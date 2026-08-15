"""Analytics: trends over time, and one period against another.

Two questions this answers that the dashboard does not:

  * **"How has this moved?"** — income and expense per month across a span,
    with the empty months filled in. A database returns only the months that
    have rows; a chart with a gap where March should be is a chart that lies
    about March.
  * **"Compared to what?"** — a period beside the one immediately before it,
    of the same length, with the difference per category. A number on its own
    is not information; 12,000 spent on food is only meaningful next to last
    month's 8,000.

The comparison window is derived, not asked for. Given 1–31 March it uses
1–28 February: the same length, ending the day before. Making the caller supply
four dates would let them compare a month against a fortnight and read the
result as a 50% saving.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailed
from app.core.money import ZERO, percentage_of, quantise
from app.repositories.analytics_repository import AnalyticsRepository, MonthTotals

logger = logging.getLogger(__name__)

#: How far back a trend may be asked for. Two years of monthly bars is already
#: past the point where individual months can be read.
MAX_TREND_MONTHS = 24
DEFAULT_TREND_MONTHS = 6


@dataclass(frozen=True)
class Change:
    """A figure, what it was before, and the difference.

    `percentage` is None when the previous value was zero: going from nothing
    to something is not a percentage increase, it is a start, and "+∞%" or a
    silent 0% would both be wrong.
    """

    current: Decimal
    previous: Decimal
    difference: Decimal
    percentage: Decimal | None

    @classmethod
    def between(cls, current: Decimal, previous: Decimal) -> Change:
        difference = quantise(current - previous)
        percentage = percentage_of(difference, previous) if previous != ZERO else None
        return cls(
            current=quantise(current),
            previous=quantise(previous),
            difference=difference,
            percentage=percentage,
        )

    @property
    def is_new(self) -> bool:
        """Nothing before, something now — the case a percentage cannot express."""
        return self.previous == ZERO and self.current != ZERO


@dataclass(frozen=True)
class CategoryChange:
    """One category's spend, this period against last."""

    category_id: int | None
    name: str
    color: str | None
    change: Change


@dataclass(frozen=True)
class Comparison:
    """Two periods, side by side."""

    period_start: date
    period_end: date
    previous_start: date
    previous_end: date
    income: Change
    expense: Change
    net: Change
    categories: list[CategoryChange]


@dataclass(frozen=True)
class Trend:
    """Income and expense per month across a span, gaps included."""

    months: list[MonthTotals]

    @property
    def has_activity(self) -> bool:
        return any(month.income or month.expense for month in self.months)


class AnalyticsService:
    def __init__(self, session: Session) -> None:
        self._analytics = AnalyticsRepository(session)

    # ─── Trend ────────────────────────────────────────────────────────────

    def trend(
        self, user_id: int, *, months: int = DEFAULT_TREND_MONTHS, today: date | None = None
    ) -> Trend:
        """The last N calendar months, including the current one.

        Months with no transactions are returned as zeroes rather than omitted.
        A bar chart that simply skips March puts February next to April and
        makes a two-month gap look like one month of change.
        """
        if not 1 <= months <= MAX_TREND_MONTHS:
            raise ValidationFailed(f"Months must be between 1 and {MAX_TREND_MONTHS}.")

        on_day = today or date.today()
        span = _months_back(on_day, months - 1)
        start = date(span.year, span.month, 1)
        end = _end_of_month(on_day)

        found = {
            (row.year, row.month): row
            for row in self._analytics.monthly_series(user_id, start, end)
        }

        filled: list[MonthTotals] = []
        cursor = start
        while cursor <= end:
            row = found.get((cursor.year, cursor.month))
            filled.append(
                row or MonthTotals(year=cursor.year, month=cursor.month, income=ZERO, expense=ZERO)
            )
            cursor = _months_forward(cursor, 1)

        return Trend(months=filled)

    # ─── Comparison ───────────────────────────────────────────────────────

    def compare(
        self,
        user_id: int,
        *,
        start: date | None = None,
        end: date | None = None,
        today: date | None = None,
    ) -> Comparison:
        """A period against the one immediately before it, of equal length."""
        on_day = today or date.today()
        period_start, period_end = self._resolve_period(start, end, on_day)
        previous_start, previous_end = _preceding_window(period_start, period_end)

        current_totals = self._analytics.totals_for_period(user_id, period_start, period_end)
        previous_totals = self._analytics.totals_for_period(user_id, previous_start, previous_end)

        return Comparison(
            period_start=period_start,
            period_end=period_end,
            previous_start=previous_start,
            previous_end=previous_end,
            income=Change.between(current_totals.income, previous_totals.income),
            expense=Change.between(current_totals.expense, previous_totals.expense),
            net=Change.between(current_totals.net, previous_totals.net),
            categories=self._category_changes(
                user_id, period_start, period_end, previous_start, previous_end
            ),
        )

    def _category_changes(
        self,
        user_id: int,
        start: date,
        end: date,
        previous_start: date,
        previous_end: date,
    ) -> list[CategoryChange]:
        """Every category that appears in either period, biggest mover first.

        The union matters. Listing only this period's categories would hide the
        most useful finding of all — something the user *stopped* spending on,
        which shows as a large fall and would otherwise vanish from the report.
        """
        current = {
            row.category_id: row for row in self._analytics.spend_by_category(user_id, start, end)
        }
        previous = {
            row.category_id: row
            for row in self._analytics.spend_by_category(user_id, previous_start, previous_end)
        }

        changes = [
            CategoryChange(
                category_id=category_id,
                name=(current.get(category_id) or previous[category_id]).name,
                color=(current.get(category_id) or previous[category_id]).color,
                change=Change.between(
                    current[category_id].total if category_id in current else ZERO,
                    previous[category_id].total if category_id in previous else ZERO,
                ),
            )
            for category_id in {**previous, **current}
        ]

        # Biggest movement first, in either direction — a large fall is as
        # interesting as a large rise, and sorting by the signed value would
        # bury one of them.
        changes.sort(key=lambda row: abs(row.change.difference), reverse=True)
        return changes

    @staticmethod
    def _resolve_period(start: date | None, end: date | None, today: date) -> tuple[date, date]:
        default_start = date(today.year, today.month, 1)
        default_end = _end_of_month(today)
        resolved_start = start or default_start
        resolved_end = end or default_end

        if resolved_end < resolved_start:
            raise ValidationFailed("The period cannot end before it starts.")

        return resolved_start, resolved_end


# ─── Calendar helpers ─────────────────────────────────────────────────────


def _end_of_month(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _months_back(day: date, count: int) -> date:
    total = day.month - 1 - count
    year = day.year + total // 12
    month = total % 12 + 1
    return date(year, month, 1)


def _months_forward(day: date, count: int) -> date:
    total = day.month - 1 + count
    year = day.year + total // 12
    month = total % 12 + 1
    return date(year, month, 1)


def _preceding_window(start: date, end: date) -> tuple[date, date]:
    """The window of the same length ending the day before `start`.

    Length in days, not in calendar months, so comparing 1–31 March gives
    29–28 February rather than a February that is three days shorter. Equal
    lengths are what makes the two totals comparable at all.
    """
    length = (end - start).days
    previous_end = start - timedelta(days=1)
    return previous_end - timedelta(days=length), previous_end
