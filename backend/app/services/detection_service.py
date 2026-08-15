"""Gathering history for the recurrence detector, and filtering its results.

The only part of detection that touches a database. It fetches the expense
history, hands it to the pure detector in `recurrence`, and drops candidates
the user already tracks.

**It creates nothing** (ADR-007). Every candidate comes back as a proposal with
its evidence attached, and the user decides. A wrong guess appearing silently
in someone's monthly commitment would be worse than not finding it.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailed
from app.models.enums import TransactionType
from app.models.transaction import Transaction
from app.repositories.subscription_repository import SubscriptionRepository
from app.services.recurrence import Candidate, Charge, detect

logger = logging.getLogger(__name__)

#: How far back to look. A year covers four quarterly charges or one yearly
#: one; going further mostly adds cancelled services and old prices.
DEFAULT_LOOKBACK_DAYS = 365
MAX_LOOKBACK_DAYS = 1095


class DetectionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._subscriptions = SubscriptionRepository(session)

    def detect(
        self,
        user_id: int,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        include_tracked: bool = False,
        today: date | None = None,
    ) -> list[Candidate]:
        """Propose subscriptions found in this user's transaction history."""
        if not 1 <= lookback_days <= MAX_LOOKBACK_DAYS:
            raise ValidationFailed(f"Lookback must be between 1 and {MAX_LOOKBACK_DAYS} days.")

        on_day = today or date.today()
        charges = self._charges(user_id, on_day - timedelta(days=lookback_days), on_day)
        candidates = detect(charges)

        if not include_tracked:
            candidates = [
                candidate
                for candidate in candidates
                if not self._subscriptions.name_exists(user_id, candidate.name)
            ]

        logger.info(
            "Detection for user id=%s over %s charges proposed %s candidate(s)",
            user_id,
            len(charges),
            len(candidates),
        )
        return candidates

    def _charges(self, user_id: int, start: date, end: date) -> list[Charge]:
        """Expense history in one query.

        Expenses only: a subscription is money going out, and including income
        would let a regular salary be proposed as something to cancel.

        Rows without a description are left out here rather than inside the
        detector — there is nothing in them to match on, and fetching them only
        to discard them wastes the trip.
        """
        statement = (
            select(
                Transaction.id,
                Transaction.date,
                Transaction.amount,
                Transaction.description,
                Transaction.category_id,
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.date >= start,
                Transaction.date <= end,
                Transaction.description.is_not(None),
                Transaction.description != "",
            )
            .order_by(Transaction.date)
        )

        return [
            Charge(
                transaction_id=row_id,
                date=row_date,
                amount=amount,
                description=description,
                category_id=category_id,
            )
            for row_id, row_date, amount, description, category_id in self._session.execute(
                statement
            )
        ]
