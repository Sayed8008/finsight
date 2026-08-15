"""Data access for budgets.

The method worth reading is `spend_by_budget`. Each budget covers its own date
range, so the obvious implementation is a `SUM` per budget — which is an N+1:
twelve budgets, twelve round trips, and it grows with the data. Instead the
budgets table is joined *to* the transactions table on the range itself, so one
query returns the spend for every budget at once whatever periods they cover.

As everywhere, every method takes a `user_id` and puts it in the WHERE clause.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, contains_eager

from app.core.money import ZERO
from app.models.budget import Budget
from app.models.category import Category
from app.models.enums import TransactionType
from app.models.transaction import Transaction


class BudgetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ─── Reading ──────────────────────────────────────────────────────────

    def list_for_user(
        self,
        user_id: int,
        *,
        category_id: int | None = None,
        active_on: date | None = None,
    ) -> list[Budget]:
        """This user's budgets, newest period first.

        `active_on` narrows to budgets whose period contains that date — what
        "show me my current budgets" means. The category is eager-loaded on the
        same join used for ordering, so rendering a list of budget cards with
        their category names costs one query rather than one per card.
        """
        statement: Select[tuple[Budget]] = (
            select(Budget)
            .join(Budget.category)
            .options(contains_eager(Budget.category))
            .where(Budget.user_id == user_id)
        )

        if category_id is not None:
            statement = statement.where(Budget.category_id == category_id)
        if active_on is not None:
            # Inclusive both ends, matching how the period is defined.
            statement = statement.where(
                Budget.period_start <= active_on,
                Budget.period_end >= active_on,
            )

        statement = statement.order_by(
            Budget.period_start.desc(),
            Category.name,
            # A unique tie-breaker, for the same reason the transaction list
            # has one: budgets sharing a period and category name would
            # otherwise have no defined order between them.
            Budget.id.desc(),
        )
        return list(self._session.execute(statement).scalars())

    def get_for_user(self, budget_id: int, user_id: int) -> Budget | None:
        """One budget, or None if it does not exist *or* is not this user's."""
        statement = (
            select(Budget)
            .join(Budget.category)
            .options(contains_eager(Budget.category))
            .where(Budget.id == budget_id, Budget.user_id == user_id)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def spend_by_budget(
        self, user_id: int, budget_ids: Sequence[int] | None = None
    ) -> dict[int, Decimal]:
        """Total expense per budget, in one query, whatever periods they cover.

        The join condition carries the date range from each budget row, so
        every budget is matched against exactly the transactions inside its own
        period. That is what makes a single `GROUP BY` possible here — a plain
        `WHERE date BETWEEN ...` could only ever express one range.

        A LEFT JOIN with `COALESCE`, so a budget with no spending yet comes back
        as zero rather than being missing from the result and having to be
        defaulted by the caller.

        Only expenses count. Income filed against the same category — a refund
        recorded as income, say — is not spending and must not reduce it.
        """
        spent = func.coalesce(func.sum(Transaction.amount), 0).label("spent")

        statement = (
            select(Budget.id, spent)
            .select_from(Budget)
            .outerjoin(
                Transaction,
                and_(
                    Transaction.user_id == Budget.user_id,
                    Transaction.category_id == Budget.category_id,
                    Transaction.transaction_type == TransactionType.EXPENSE,
                    Transaction.date >= Budget.period_start,
                    Transaction.date <= Budget.period_end,
                ),
            )
            .where(Budget.user_id == user_id)
            .group_by(Budget.id)
        )

        if budget_ids is not None:
            if not budget_ids:
                # `IN ()` is not valid SQL, and there is nothing to ask anyway.
                return {}
            statement = statement.where(Budget.id.in_(budget_ids))

        return {
            budget_id: Decimal(total) if total is not None else ZERO
            for budget_id, total in self._session.execute(statement)
        }

    def find_overlapping(
        self,
        user_id: int,
        category_id: int,
        period_start: date,
        period_end: date,
        *,
        exclude_id: int | None = None,
    ) -> Budget | None:
        """An existing budget for this category whose period overlaps.

        Two ranges overlap when each starts on or before the other ends. Worth
        stating explicitly because the intuitive version — comparing starts to
        starts — misses the case of one period entirely inside another.

        `exclude_id` is for editing: a budget never conflicts with itself.
        """
        statement = select(Budget).where(
            Budget.user_id == user_id,
            Budget.category_id == category_id,
            Budget.period_start <= period_end,
            Budget.period_end >= period_start,
        )
        if exclude_id is not None:
            statement = statement.where(Budget.id != exclude_id)

        return self._session.execute(statement.limit(1)).scalar_one_or_none()

    # ─── Writing ──────────────────────────────────────────────────────────

    def add(self, budget: Budget) -> Budget:
        self._session.add(budget)
        self._session.flush()
        return budget

    def delete(self, budget: Budget) -> None:
        self._session.delete(budget)
        self._session.flush()
