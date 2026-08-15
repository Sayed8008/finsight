"""Data access for subscriptions.

The category is `LEFT OUTER JOIN`ed rather than inner joined, unlike everywhere
else: `subscriptions.category_id` is nullable, because a subscription detected
from transaction history has not been categorised yet (Phase 9.5). An inner
join would silently drop exactly those rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, contains_eager

from app.models.enums import BillingCycle, SubscriptionStatus
from app.models.subscription import Subscription


class SubscriptionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ─── Reading ──────────────────────────────────────────────────────────

    def list_for_user(
        self,
        user_id: int,
        *,
        status: SubscriptionStatus | None = None,
        category_id: int | None = None,
        due_before: date | None = None,
    ) -> list[Subscription]:
        """This user's subscriptions, soonest renewal first.

        `due_before` answers "what renews in the next N days". Combined with a
        status of ACTIVE it matches the `(user_id, status, next_billing_date)`
        index exactly — the index exists for this query, so the clauses are
        written in the order it expects.
        """
        statement: Select[tuple[Subscription]] = (
            select(Subscription)
            # Outer, because category_id is nullable here.
            .outerjoin(Subscription.category)
            .options(contains_eager(Subscription.category))
            .where(Subscription.user_id == user_id)
        )

        if status is not None:
            statement = statement.where(Subscription.status == status)
        if category_id is not None:
            statement = statement.where(Subscription.category_id == category_id)
        if due_before is not None:
            statement = statement.where(Subscription.next_billing_date <= due_before)

        statement = statement.order_by(
            Subscription.next_billing_date,
            Subscription.name,
            # A unique tie-breaker, so two subscriptions renewing on the same
            # day with the same name have a defined order.
            Subscription.id,
        )
        return list(self._session.execute(statement).scalars())

    def get_for_user(self, subscription_id: int, user_id: int) -> Subscription | None:
        """One subscription, or None if it is not this user's."""
        statement = (
            select(Subscription)
            .outerjoin(Subscription.category)
            .options(contains_eager(Subscription.category))
            .where(Subscription.id == subscription_id, Subscription.user_id == user_id)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def totals_by_status_and_cycle(
        self, user_id: int
    ) -> dict[tuple[SubscriptionStatus, BillingCycle], tuple[int, Decimal]]:
        """Count and total amount per (status, cycle) pair, in one query.

        The summary needs a monthly-equivalent total across every subscription.
        Converting row by row would mean fetching them all; grouping here means
        the service converts once per *cycle* — twelve multiplications at the
        very most, whatever the number of subscriptions. Grouping by status in
        the same query rather than running one per status keeps it to a single
        round trip.
        """
        statement = (
            select(
                Subscription.status,
                Subscription.billing_cycle,
                func.count(Subscription.id),
                func.coalesce(func.sum(Subscription.amount), 0),
            )
            .where(Subscription.user_id == user_id)
            .group_by(Subscription.status, Subscription.billing_cycle)
        )
        return {
            (status, cycle): (count, Decimal(total))
            for status, cycle, count, total in self._session.execute(statement)
        }

    def name_exists(self, user_id: int, name: str, *, exclude_id: int | None = None) -> bool:
        """Whether this user already tracks a subscription by this name.

        Matched case-insensitively. There is no unique constraint for this —
        two genuinely different plans could share a name — so this backs a
        warning rather than a refusal, and is used by detection in Phase 9.5 to
        avoid proposing something already tracked.
        """
        statement = select(Subscription.id).where(
            Subscription.user_id == user_id,
            func.lower(Subscription.name) == name.lower(),
        )
        if exclude_id is not None:
            statement = statement.where(Subscription.id != exclude_id)

        return self._session.execute(statement).first() is not None

    # ─── Writing ──────────────────────────────────────────────────────────

    def add(self, subscription: Subscription) -> Subscription:
        self._session.add(subscription)
        self._session.flush()
        return subscription

    def delete(self, subscription: Subscription) -> None:
        self._session.delete(subscription)
        self._session.flush()
