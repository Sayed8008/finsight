"""Subscription rules, costs and renewal timing.

The decision that shapes this module: **`next_billing_date` is never supplied
by a client.** It is derived from `start_date` and the cycle, recomputed
whenever either changes, and advanced by `renew()` when a charge is taken.
Accepting it as an input would allow a subscription whose start date, cycle and
next charge disagree, with no way to tell which was meant.

Everything derived — monthly cost, yearly cost, days until renewal — is
computed on read (ADR-015) by `billing_cycle`, which is pure and separately
tested.

Status is not a free-for-all either:

  * **active** — being charged, counted in the totals;
  * **paused** — expected to resume, so still listed but excluded from totals
    and from upcoming renewals;
  * **cancelled** — finished. Kept for history, excluded from everything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import NotFound, ValidationFailed
from app.core.money import ZERO, quantise
from app.models.category import Category
from app.models.enums import BillingCycle, SubscriptionStatus
from app.models.subscription import Subscription
from app.repositories.subscription_repository import SubscriptionRepository
from app.services.billing_cycle import (
    days_until,
    monthly_equivalent,
    next_billing_after,
    yearly_equivalent,
)
from app.services.category_service import CategoryService

logger = logging.getLogger(__name__)

#: How many days ahead counts as "due soon". A week is long enough to act on a
#: renewal — cancel it, move money — and short enough that the badge means
#: something.
DUE_SOON_DAYS = 7

#: Statuses that cost money. Paused subscriptions are not being charged, so
#: including them would overstate what the user actually pays.
BILLABLE = (SubscriptionStatus.ACTIVE,)


class SubscriptionNotFound(NotFound):
    message = "That subscription was not found."


class SubscriptionEnded(ValidationFailed):
    message = "That subscription has ended and cannot be renewed."


@dataclass(frozen=True)
class SubscriptionView:
    """A subscription plus what it costs and when it next renews.

    Exposes the stored fields too, so a route can call
    `SubscriptionResponse.model_validate(view)` without a third list of field
    names to keep in step.
    """

    subscription: Subscription
    on_day: date

    def __getattr__(self, name: str) -> Any:
        """Fall through to the stored row for anything not computed here.

        Saves a dozen one-line properties. Python only calls this for names the
        class does not define, so a computed field can never be shadowed by a
        column of the same name.

        The guard matters: without it, an attribute lookup before `subscription`
        is set would recurse into this method forever instead of raising.
        """
        if name.startswith("_") or name == "subscription":
            raise AttributeError(name)
        return getattr(self.subscription, name)

    @property
    def monthly_cost(self) -> Decimal:
        return monthly_equivalent(self.subscription.amount, self.subscription.billing_cycle)

    @property
    def yearly_cost(self) -> Decimal:
        return yearly_equivalent(self.subscription.amount, self.subscription.billing_cycle)

    @property
    def days_until_renewal(self) -> int:
        return days_until(self.subscription.next_billing_date, self.on_day)

    @property
    def is_due_soon(self) -> bool:
        """Due within the window — including overdue, which is more urgent still."""
        return (
            self.subscription.status is SubscriptionStatus.ACTIVE
            and self.days_until_renewal <= DUE_SOON_DAYS
        )


@dataclass(frozen=True)
class Commitment:
    """Totals across a user's subscriptions."""

    active_count: int
    paused_count: int
    cancelled_count: int
    monthly_total: Decimal
    yearly_total: Decimal
    next_renewal: SubscriptionView | None


class SubscriptionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._subscriptions = SubscriptionRepository(session)
        self._categories = CategoryService(session)

    # ─── Reading ──────────────────────────────────────────────────────────

    def list_subscriptions(
        self,
        user_id: int,
        *,
        status: SubscriptionStatus | None = None,
        category_id: int | None = None,
        due_within_days: int | None = None,
        today: date | None = None,
    ) -> list[SubscriptionView]:
        """Subscriptions, soonest renewal first."""
        on_day = today or date.today()
        due_before = (
            on_day + timedelta(days=due_within_days) if due_within_days is not None else None
        )

        rows = self._subscriptions.list_for_user(
            user_id,
            status=status,
            category_id=category_id,
            due_before=due_before,
        )
        return [SubscriptionView(row, on_day) for row in rows]

    def get(
        self, user_id: int, subscription_id: int, *, today: date | None = None
    ) -> SubscriptionView:
        subscription = self._subscriptions.get_for_user(subscription_id, user_id)
        if subscription is None:
            raise SubscriptionNotFound
        return SubscriptionView(subscription, today or date.today())

    def summary(self, user_id: int, *, today: date | None = None) -> Commitment:
        """What the user is committed to.

        The totals come from one grouped query rather than from the rows, so
        the cost of this does not grow with the number of subscriptions:
        conversion happens once per *cycle*, four times at most.
        """
        on_day = today or date.today()
        totals = self._subscriptions.totals_by_status_and_cycle(user_id)

        monthly = ZERO
        yearly = ZERO
        for (status, cycle), (_, total) in totals.items():
            if status in BILLABLE:
                monthly += monthly_equivalent(total, cycle)
                yearly += yearly_equivalent(total, cycle)

        upcoming = self.list_subscriptions(user_id, status=SubscriptionStatus.ACTIVE, today=on_day)

        return Commitment(
            active_count=_count_with_status(totals, SubscriptionStatus.ACTIVE),
            paused_count=_count_with_status(totals, SubscriptionStatus.PAUSED),
            cancelled_count=_count_with_status(totals, SubscriptionStatus.CANCELLED),
            monthly_total=quantise(monthly),
            yearly_total=quantise(yearly),
            next_renewal=upcoming[0] if upcoming else None,
        )

    # ─── Writing ──────────────────────────────────────────────────────────

    def create(
        self, user_id: int, data: dict[str, Any], *, today: date | None = None
    ) -> SubscriptionView:
        """Track a new subscription.

        `next_billing_date` is computed, not accepted. For a subscription that
        started in the past this lands on the next charge from today; for one
        starting later it is the start date itself.
        """
        on_day = today or date.today()
        payload = dict(data)

        category_id = payload.get("category_id")
        if category_id is not None:
            self._require_own_category(user_id, category_id)

        subscription = Subscription(
            user_id=user_id,
            next_billing_date=self._first_billing_date(
                payload["start_date"], payload["billing_cycle"], on_day
            ),
            **payload,
        )

        self._subscriptions.add(subscription)
        self._session.commit()

        logger.info(
            "Tracking subscription id=%s (%s, %s/%s) for user id=%s",
            subscription.id,
            subscription.name,
            subscription.amount,
            subscription.billing_cycle,
            user_id,
        )
        return SubscriptionView(subscription, on_day)

    def update(
        self,
        user_id: int,
        subscription_id: int,
        changes: dict[str, Any],
        *,
        today: date | None = None,
    ) -> SubscriptionView:
        """Apply a partial update, recomputing the renewal date if it moved.

        Changing the start date or the cycle changes when the next charge
        falls. Leaving `next_billing_date` alone would leave a subscription
        claiming a schedule its own anchor and cycle disagree with.
        """
        on_day = today or date.today()
        view = self.get(user_id, subscription_id, today=on_day)
        subscription = view.subscription

        if changes.get("category_id") is not None:
            self._require_own_category(user_id, changes["category_id"])

        new_start = changes.get("start_date", subscription.start_date)
        new_end = changes.get("end_date", subscription.end_date)
        if new_end is not None and new_end < new_start:
            # Reachable when only one of the two is sent.
            raise ValidationFailed("The end date cannot be before the start date.")

        for field, value in changes.items():
            setattr(subscription, field, value)

        if "start_date" in changes or "billing_cycle" in changes:
            subscription.next_billing_date = self._first_billing_date(
                subscription.start_date, subscription.billing_cycle, on_day
            )

        self._session.commit()
        logger.info(
            "Updated subscription id=%s for user id=%s (fields: %s)",
            subscription.id,
            user_id,
            ", ".join(sorted(changes)) or "none",
        )
        return SubscriptionView(subscription, on_day)

    def renew(
        self, user_id: int, subscription_id: int, *, today: date | None = None
    ) -> SubscriptionView:
        """Record that the charge was taken, and move to the next one.

        The new date is computed from the original anchor, not by adding a
        cycle to the current one. Stepping forward from a clamped date is how a
        subscription that bills on the 31st quietly moves to the 28th and stays
        there (see `billing_cycle`).
        """
        on_day = today or date.today()
        view = self.get(user_id, subscription_id, today=on_day)
        subscription = view.subscription

        if subscription.status is SubscriptionStatus.CANCELLED:
            raise SubscriptionEnded

        following = next_billing_after(
            subscription.start_date,
            subscription.billing_cycle,
            subscription.next_billing_date,
        )

        if subscription.end_date is not None and following > subscription.end_date:
            # The subscription has run its course; renewing past its own end
            # date would invent a charge that will not happen.
            subscription.status = SubscriptionStatus.CANCELLED
            logger.info("Subscription id=%s reached its end date; cancelling", subscription.id)
        else:
            subscription.next_billing_date = following

        self._session.commit()
        return SubscriptionView(subscription, on_day)

    def delete(self, user_id: int, subscription_id: int) -> None:
        """Delete a subscription outright.

        Distinct from cancelling it, which keeps the record. Deleting is for
        something tracked by mistake.
        """
        subscription = self._subscriptions.get_for_user(subscription_id, user_id)
        if subscription is None:
            raise SubscriptionNotFound

        self._subscriptions.delete(subscription)
        self._session.commit()
        logger.info("Deleted subscription id=%s for user id=%s", subscription_id, user_id)

    # ─── Rules ────────────────────────────────────────────────────────────

    def _require_own_category(self, user_id: int, category_id: int) -> Category:
        """Answers 404 for another user's category, as everywhere else."""
        return self._categories.get(user_id, category_id)

    @staticmethod
    def _first_billing_date(start: date, cycle: BillingCycle, today: date) -> date:
        """When the next charge falls for a subscription anchored at `start`.

        A subscription entered today with a start date in the past has already
        been charged some number of times; the useful date is the next one, not
        the first one. A start date in the future is itself the next charge.
        """
        if start > today:
            return start
        return next_billing_after(start, cycle, today - timedelta(days=1))


def _count_with_status(
    totals: dict[tuple[SubscriptionStatus, BillingCycle], tuple[int, Decimal]],
    status: SubscriptionStatus,
) -> int:
    return sum(count for (row_status, _), (count, _total) in totals.items() if row_status is status)
