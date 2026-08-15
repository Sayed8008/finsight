"""Aggregate queries over transactions.

Every method here returns totals, not rows. The dashboard and the analytics
screen both need "how much, grouped by something, over a period", and the
alternative — fetching a user's transactions and adding them up in Python —
gets slower in exact proportion to the history it summarises. `SUM` and
`GROUP BY` are what a database is for.

Shared by Phase 7's dashboard and Phase 8's analytics, so the grouping is
written once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.money import ZERO
from app.models.category import Category
from app.models.enums import TransactionType
from app.models.transaction import Transaction


@dataclass(frozen=True)
class PeriodTotals:
    """Income, expense and count for one period."""

    income: Decimal
    expense: Decimal
    transaction_count: int

    @property
    def net(self) -> Decimal:
        """What was kept. Negative when more went out than came in."""
        return self.income - self.expense


@dataclass(frozen=True)
class CategoryTotal:
    """One category's spend, with enough to render it."""

    category_id: int
    name: str
    color: str | None
    total: Decimal


class AnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _in_period(self, user_id: int, start: date, end: date) -> list:
        """The clauses every aggregate here shares.

        One method, so the dashboard and the analytics screen cannot end up
        summarising subtly different sets of rows.
        """
        return [
            Transaction.user_id == user_id,
            Transaction.date >= start,
            Transaction.date <= end,
        ]

    def totals_for_period(self, user_id: int, start: date, end: date) -> PeriodTotals:
        """Income and expense for a period, in one query.

        Conditional aggregation — `SUM(CASE WHEN ...)` — rather than two
        queries. One pass over the same index range answers both, and the two
        figures cannot come from different snapshots of the table.
        """
        income = func.coalesce(
            func.sum(
                func.if_(
                    Transaction.transaction_type == TransactionType.INCOME, Transaction.amount, 0
                )
            ),
            0,
        )
        expense = func.coalesce(
            func.sum(
                func.if_(
                    Transaction.transaction_type == TransactionType.EXPENSE, Transaction.amount, 0
                )
            ),
            0,
        )

        statement = select(income, expense, func.count(Transaction.id)).where(
            *self._in_period(user_id, start, end)
        )
        total_income, total_expense, count = self._session.execute(statement).one()

        return PeriodTotals(
            income=Decimal(total_income),
            expense=Decimal(total_expense),
            transaction_count=int(count),
        )

    def spend_by_category(
        self, user_id: int, start: date, end: date, *, limit: int | None = None
    ) -> list[CategoryTotal]:
        """Expense per category over a period, largest first.

        Expenses only: income filed against a category is not spending, and
        mixing the two would make the shares meaningless.

        `limit` takes the top N. The caller folds whatever is left into an
        "Other" row rather than showing a dozen slivers — past about seven
        classes, adjacent ones stop being tellable apart whatever colours are
        used.
        """
        total = func.coalesce(func.sum(Transaction.amount), 0).label("total")

        statement: Select = (
            select(Category.id, Category.name, Category.color, total)
            .join(Transaction, Transaction.category_id == Category.id)
            .where(
                *self._in_period(user_id, start, end),
                Transaction.transaction_type == TransactionType.EXPENSE,
            )
            .group_by(Category.id, Category.name, Category.color)
            # Largest first, then by name so two equal totals have a defined
            # order rather than swapping between requests.
            .order_by(total.desc(), Category.name)
        )
        if limit is not None:
            statement = statement.limit(limit)

        return [
            CategoryTotal(category_id=row_id, name=name, color=color, total=Decimal(amount))
            for row_id, name, color, amount in self._session.execute(statement)
        ]

    def total_spend(self, user_id: int, start: date, end: date) -> Decimal:
        """All expense in a period. Used to work out what the top N left out."""
        statement = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            *self._in_period(user_id, start, end),
            Transaction.transaction_type == TransactionType.EXPENSE,
        )
        result = self._session.execute(statement).scalar_one()
        return Decimal(result) if result is not None else ZERO
