"""Tests for the insight rules.

Pure unit tests — no database, no HTTP, no clock. That is the payoff of making
rules functions over a snapshot: each one is exercised by building a few fields
and calling it, so every threshold and every boundary is cheap to pin down.

What these check, beyond "does it fire":

  * the **explanation names the figures**, because an insight that cannot say
    why it fired is the thing this design exists to prevent;
  * rules **stay quiet** when they should — a screen that cries wolf is worse
    than an empty one;
  * ordering is **fully determined**, so the list does not reshuffle between
    two refreshes of the same data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.insight_rules import (
    BUDGET_WARNING_AT,
    MATERIAL_AMOUNT,
    RENEWAL_SOON_DAYS,
    BudgetFact,
    CategoryFact,
    Insight,
    InsightSnapshot,
    Severity,
    SubscriptionFact,
    budget_ahead_of_pace,
    budget_exceeded,
    budget_nearly_spent,
    category_fell,
    category_rose,
    evaluate,
    nothing_recorded,
    renewal_due_soon,
    spent_more_than_earned,
    subscription_overdue,
    subscriptions_are_heavy,
)

TODAY = date(2026, 3, 15)


def snapshot(**overrides) -> InsightSnapshot:
    """A snapshot with nothing interesting in it, for a rule to be given."""
    defaults = {
        "today": TODAY,
        "period_start": date(2026, 3, 1),
        "period_end": date(2026, 3, 31),
        "income": Decimal("50000.00"),
        "expense": Decimal("20000.00"),
        "transaction_count": 12,
    }
    return InsightSnapshot(**{**defaults, **overrides})


def budget(
    spent: str,
    amount: str = "10000.00",
    *,
    days_remaining: int | None = 16,
    days_total: int = 31,
    name: str = "Food",
) -> BudgetFact:
    limit, used = Decimal(amount), Decimal(spent)
    return BudgetFact(
        category_id=1,
        category_name=name,
        amount=limit,
        spent=used,
        remaining=limit - used,
        percentage_used=(used / limit * 100).quantize(Decimal("0.01")),
        days_remaining=days_remaining,
        days_total=days_total,
    )


def subscription(days: int, name: str = "Netflix", amount: str = "499.00") -> SubscriptionFact:
    return SubscriptionFact(
        subscription_id=1,
        name=name,
        amount=Decimal(amount),
        monthly_cost=Decimal(amount),
        days_until_renewal=days,
        is_active=True,
    )


def category(current: str, previous: str, name: str = "Food") -> CategoryFact:
    return CategoryFact(
        category_id=1, name=name, current=Decimal(current), previous=Decimal(previous)
    )


def only(rule, data: InsightSnapshot) -> list[Insight]:
    return list(rule(data))


# ─── Budgets: exceeded ────────────────────────────────────────────────────


def test_an_exceeded_budget_is_critical() -> None:
    found = only(budget_exceeded, snapshot(budgets=(budget("12000.00", "10000.00"),)))

    assert len(found) == 1
    assert found[0].severity is Severity.CRITICAL


def test_an_exceeded_budget_names_every_figure() -> None:
    """The explanation is the feature. It has to survive being read aloud."""
    found = only(budget_exceeded, snapshot(budgets=(budget("12000.00", "10000.00"),)))

    detail = found[0].detail
    assert "12,000.00" in detail  # spent
    assert "10,000.00" in detail  # the budget
    assert "2,000.00" in detail  # how far over
    assert "16 days" in detail  # how long is left to act


def test_a_budget_within_its_limit_is_not_exceeded() -> None:
    assert only(budget_exceeded, snapshot(budgets=(budget("5000.00"),))) == []


def test_a_budget_spent_exactly_to_the_limit_is_not_exceeded() -> None:
    """Nothing left is not the same as over, and the wording would be wrong."""
    assert only(budget_exceeded, snapshot(budgets=(budget("10000.00"),))) == []


def test_a_finished_budget_cannot_be_exceeded_now() -> None:
    """It would be a permanent complaint no action could clear."""
    over_but_ended = budget("12000.00", days_remaining=None)

    assert only(budget_exceeded, snapshot(budgets=(over_but_ended,))) == []


# ─── Budgets: nearly spent ────────────────────────────────────────────────


def test_a_budget_at_the_warning_threshold_fires() -> None:
    found = only(budget_nearly_spent, snapshot(budgets=(budget("8000.00", "10000.00"),)))

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert "80%" in found[0].detail


def test_a_budget_just_below_the_threshold_stays_quiet() -> None:
    assert only(budget_nearly_spent, snapshot(budgets=(budget("7900.00", "10000.00"),))) == []


def test_an_exceeded_budget_does_not_also_say_nearly_spent() -> None:
    """Two insights about one budget is nagging; the louder one wins."""
    over = snapshot(budgets=(budget("12000.00", "10000.00"),))

    assert only(budget_nearly_spent, over) == []


def test_the_threshold_matches_the_budget_screen() -> None:
    """Two answers to "is this budget in trouble" would be worse than one."""
    from app.services.budget_utilisation import WARNING_AT

    assert BUDGET_WARNING_AT == WARNING_AT


# ─── Budgets: ahead of pace ───────────────────────────────────────────────


def test_spending_far_ahead_of_the_calendar_is_flagged() -> None:
    """The rule that earns its place: 60% spent on day 10 of 30 trips nothing
    else, but it is on course to run out with a third of the month left."""
    ahead = budget("6000.00", "10000.00", days_remaining=20, days_total=30)

    found = only(budget_ahead_of_pace, snapshot(budgets=(ahead,)))

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert "60%" in found[0].detail
    assert "33%" in found[0].detail  # the period elapsed


def test_spending_in_step_with_the_calendar_is_not_flagged() -> None:
    even = budget("5000.00", "10000.00", days_remaining=15, days_total=30)

    assert only(budget_ahead_of_pace, snapshot(budgets=(even,))) == []


def test_a_modest_lead_is_tolerated() -> None:
    """Nobody spends evenly. A rule that fires on the weekly shop is noise."""
    slightly_ahead = budget("6000.00", "10000.00", days_remaining=15, days_total=30)

    assert only(budget_ahead_of_pace, snapshot(budgets=(slightly_ahead,))) == []


def test_pace_stays_quiet_once_the_budget_is_nearly_gone() -> None:
    """That case has its own, louder insight."""
    nearly = budget("8500.00", "10000.00", days_remaining=25, days_total=30)

    assert only(budget_ahead_of_pace, snapshot(budgets=(nearly,))) == []


def test_pace_stays_quiet_on_a_budget_that_is_not_running() -> None:
    assert (
        only(budget_ahead_of_pace, snapshot(budgets=(budget("6000.00", days_remaining=None),)))
        == []
    )


# ─── Spending against income ──────────────────────────────────────────────


def test_spending_more_than_earning_is_critical() -> None:
    found = only(
        spent_more_than_earned,
        snapshot(income=Decimal("10000.00"), expense=Decimal("13500.00")),
    )

    assert len(found) == 1
    assert found[0].severity is Severity.CRITICAL
    assert "3,500.00" in found[0].detail


def test_breaking_even_is_not_a_shortfall() -> None:
    even = snapshot(income=Decimal("10000.00"), expense=Decimal("10000.00"))

    assert only(spent_more_than_earned, even) == []


def test_an_empty_period_is_not_a_shortfall() -> None:
    """Zero in and zero out is no transactions, not a deficit."""
    empty = snapshot(income=Decimal("0.00"), expense=Decimal("0.00"), transaction_count=0)

    assert only(spent_more_than_earned, empty) == []


# ─── Subscriptions ────────────────────────────────────────────────────────


def test_an_overdue_subscription_is_flagged_with_both_explanations() -> None:
    """The app cannot tell which of the two happened, so it says both."""
    found = only(subscription_overdue, snapshot(subscriptions=(subscription(-3),)))

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert "3 days ago" in found[0].detail
    assert "marking as renewed" in found[0].detail
    assert "ended" in found[0].detail


def test_a_renewal_due_soon_is_informational() -> None:
    found = only(renewal_due_soon, snapshot(subscriptions=(subscription(3),)))

    assert len(found) == 1
    assert found[0].severity is Severity.INFO
    assert "3 days" in found[0].title
    assert "499.00" in found[0].detail


def test_a_renewal_today_says_today() -> None:
    found = only(renewal_due_soon, snapshot(subscriptions=(subscription(0),)))

    assert "today" in found[0].title


def test_a_renewal_beyond_the_window_stays_quiet() -> None:
    beyond = subscription(RENEWAL_SOON_DAYS + 1)

    assert only(renewal_due_soon, snapshot(subscriptions=(beyond,))) == []


def test_an_overdue_subscription_is_not_also_due_soon() -> None:
    assert only(renewal_due_soon, snapshot(subscriptions=(subscription(-2),))) == []


def test_soonest_renewal_ranks_first() -> None:
    data = snapshot(subscriptions=(subscription(6, "Later"), subscription(1, "Sooner")))

    ordered = evaluate(data, rules=[renewal_due_soon]).insights

    assert [insight.title.split()[0] for insight in ordered] == ["Sooner", "Later"]


def test_heavy_subscriptions_are_named_with_their_share() -> None:
    data = snapshot(expense=Decimal("10000.00"), subscription_monthly_total=Decimal("2500.00"))

    found = only(subscriptions_are_heavy, data)

    assert len(found) == 1
    assert "25%" in found[0].detail
    assert "2,500.00" in found[0].detail


def test_a_small_subscription_share_stays_quiet() -> None:
    data = snapshot(expense=Decimal("10000.00"), subscription_monthly_total=Decimal("500.00"))

    assert only(subscriptions_are_heavy, data) == []


def test_no_spending_means_no_share_to_report() -> None:
    """Dividing by nothing would be the only way to get a figure here."""
    data = snapshot(expense=Decimal("0.00"), subscription_monthly_total=Decimal("500.00"))

    assert only(subscriptions_are_heavy, data) == []


# ─── Category movement ────────────────────────────────────────────────────


def test_a_large_rise_is_a_warning() -> None:
    found = only(category_rose, snapshot(categories=(category("3000.00", "1000.00"),)))

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert "200%" in found[0].detail
    assert "2,000.00" in found[0].detail


def test_a_large_percentage_on_a_trivial_amount_stays_quiet() -> None:
    """300% of a rounding error is not news."""
    trivial = category("40.00", "10.00")

    assert only(category_rose, snapshot(categories=(trivial,))) == []


def test_a_large_amount_at_a_small_percentage_stays_quiet() -> None:
    """A big absolute move on a big category may be perfectly ordinary."""
    ordinary = category("22000.00", "20000.00")

    assert only(category_rose, snapshot(categories=(ordinary,))) == []


def test_a_category_with_no_previous_spend_is_not_a_rise() -> None:
    """From nothing is a start, and there is no percentage to report."""
    fresh = category("5000.00", "0.00")

    assert only(category_rose, snapshot(categories=(fresh,))) == []


def test_a_large_fall_is_good_news() -> None:
    """An application that only reports problems teaches people to dread it."""
    found = only(category_fell, snapshot(categories=(category("1000.00", "3000.00"),)))

    assert len(found) == 1
    assert found[0].severity is Severity.GOOD
    assert "2,000.00" in found[0].detail


def test_a_small_fall_stays_quiet() -> None:
    assert only(category_fell, snapshot(categories=(category("9800.00", "10000.00"),))) == []


def test_a_fall_below_the_material_amount_stays_quiet() -> None:
    below = category("100.00", "300.00")
    assert Decimal("200.00") < MATERIAL_AMOUNT

    assert only(category_fell, snapshot(categories=(below,))) == []


# ─── Nothing recorded ─────────────────────────────────────────────────────


def test_an_empty_period_says_so() -> None:
    """An empty screen is indistinguishable from something being broken."""
    found = only(nothing_recorded, snapshot(transaction_count=0))

    assert len(found) == 1
    assert "01 Mar" in found[0].detail
    assert "31 Mar" in found[0].detail


def test_a_period_with_activity_does_not() -> None:
    assert only(nothing_recorded, snapshot(transaction_count=1)) == []


# ─── The engine ───────────────────────────────────────────────────────────


def test_nothing_wrong_produces_nothing() -> None:
    """Quiet is a valid answer, and better than a manufactured one."""
    report = evaluate(snapshot())

    assert report.insights == []
    assert report.needs_attention == 0


def test_insights_are_ordered_by_severity() -> None:
    data = snapshot(
        income=Decimal("1000.00"),
        expense=Decimal("5000.00"),  # critical: shortfall
        budgets=(budget("8000.00", "10000.00"),),  # warning: nearly spent
        subscriptions=(subscription(2),),  # info: renews soon
        categories=(category("1000.00", "3000.00"),),  # good: fell
    )

    severities = [insight.severity for insight in evaluate(data).insights]

    assert severities == [
        Severity.CRITICAL,
        Severity.WARNING,
        Severity.INFO,
        Severity.GOOD,
    ]


def test_the_biggest_problem_comes_first_within_a_severity() -> None:
    data = snapshot(
        budgets=(
            budget("11000.00", "10000.00", name="Small overspend"),
            budget("20000.00", "10000.00", name="Big overspend"),
        )
    )

    titles = [insight.title for insight in evaluate(data).insights]

    assert titles[0].startswith("Big overspend")


def test_the_order_is_the_same_every_time() -> None:
    """A list that reshuffles between two refreshes reads as broken."""
    data = snapshot(
        budgets=(budget("9000.00", "10000.00", name="A"), budget("9000.00", "10000.00", name="B")),
        subscriptions=(subscription(3, "X"), subscription(3, "Y")),
    )

    first = [insight.title for insight in evaluate(data).insights]
    second = [insight.title for insight in evaluate(data).insights]

    assert first == second


def test_counts_are_reported_per_severity() -> None:
    data = snapshot(
        income=Decimal("1000.00"),
        expense=Decimal("5000.00"),
        budgets=(budget("12000.00", "10000.00"),),
    )

    counts = evaluate(data).counts

    assert counts[Severity.CRITICAL] == 2
    assert counts[Severity.GOOD] == 0


def test_needs_attention_counts_only_the_bad_news() -> None:
    data = snapshot(
        budgets=(budget("8000.00", "10000.00"),),  # warning
        categories=(category("1000.00", "3000.00"),),  # good
        subscriptions=(subscription(2),),  # info
    )

    assert evaluate(data).needs_attention == 1


def test_every_insight_carries_an_explanation() -> None:
    """The one property that must hold for every rule, present and future."""
    data = snapshot(
        income=Decimal("1000.00"),
        expense=Decimal("9000.00"),
        budgets=(budget("12000.00", "10000.00"), budget("8500.00", "10000.00", name="Rent")),
        subscriptions=(subscription(-2, "Late"), subscription(1, "Soon")),
        categories=(category("4000.00", "1000.00"), category("500.00", "3000.00", name="Fell")),
        subscription_monthly_total=Decimal("3000.00"),
    )

    report = evaluate(data)

    assert report.insights
    for insight in report.insights:
        assert insight.title.strip(), insight.code
        assert len(insight.detail) > 20, f"{insight.code} does not explain itself"
        assert any(character.isdigit() for character in insight.detail), (
            f"{insight.code} explains nothing without a figure"
        )


@pytest.mark.parametrize("severity", list(Severity))
def test_every_severity_is_orderable(severity: Severity) -> None:
    """A severity with no rank would sort unpredictably."""
    from app.services.insight_rules import SEVERITY_ORDER

    assert severity in SEVERITY_ORDER
