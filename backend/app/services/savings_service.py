"""The savings journey: what each completed month kept, and whether it improves.

**Nothing here is stored, and nothing here computes money twice.** Monthly
income and expense already come from `AnalyticsRepository.monthly_series` — one
indexed `GROUP BY YEAR, MONTH` — and net savings is the `net` those rows
already carry. This service arranges them; it does not re-add anything up.

That is ADR-015 applied to a new screen rather than a new decision. A stored
monthly snapshot is a cache, and this application writes into *past* months
routinely: a CSV import carries a year of history, and a transaction can be
edited, recategorised or deleted long after the month it belongs to. Every one
of those would leave a stored figure wrong until something invalidated it, and
the invalidation would have to hang off every write path. Recomputed from the
same query the trend chart already uses, the journey cannot disagree with the
rest of the application, because it is not a second opinion.

**Only completed months appear.** The month in progress is not a savings
result: on the 3rd it shows a salary and almost no spending, and on the 30th it
shows the reverse. Including it would make "are you improving?" answer
differently depending on the day somebody opened the screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailed
from app.core.money import ZERO, percentage_of
from app.repositories.analytics_repository import AnalyticsRepository
from app.services.savings_rules import Badge, SavingsMonth, award, best_month, observations

#: The longest history the endpoint will assemble in one response. Not a
#: statement about how much anybody has — `ALL_TIME` is a separate request —
#: but a bound on what one query is asked to build.
MAX_SAVINGS_MONTHS = 120

#: The default window. Twelve completed months is a year of comparison and
#: matches the trend chart's own default reading.
DEFAULT_SAVINGS_MONTHS = 12

#: Asks for the whole history rather than a window of it.
ALL_TIME = 0

#: How far back "all time" is willing to look. An account cannot have activity
#: before it existed, and this bounds the scan for one that has been running
#: for years.
ALL_TIME_YEARS = 10


@dataclass(frozen=True)
class SavingsSummary:
    """The figures the header of the journey shows."""

    #: The most recent *completed* month, or None when there is none.
    latest: SavingsMonth | None
    previous: SavingsMonth | None
    best: SavingsMonth | None

    @property
    def change(self) -> Decimal:
        """Latest against previous, in money. Zero when there is no previous."""
        if self.latest is None or self.previous is None:
            return ZERO
        return self.latest.net - self.previous.net

    @property
    def change_percentage(self) -> Decimal | None:
        """The change as a share of the previous month.

        None when the previous month saved nothing, or lost money: "up 300%
        from minus 2,000" is arithmetic that means nothing to a reader, and a
        number here would be a fiction. The money figure is always shown, and
        it is the honest one.
        """
        if self.latest is None or self.previous is None:
            return None
        if self.previous.net <= ZERO:
            return None
        return percentage_of(self.change, self.previous.net)

    @property
    def is_personal_best(self) -> bool:
        return (
            self.latest is not None
            and self.best is not None
            and self.best is self.latest
            and self.latest.is_positive
        )


@dataclass(frozen=True)
class SavingsJourney:
    """Everything the screen needs, in one response."""

    months: list[SavingsMonth]
    summary: SavingsSummary
    badges: list[Badge]
    observations: list[str]

    @property
    def has_history(self) -> bool:
        return bool(self.months)


class SavingsService:
    def __init__(self, session: Session) -> None:
        self._analytics = AnalyticsRepository(session)

    def journey(
        self,
        user_id: int,
        *,
        months: int = DEFAULT_SAVINGS_MONTHS,
        today: date | None = None,
    ) -> SavingsJourney:
        """The last `months` completed months, or the whole history for 0.

        Months with no transactions at all are left out rather than shown as a
        zero: a month before the account had any activity is not a month that
        saved nothing, and a line through it would invent a data point. Months
        that *do* have activity and happen to net zero are kept, because that
        is a real result.
        """
        if months != ALL_TIME and not 1 <= months <= MAX_SAVINGS_MONTHS:
            raise ValidationFailed(
                f"Months must be between 1 and {MAX_SAVINGS_MONTHS}, or 0 for all time."
            )

        on_day = today or date.today()
        end = _last_day_of_previous_month(on_day)
        if end is None:
            return _empty()

        start = date(end.year - ALL_TIME_YEARS, 1, 1)
        rows = self._analytics.monthly_series(user_id, start, end)

        history = [
            SavingsMonth(
                year=row.year, month=row.month, income=row.income, expense=row.expense
            )
            for row in rows
        ]
        # `monthly_series` orders by year then month, so this is already
        # chronological; sorted again because the ordering is a property this
        # screen depends on rather than one it should assume.
        history.sort(key=lambda month: (month.year, month.month))

        window = history if months == ALL_TIME else history[-months:]
        if not window:
            return _empty()

        # Badges and observations describe the *whole* history, not the window:
        # narrowing the chart to three months must not retract a personal best
        # or reset a streak that really happened.
        return SavingsJourney(
            months=window,
            summary=SavingsSummary(
                latest=history[-1],
                previous=history[-2] if len(history) > 1 else None,
                best=best_month(history),
            ),
            badges=award(history),
            observations=observations(history),
        )


def _empty() -> SavingsJourney:
    return SavingsJourney(
        months=[],
        summary=SavingsSummary(latest=None, previous=None, best=None),
        badges=[],
        observations=[],
    )


def _last_day_of_previous_month(on_day: date) -> date | None:
    """The last day of the month before `on_day`.

    None is impossible in practice — there is always a previous month — but
    the type says so rather than relying on the reader to notice.
    """
    first_of_this = date(on_day.year, on_day.month, 1)
    return first_of_this.fromordinal(first_of_this.toordinal() - 1)
