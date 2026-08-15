"""The dashboard: one request, one answer.

This service owns no table. It composes what the others already compute —
totals, category spend, recent activity, budget health, subscription
commitment — into a single payload.

That composition is the point. A dashboard assembled from five endpoints is
five round trips, five loading states, and five chances to show figures from
five different moments. One endpoint means the numbers on screen are all from
the same instant.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailed
from app.core.money import ZERO, percentage_of
from app.models.transaction import Transaction
from app.repositories.analytics_repository import AnalyticsRepository, CategoryTotal, PeriodTotals
from app.repositories.transaction_repository import SortField, TransactionRepository
from app.services.budget_service import BudgetService
from app.services.budget_utilisation import BudgetStatus
from app.services.subscription_service import Commitment, SubscriptionService

logger = logging.getLogger(__name__)

#: How many transactions the "recent activity" panel shows. Enough to recognise
#: the last few things you did, not enough to be a second transactions table.
RECENT_LIMIT = 5

#: How many categories the spending chart names individually. Past this the
#: tail is folded into one "Other" row — adjacent classes stop being tellable
#: apart, whatever colours are used (ADR-026).
TOP_CATEGORIES = 6

OTHER_LABEL = "Other categories"


def month_bounds(day: date) -> tuple[date, date]:
    """First and last day of the month containing `day`."""
    last = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, 1), date(day.year, day.month, last)


@dataclass(frozen=True)
class CategoryShare:
    """One slice of the spending breakdown."""

    category_id: int | None
    name: str
    color: str | None
    total: Decimal
    #: Share of the period's total spend. Zero when nothing was spent.
    percentage: Decimal


@dataclass(frozen=True)
class BudgetHealth:
    """Headline counts, not the budgets themselves.

    The dashboard says "2 of 5 budgets need attention" and links onward; it
    does not reproduce the budgets screen.
    """

    total: int
    on_track: int
    warning: int
    exceeded: int

    @property
    def needs_attention(self) -> int:
        return self.warning + self.exceeded


@dataclass(frozen=True)
class Dashboard:
    """Everything the first screen needs."""

    period_start: date
    period_end: date
    totals: PeriodTotals
    spending: list[CategoryShare]
    recent: list[Transaction]
    budgets: BudgetHealth
    subscriptions: Commitment


class DashboardService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._analytics = AnalyticsRepository(session)
        self._transactions = TransactionRepository(session)
        self._budgets = BudgetService(session)
        self._subscriptions = SubscriptionService(session)

    def build(
        self,
        user_id: int,
        *,
        start: date | None = None,
        end: date | None = None,
        today: date | None = None,
    ) -> Dashboard:
        """Assemble the dashboard for a period, defaulting to this month."""
        on_day = today or date.today()
        period_start, period_end = self._resolve_period(start, end, on_day)

        totals = self._analytics.totals_for_period(user_id, period_start, period_end)
        spending = self._spending_breakdown(user_id, period_start, period_end)
        recent, _ = self._transactions.list_page(
            user_id, page=1, page_size=RECENT_LIMIT, sort_by=SortField.DATE
        )
        budgets = self._budget_health(user_id, on_day)
        subscriptions = self._subscriptions.summary(user_id, today=on_day)

        return Dashboard(
            period_start=period_start,
            period_end=period_end,
            totals=totals,
            spending=spending,
            recent=recent,
            budgets=budgets,
            subscriptions=subscriptions,
        )

    @staticmethod
    def _resolve_period(start: date | None, end: date | None, today: date) -> tuple[date, date]:
        """Work out the period, defaulting each end independently.

        "This month" is the default because it is the period a person is
        actually inside — last month is history, and the year to date is a
        different question.
        """
        default_start, default_end = month_bounds(today)
        resolved_start = start or default_start
        resolved_end = end or default_end

        if resolved_end < resolved_start:
            raise ValidationFailed("The period cannot end before it starts.")

        return resolved_start, resolved_end

    def _spending_breakdown(self, user_id: int, start: date, end: date) -> list[CategoryShare]:
        """The top categories by spend, with the tail folded into one row.

        Percentages are of the *whole* period's spend, not of the shown rows,
        so the listed shares plus "Other" always come to 100 rather than the
        top six being rescaled to fill the chart.
        """
        top = self._analytics.spend_by_category(user_id, start, end, limit=TOP_CATEGORIES)
        if not top:
            return []

        overall = self._analytics.total_spend(user_id, start, end)
        shares = [self._share(row, overall) for row in top]

        remainder = overall - sum((row.total for row in top), ZERO)
        if remainder > ZERO:
            shares.append(
                CategoryShare(
                    category_id=None,
                    name=OTHER_LABEL,
                    color=None,
                    total=remainder,
                    percentage=percentage_of(remainder, overall),
                )
            )

        return shares

    @staticmethod
    def _share(row: CategoryTotal, overall: Decimal) -> CategoryShare:
        return CategoryShare(
            category_id=row.category_id,
            name=row.name,
            color=row.color,
            total=row.total,
            percentage=percentage_of(row.total, overall),
        )

    def _budget_health(self, user_id: int, today: date) -> BudgetHealth:
        """Counts by status across the budgets running today.

        Only current ones: a budget that ended last month cannot need
        attention, and counting it would keep the dashboard permanently amber.
        """
        snapshots = self._budgets.list_budgets(user_id, current_only=True, today=today)
        by_status = [snapshot.status for snapshot in snapshots]

        return BudgetHealth(
            total=len(by_status),
            on_track=by_status.count(BudgetStatus.HEALTHY),
            warning=by_status.count(BudgetStatus.WARNING),
            exceeded=by_status.count(BudgetStatus.EXCEEDED),
        )
