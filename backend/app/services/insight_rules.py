"""The insight rules: deterministic, explainable, and pure.

Every rule is a function from a *snapshot* to zero or more insights. No
database, no HTTP, no clock — the snapshot carries everything, including what
day it is. That is what lets a rule be tested by building three fields and
calling it, and what stops a rule quietly growing a query of its own.

Two constraints shape the whole module.

**Every insight explains itself.** "Unusual spending detected" is not an
insight; it is a shrug with a badge. Each one states the figure it found, what
it compared it against, and — where there is one — what to do. The explanation
is the feature, not decoration on top of it.

**Nothing here is stored** (ADR-015). Insights are recomputed on read, which is
the only way they can be right: an insight cached yesterday describes yesterday.

Rules are deliberately dull. A rule that surprises its author will surprise a
user, and a finance application that cannot say *why* it said something is
worse than one that says nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.core.money import ZERO, percentage_of

# ─── Thresholds ───────────────────────────────────────────────────────────
# Named, gathered, and stated once. A rule with a bare `0.8` in it is a rule
# nobody can tune without reading the code.

#: A budget is worth warning about at this share used. Matches the budget
#: screen's own amber threshold deliberately — two different answers to "is
#: this budget in trouble" would be worse than either answer alone.
BUDGET_WARNING_AT = Decimal("80")

#: Spending is "ahead of pace" when the share of budget used exceeds the share
#: of the period elapsed by this much. A generous margin: nobody spends evenly,
#: and a rule that fires every time someone does their weekly shop is noise.
PACE_MARGIN = Decimal("20")

#: A category has to move by at least this share *and* this amount to be worth
#: mentioning. Both, deliberately: 300% of a rounding error is not news, and a
#: large absolute change on a huge category may be perfectly ordinary.
CATEGORY_RISE_AT = Decimal("50")
CATEGORY_FALL_AT = Decimal("30")
MATERIAL_AMOUNT = Decimal("500")

#: Renewals inside this many days are worth surfacing. Matches the
#: subscriptions screen's own window.
RENEWAL_SOON_DAYS = 7

#: Subscriptions taking more than this share of spending is worth naming.
SUBSCRIPTION_HEAVY_AT = Decimal("15")


class Severity(StrEnum):
    """How much attention an insight deserves.

    A small closed set, ordered below. The interface renders these; it does not
    decide them, and it must not invent a sixth.
    """

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    GOOD = "good"


#: Display order. Bad news first, good news last — someone opening this screen
#: is looking for problems, and burying one under a compliment would be a poor
#: trade.
SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
    Severity.GOOD: 3,
}


@dataclass(frozen=True)
class Insight:
    """One finding, and why."""

    #: A stable identifier for the rule that produced this. Not shown to the
    #: user — it exists so the interface can key on something that will not
    #: change when the wording is improved.
    code: str
    severity: Severity
    title: str
    #: The explanation. Always names the figures involved.
    detail: str
    #: Used only to order insights of equal severity, so the biggest problem
    #: comes first. Never displayed.
    magnitude: Decimal = ZERO
    category_id: int | None = None
    subscription_id: int | None = None


# ─── The snapshot ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetFact:
    """What the rules need to know about one budget."""

    category_id: int
    category_name: str
    amount: Decimal
    spent: Decimal
    remaining: Decimal
    percentage_used: Decimal
    days_remaining: int | None
    days_total: int

    @property
    def is_current(self) -> bool:
        return self.days_remaining is not None

    @property
    def period_elapsed(self) -> Decimal:
        """Share of the budget's period that has passed, as a percentage.

        Zero for a budget that is not running, so a pace rule cannot fire on a
        period nobody is inside.
        """
        if self.days_remaining is None or self.days_total <= 0:
            return ZERO
        elapsed = self.days_total - self.days_remaining
        return percentage_of(Decimal(elapsed), Decimal(self.days_total))


@dataclass(frozen=True)
class SubscriptionFact:
    """What the rules need to know about one subscription."""

    subscription_id: int
    name: str
    amount: Decimal
    monthly_cost: Decimal
    days_until_renewal: int
    is_active: bool


@dataclass(frozen=True)
class CategoryFact:
    """One category's spend, this period against last."""

    category_id: int
    name: str
    current: Decimal
    previous: Decimal

    @property
    def difference(self) -> Decimal:
        return self.current - self.previous

    @property
    def percentage_change(self) -> Decimal | None:
        """None when there was nothing before — a start, not a percentage."""
        if self.previous == ZERO:
            return None
        return percentage_of(self.difference, self.previous)


