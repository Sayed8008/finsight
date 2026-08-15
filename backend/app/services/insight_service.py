"""Assembling the snapshot the insight rules run against.

This is the only part of the insights feature that touches a database. It
gathers what the rules need — the period's totals, current budgets, active
subscriptions, category movement — maps each into the plain facts the rules
understand, and hands the whole thing over.

Keeping the gathering here and the reasoning in `insight_rules` is what makes
the rules testable by building three fields. It also fixes the cost of the
screen: the queries are all in one method, so "how expensive is this page" has
an answer that does not depend on which rules happen to fire.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.enums import SubscriptionStatus
from app.repositories.analytics_repository import AnalyticsRepository
from app.services.analytics_service import AnalyticsService
from app.services.budget_service import BudgetService
from app.services.insight_rules import (
    BudgetFact,
    CategoryFact,
    InsightReport,
    InsightSnapshot,
    SubscriptionFact,
    evaluate,
)
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class InsightService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._analytics = AnalyticsRepository(session)
        self._comparisons = AnalyticsService(session)
        self._budgets = BudgetService(session)
        self._subscriptions = SubscriptionService(session)

    def report(
        self,
        user_id: int,
        *,
        start: date | None = None,
        end: date | None = None,
        today: date | None = None,
    ) -> InsightReport:
        """Gather a snapshot and run the rules over it.

        A convenience for callers that do not need the snapshot itself. Anyone
        who does — the endpoint, which reports the period alongside the
        findings — should build it once and call `evaluate`, rather than paying
        for the gathering twice.
        """
        return self.evaluate(self.snapshot(user_id, start=start, end=end, today=today))

    @staticmethod
    def evaluate(snapshot: InsightSnapshot) -> InsightReport:
        """Run the rules over an already-gathered snapshot."""
        report = evaluate(snapshot)
        logger.info(
            "Evaluated insights: %s found, %s needing attention",
            len(report.insights),
            report.needs_attention,
        )
        return report

    def snapshot(
        self,
        user_id: int,
        *,
        start: date | None = None,
        end: date | None = None,
        today: date | None = None,
    ) -> InsightSnapshot:
        """Everything the rules are allowed to see, for one user and period.

        Exposed separately from `report` so a test can inspect what the rules
        were given, rather than inferring it from what they concluded.
        """
        on_day = today or date.today()
        comparison = self._comparisons.compare(user_id, start=start, end=end, today=on_day)
        totals = self._analytics.totals_for_period(
            user_id, comparison.period_start, comparison.period_end
        )

        return InsightSnapshot(
            today=on_day,
            period_start=comparison.period_start,
            period_end=comparison.period_end,
            income=totals.income,
            expense=totals.expense,
            transaction_count=totals.transaction_count,
            budgets=self._budget_facts(user_id, on_day),
            subscriptions=self._subscription_facts(user_id, on_day),
            categories=tuple(
                CategoryFact(
                    category_id=row.category_id or 0,
                    name=row.name,
                    current=row.change.current,
                    previous=row.change.previous,
                )
                for row in comparison.categories
            ),
            subscription_monthly_total=self._subscriptions.summary(
                user_id, today=on_day
            ).monthly_total,
            previous_expense=comparison.expense.previous,
        )

    def _budget_facts(self, user_id: int, today: date) -> tuple[BudgetFact, ...]:
        """Only budgets running today.

        One that ended last month cannot be exceeded *now*, and including it
        would leave a permanent complaint on the screen that no action could
        clear.
        """
        snapshots = self._budgets.list_budgets(user_id, current_only=True, today=today)

        return tuple(
            BudgetFact(
                category_id=snapshot.category.id,
                category_name=snapshot.category.name,
                amount=snapshot.amount,
                spent=snapshot.spent,
                remaining=snapshot.remaining,
                percentage_used=snapshot.percentage_used,
                days_remaining=snapshot.days_remaining,
                days_total=(snapshot.period_end - snapshot.period_start).days + 1,
            )
            for snapshot in snapshots
        )

    def _subscription_facts(self, user_id: int, today: date) -> tuple[SubscriptionFact, ...]:
        """Active subscriptions only.

        A paused one is not being charged and a cancelled one never will be, so
        neither can be overdue or due soon.
        """
        views = self._subscriptions.list_subscriptions(
            user_id, status=SubscriptionStatus.ACTIVE, today=today
        )

        return tuple(
            SubscriptionFact(
                subscription_id=view.id,
                name=view.name,
                amount=view.amount,
                monthly_cost=view.monthly_cost,
                days_until_renewal=view.days_until_renewal,
                is_active=True,
            )
            for view in views
        )
