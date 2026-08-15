"""Badges and sentences for the savings journey: deterministic, and pure.

Same shape as `insight_rules`: functions from a list of months to findings,
with no session, no clock and no query. Everything they need is passed in, so
a rule is tested by building three months and calling it.

**Rate, not amount, wherever a badge could otherwise reward income.** Somebody
earning three times as much saves three times as much without trying, so a
badge keyed on absolute savings would congratulate them for their salary. The
badges that measure *quality* — Strong saver — use the share of income kept.
The badges that measure *progress* — Personal best, Improving, streaks — are
comparisons against the same person's own history, which is fair whatever the
income, and is the whole point of a journey.

Every threshold is named here rather than written into a rule, so it can be
read and argued with in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.money import ZERO, percentage_of

#: Share of income kept that counts as saving strongly. Twenty per cent is the
#: figure most personal-finance guidance settles on, and it is a threshold the
#: user can check against the rate shown beside it.
STRONG_SAVER_RATE = Decimal("20")

#: Consecutive positive months before a streak is worth naming. Two months is
#: a coincidence; three is a habit forming.
STREAK_MONTHS = 3

#: Consecutive positive months that count as consistency rather than a streak.
#: Half a year of never overspending is a different claim from three months.
CONSISTENT_MONTHS = 6

#: A personal best needs something to be best *of*. One month is not a record.
MIN_MONTHS_FOR_BEST = 2


class BadgeCode(StrEnum):
    """A stable identifier per badge, so wording can change without breaking
    anything that keys on it."""

    PERSONAL_BEST = "personal_best"
    IMPROVING = "improving"
    STREAK = "savings_streak"
    STRONG_SAVER = "strong_saver"
    CONSISTENT = "consistent_saver"


@dataclass(frozen=True)
class SavingsMonth:
    """One completed month's own performance.

    `net` and `rate` are computed here from income and expense rather than
    passed in, so there is exactly one place that turns a month into savings.
    """

    year: int
    month: int
    income: Decimal
    expense: Decimal

    @property
    def net(self) -> Decimal:
        """Income less expense. Negative is a deficit, and stays negative."""
        return self.income - self.expense

    @property
    def rate(self) -> Decimal:
        """Share of income kept, or zero when nothing came in.

        A month with no income has no meaningful rate — dividing by it would
        raise, and inventing 0% or 100% would both be claims about a month
        that earned nothing. `percentage_of` already decides this once
        (ADR-003), so this does not decide it again.
        """
        return percentage_of(self.net, self.income)

    @property
    def is_positive(self) -> bool:
        return self.net > ZERO


@dataclass(frozen=True)
class Badge:
    """One award, and the figure that earned it."""

    code: BadgeCode
    title: str
    #: Always names the number it was awarded for. A badge that cannot say why
    #: it appeared is decoration.
    detail: str


def positive_streak(months: list[SavingsMonth]) -> int:
    """How many of the most recent months in a row were positive.

    Counted backwards from the latest month, so a good run three years ago
    does not earn a badge today.
    """
    streak = 0
    for month in reversed(months):
        if not month.is_positive:
            break
        streak += 1
    return streak


def best_month(months: list[SavingsMonth]) -> SavingsMonth | None:
    """The month with the highest net savings, or None when there are none.

    Ties go to the earlier month: the record was set when it was first
    reached, not when it was matched.
    """
    positive = [month for month in months if month.is_positive]
    if not positive:
        return None
    return max(positive, key=lambda month: (month.net, -month.year, -month.month))


def award(months: list[SavingsMonth]) -> list[Badge]:
    """Every badge the history earns, most significant first.

    Ordered deliberately: a personal best is the rarest thing here and a
    streak is the most durable, so they lead. `months` must be in
    chronological order and contain only completed months.
    """
    if not months:
        return []

    latest = months[-1]
    previous = months[-2] if len(months) > 1 else None
    badges: list[Badge] = []

    best = best_month(months)
    if best is not None and len(months) >= MIN_MONTHS_FOR_BEST and best is latest:
        badges.append(
            Badge(
                code=BadgeCode.PERSONAL_BEST,
                title="Personal best",
                detail=f"{_money(latest.net)} saved — your highest month yet.",
            )
        )

    streak = positive_streak(months)
    if streak >= CONSISTENT_MONTHS:
        badges.append(
            Badge(
                code=BadgeCode.CONSISTENT,
                title="Consistent saver",
                detail=f"{streak} months in a row without overspending.",
            )
        )
    elif streak >= STREAK_MONTHS:
        badges.append(
            Badge(
                code=BadgeCode.STREAK,
                title=f"{streak}-month streak",
                detail=f"Positive savings {streak} months running.",
            )
        )

    if latest.rate >= STRONG_SAVER_RATE and latest.is_positive:
        badges.append(
            Badge(
                code=BadgeCode.STRONG_SAVER,
                title="Strong saver",
                detail=(
                    f"You kept {_percent(latest.rate)}% of what you earned — "
                    f"{STRONG_SAVER_RATE:.0f}% or more earns this."
                ),
            )
        )

    if previous is not None and latest.net > previous.net:
        badges.append(
            Badge(
                code=BadgeCode.IMPROVING,
                title="Improving",
                detail=f"{_money(latest.net - previous.net)} more than last month.",
            )
        )

    return badges


def observations(months: list[SavingsMonth]) -> list[str]:
    """Plain sentences about the history, each naming its own figures.

    Deliberately not a second insights engine: these describe the months on
    this screen, and are returned alongside them rather than mixed into the
    Insights section, which is about the current period.
    """
    if not months:
        return []

    latest = months[-1]
    lines: list[str] = []

    best = best_month(months)
    if best is not None and len(months) >= MIN_MONTHS_FOR_BEST:
        lines.append(
            f"{_month_name(best)} was your best savings month — you saved {_money(best.net)}."
        )

    if len(months) > 1:
        previous = months[-2]
        difference = latest.net - previous.net
        if difference > ZERO:
            lines.append(f"You saved {_money(difference)} more than last month.")
        elif difference < ZERO:
            lines.append(f"You saved {_money(-difference)} less than last month.")

        if latest.income > ZERO and previous.income > ZERO and latest.rate != previous.rate:
            moved = "improved" if latest.rate > previous.rate else "fell"
            lines.append(
                f"Your savings rate {moved} from {_percent(previous.rate)}% "
                f"to {_percent(latest.rate)}%."
            )

    streak = positive_streak(months)
    if streak >= 2:
        lines.append(f"You maintained positive savings for {streak} consecutive months.")

    if not latest.is_positive:
        lines.append(
            f"{_month_name(latest)} spent {_money(-latest.net)} more than it earned."
        )

    return lines


# ─── Formatting ───────────────────────────────────────────────────────────


def _money(value: Decimal) -> str:
    """No currency code: the screen around these sentences already carries it."""
    return f"{value:,.2f}"


def _percent(value: Decimal) -> str:
    """Whole numbers, rounded half up like every other percentage shown."""
    from app.core.money import percent_text

    return percent_text(value)


def _month_name(month: SavingsMonth) -> str:
    from datetime import date

    return f"{date(month.year, month.month, 1):%B %Y}"