@dataclass(frozen=True)
class InsightSnapshot:
    """Everything the rules are allowed to see.

    Assembled once by the service. A rule that needs something absent here adds
    a field rather than reaching for a session — the moment one rule queries,
    they all become untestable and the cost of the screen stops being
    predictable.
    """

    today: date
    period_start: date
    period_end: date
    income: Decimal
    expense: Decimal
    transaction_count: int
    budgets: tuple[BudgetFact, ...] = ()
    subscriptions: tuple[SubscriptionFact, ...] = ()
    categories: tuple[CategoryFact, ...] = ()
    subscription_monthly_total: Decimal = ZERO
    previous_expense: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.income - self.expense


# ─── Formatting ───────────────────────────────────────────────────────────


def _money(value: Decimal) -> str:
    """Amounts inside an explanation.

    No currency code: the sentence already sits inside an application that
    knows the user's currency, and repeating it in every clause makes the text
    unreadable.
    """
    return f"{value:,.2f}"


def _days(count: int) -> str:
    return f"{count} day{'s' if count != 1 else ''}"


# ─── Rules ────────────────────────────────────────────────────────────────
# Each takes the snapshot and yields zero or more insights.


def budget_exceeded(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """A budget that has been spent past its limit."""
    for budget in snapshot.budgets:
        if not budget.is_current or budget.remaining >= ZERO:
            continue

        over = -budget.remaining
        left = _days(budget.days_remaining or 0)
        yield Insight(
            code="budget_exceeded",
            severity=Severity.CRITICAL,
            title=f"{budget.category_name} budget exceeded",
            detail=(
                f"You have spent {_money(budget.spent)} against a "
                f"{_money(budget.amount)} budget — {_money(over)} over, with "
                f"{left} of the period left."
            ),
            magnitude=over,
            category_id=budget.category_id,
        )


def budget_nearly_spent(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """A budget close to its limit but not past it."""
    for budget in snapshot.budgets:
        if not budget.is_current or budget.remaining < ZERO:
            continue
        if budget.percentage_used < BUDGET_WARNING_AT:
            continue

        yield Insight(
            code="budget_nearly_spent",
            severity=Severity.WARNING,
            title=f"{budget.category_name} budget almost gone",
            detail=(
                f"{budget.percentage_used:.0f}% used — {_money(budget.remaining)} "
                f"left with {_days(budget.days_remaining or 0)} to go."
            ),
            magnitude=budget.percentage_used,
            category_id=budget.category_id,
        )


def budget_ahead_of_pace(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """Spending faster than the period is passing.

    The rule that earns its place. A budget at 60% on day 10 of 30 is not yet
    "nearly spent" and will not trigger any threshold on its amount — but it is
    on course to run out with a third of the month left, which is worth knowing
    while there is still time to act.

    Suppressed once the budget is already over or nearly gone: those have their
    own, louder insight, and saying both would be nagging.
    """
    for budget in snapshot.budgets:
        if not budget.is_current or budget.remaining < ZERO:
            continue
        if budget.percentage_used >= BUDGET_WARNING_AT:
            continue

        elapsed = budget.period_elapsed
        if budget.percentage_used <= elapsed + PACE_MARGIN:
            continue

        yield Insight(
            code="budget_ahead_of_pace",
            severity=Severity.WARNING,
            title=f"{budget.category_name} spending is ahead of pace",
            detail=(
                f"{budget.percentage_used:.0f}% of the budget is gone but only "
                f"{elapsed:.0f}% of the period has passed. At this rate it runs "
                f"out before {budget.days_remaining} more days are up."
            ),
            magnitude=budget.percentage_used - elapsed,
            category_id=budget.category_id,
        )


def spent_more_than_earned(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """More went out than came in over the period."""
    if snapshot.net >= ZERO or snapshot.transaction_count == 0:
        return

    shortfall = -snapshot.net
    yield Insight(
        code="spent_more_than_earned",
        severity=Severity.CRITICAL,
        title="You spent more than you earned",
        detail=(
            f"{_money(snapshot.expense)} out against {_money(snapshot.income)} "
            f"in — a shortfall of {_money(shortfall)} this period."
        ),
        magnitude=shortfall,
    )


def subscription_overdue(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """An active subscription whose renewal date has passed.

    Means one of two things, and the explanation says so: either a charge went
    through unnoticed, or the record is stale. Both are worth a nudge, and the
    application cannot tell which.
    """
    for subscription in snapshot.subscriptions:
        if not subscription.is_active or subscription.days_until_renewal >= 0:
            continue

        late = -subscription.days_until_renewal
        yield Insight(
            code="subscription_overdue",
            severity=Severity.WARNING,
            title=f"{subscription.name} renewal has passed",
            detail=(
                f"It was due {_days(late)} ago. Either the charge went through "
                f"and needs marking as renewed, or the subscription has ended."
            ),
            magnitude=Decimal(late),
            subscription_id=subscription.subscription_id,
        )


def renewal_due_soon(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """A subscription charging within the week."""
    for subscription in snapshot.subscriptions:
        if not subscription.is_active:
            continue
        if not 0 <= subscription.days_until_renewal <= RENEWAL_SOON_DAYS:
            continue

        when = (
            "today"
            if subscription.days_until_renewal == 0
            else f"in {_days(subscription.days_until_renewal)}"
        )
        yield Insight(
            code="renewal_due_soon",
            severity=Severity.INFO,
            title=f"{subscription.name} renews {when}",
            detail=f"{_money(subscription.amount)} is due {when}.",
            # Soonest first within the group, so a negated day count.
            magnitude=Decimal(RENEWAL_SOON_DAYS - subscription.days_until_renewal),
            subscription_id=subscription.subscription_id,
        )


def subscriptions_are_heavy(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """Recurring payments taking a large share of spending.

    The finding this application exists to surface: money leaving on a
    standing order is money nobody notices leaving.
    """
    if snapshot.expense <= ZERO or snapshot.subscription_monthly_total <= ZERO:
        return

    share = percentage_of(snapshot.subscription_monthly_total, snapshot.expense)
    if share < SUBSCRIPTION_HEAVY_AT:
        return

    yield Insight(
        code="subscriptions_are_heavy",
        severity=Severity.INFO,
        title="Subscriptions are a large share of your spending",
        detail=(
            f"{_money(snapshot.subscription_monthly_total)} a month in "
            f"subscriptions — {share:.0f}% of the {_money(snapshot.expense)} you "
            f"spent this period."
        ),
        magnitude=share,
    )


def category_rose(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """A category that grew materially against the previous period."""
    for category in snapshot.categories:
        change = category.percentage_change
        if change is None or change < CATEGORY_RISE_AT:
            continue
        if category.difference < MATERIAL_AMOUNT:
            continue

        yield Insight(
            code="category_rose",
            severity=Severity.WARNING,
            title=f"{category.name} spending is up",
            detail=(
                f"{_money(category.current)} this period against "
                f"{_money(category.previous)} last — up {change:.0f}%, "
                f"{_money(category.difference)} more."
            ),
            magnitude=category.difference,
            category_id=category.category_id,
        )


def category_fell(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """A category that dropped materially. Good news, and worth saying.

    An application that only ever reports problems trains people to dread
    opening it.
    """
    for category in snapshot.categories:
        change = category.percentage_change
        if change is None or change > -CATEGORY_FALL_AT:
            continue
        saved = -category.difference
        if saved < MATERIAL_AMOUNT:
            continue

        yield Insight(
            code="category_fell",
            severity=Severity.GOOD,
            title=f"{category.name} spending is down",
            detail=(
                f"{_money(category.current)} this period against "
                f"{_money(category.previous)} last — {_money(saved)} less."
            ),
            magnitude=saved,
            category_id=category.category_id,
        )


def nothing_recorded(snapshot: InsightSnapshot) -> Iterable[Insight]:
    """No transactions in the period.

    Says so plainly rather than showing an empty screen, which is
    indistinguishable from something being broken.
    """
    if snapshot.transaction_count > 0:
        return

    yield Insight(
        code="nothing_recorded",
        severity=Severity.INFO,
        title="Nothing recorded this period",
        detail=(
            "There are no transactions between "
            f"{snapshot.period_start:%d %b} and {snapshot.period_end:%d %b}. "
            "Insights need something to work from."
        ),
    )


#: Every rule, in no significant order — the output is sorted by severity, not
#: by the order rules happen to run. Adding a rule is appending to this list.
RULES: list[Callable[[InsightSnapshot], Iterable[Insight]]] = [
    spent_more_than_earned,
    budget_exceeded,
    budget_nearly_spent,
    budget_ahead_of_pace,
    subscription_overdue,
    category_rose,
    renewal_due_soon,
    subscriptions_are_heavy,
    category_fell,
    nothing_recorded,
]


@dataclass(frozen=True)
class InsightReport:
    """Everything the rules found, ordered."""

    insights: list[Insight] = field(default_factory=list)

    @property
    def counts(self) -> dict[Severity, int]:
        return {
            severity: sum(1 for insight in self.insights if insight.severity is severity)
            for severity in Severity
        }

    @property
    def needs_attention(self) -> int:
        counts = self.counts
        return counts[Severity.CRITICAL] + counts[Severity.WARNING]


def evaluate(snapshot: InsightSnapshot, rules: list | None = None) -> InsightReport:
    """Run every rule and order the results.

    Sorted by severity, then by magnitude within a severity, so the largest
    problem of the most urgent kind comes first. `code` breaks any remaining
    tie, so the same snapshot always produces the same order — an insight list
    that reshuffles between refreshes reads as broken.
    """
    found: list[Insight] = []
    for rule in rules if rules is not None else RULES:
        found.extend(rule(snapshot))

    found.sort(
        key=lambda insight: (SEVERITY_ORDER[insight.severity], -insight.magnitude, insight.code)
    )
    return InsightReport(insights=found)
