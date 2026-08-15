"""Tests for the demonstration history.

The important one runs the **real detector** over the generated data and asserts
it finds exactly the three subscriptions and not the gym. Without that, "a year
of plausible history" is a claim about a file nobody has checked — and the demo
would be rehearsed against data that might not actually demonstrate the feature
it exists to demonstrate.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from app.models.enums import TransactionType
from app.services.recurrence import MAX_OFF_CYCLE, Charge, detect
from tools.demo_data import (
    DEFAULT_DAYS,
    GYM,
    OPAQUE_MERCHANT,
    DemoHistory,
    build_history,
)

TODAY = date(2026, 8, 15)


def history(**kwargs: object) -> DemoHistory:
    return build_history(today=TODAY, **kwargs)  # type: ignore[arg-type]


def charges(data: DemoHistory) -> list[Charge]:
    """The expense rows, as the detector sees them."""
    return [
        Charge(
            transaction_id=index,
            date=row.date,
            amount=row.amount,
            description=row.description,
            category_id=1,
        )
        for index, row in enumerate(data.transactions)
        if row.transaction_type is TransactionType.EXPENSE
    ]


# ─── It demonstrates the thing it exists to demonstrate ───────────────────


def test_detection_finds_the_three_subscriptions() -> None:
    """The demo's whole point. If this fails, the demonstration does not work
    and no amount of rehearsal will fix it."""
    found = {candidate.name for candidate in detect(charges(history()))}

    assert {"Netflix", "Spotify Ab", "Adobe Systems"} <= found


def test_detection_does_not_propose_the_gym() -> None:
    """A demo where everything is detected proves the threshold is low, not
    that the detector works. The gym is paid at 18, 44, 25 and 51 day gaps."""
    found = {candidate.name for candidate in detect(charges(history()))}

    assert "Fitness First Gulshan" not in found


def test_ordinary_habits_are_not_proposed_as_subscriptions() -> None:
    """A year of groceries, taxis and cinema tickets contains runs that are
    superficially regular. Every one of these was proposed at some point —
    "82±70 days apart", "112±77", "98±69" — carrying evidence that refuted
    itself. This is the test that keeps them out."""
    found = {candidate.name for candidate in detect(charges(history()))}

    assert found.isdisjoint(
        {"Cng Fare", "Pharmacy", "Star Cineplex", "Shwapno Supershop", "Uber", "Campus Canteen"}
    ), found


def test_nothing_proposed_carries_evidence_that_refutes_itself() -> None:
    """The property the spread ceiling exists to guarantee, checked against a
    year of realistic history rather than against contrived dates: a candidate
    whose spread approaches its own interval is not describing a rhythm."""
    for candidate in detect(charges(history())):
        assert candidate.interval_spread_days <= (
            candidate.median_interval_days * MAX_OFF_CYCLE
        ), candidate.evidence


def test_the_price_rise_is_still_one_subscription() -> None:
    """Spotify goes from 199 to 249 partway through, and detection has to see
    one subscription rather than two — which is worth showing on the day."""
    candidates = [c for c in detect(charges(history())) if c.name == "Spotify Ab"]

    assert len(candidates) == 1
    assert candidates[0].occurrences >= 10


def test_a_charge_with_no_merchant_is_in_the_history_and_is_skipped() -> None:
    """ADR-007's limitation, shown rather than hidden. A demo that quietly
    leaves these out demonstrates a limitation that does not exist."""
    data = history()

    assert any(row.description == OPAQUE_MERCHANT for row in data.transactions)
    assert not any(candidate.name.startswith("Pos") for candidate in detect(charges(data)))


def test_something_is_left_for_detection_to_find() -> None:
    """Only Netflix is tracked up front. Tracking all three would leave the
    feature with nothing to say on the day."""
    data = history()

    assert [item.name for item in data.subscriptions] == ["Netflix"]


# ─── It is history somebody could have ────────────────────────────────────


def test_it_covers_a_year_ending_today() -> None:
    data = history()
    days = [row.date for row in data.transactions]

    assert max(days) <= TODAY
    assert min(days) >= TODAY - timedelta(days=DEFAULT_DAYS + 1)
    assert (max(days) - min(days)).days > 300


def test_there_is_income_as_well_as_spending() -> None:
    """A year of pure expense would show a hero figure of minus everything."""
    kinds = Counter(row.transaction_type for row in history().transactions)

    assert kinds[TransactionType.INCOME] >= 12
    assert kinds[TransactionType.EXPENSE] > kinds[TransactionType.INCOME]


def test_income_is_not_the_same_figure_every_month() -> None:
    """Otherwise the trend chart is a flat line and the comparison table is
    empty, and both are things the demo is meant to show."""
    incomes = {
        row.amount
        for row in history().transactions
        if row.transaction_type is TransactionType.INCOME
    }

    assert len(incomes) > 1


def test_every_amount_is_a_decimal() -> None:
    """A float here would reach the API as a float and lose the point of
    ADR-003 in the one dataset anybody actually looks at."""
    assert all(isinstance(row.amount, Decimal) for row in history().transactions)


def test_amounts_are_all_positive() -> None:
    """Direction is carried by the type, never by the sign."""
    assert all(row.amount > 0 for row in history().transactions)


def test_it_uses_only_categories_a_new_account_has() -> None:
    """Seeding would otherwise fail partway through on a fresh account."""
    from app.core.default_categories import DEFAULT_CATEGORIES

    seeded = {category.name for category in DEFAULT_CATEGORIES}

    assert set(history().categories) <= seeded


def test_the_budgets_are_for_expense_categories_only() -> None:
    """ADR-023. A budget on Salary would be refused by the server."""
    from app.core.default_categories import DEFAULT_CATEGORIES

    expenses = {c.name for c in DEFAULT_CATEGORIES if c.category_type == "expense"}

    assert {budget.category for budget in history().budgets} <= expenses


def test_the_budgets_land_in_three_different_states() -> None:
    """A screen where every bar is green demonstrates a progress bar, not a
    budget. Sized from month-to-date spending rather than as fixed amounts,
    which only land interestingly on the day they were chosen for."""
    from app.services.budget_utilisation import BudgetStatus, status_for

    data = history()
    spent_by_category: dict[str, Decimal] = {}
    first = TODAY.replace(day=1)
    for row in data.transactions:
        if row.transaction_type is TransactionType.EXPENSE and first <= row.date <= TODAY:
            spent_by_category[row.category] = (
                spent_by_category.get(row.category, Decimal(0)) + row.amount
            )

    states = {
        budget.category: status_for(
            (spent_by_category.get(budget.category, Decimal(0)) / budget.amount * 100).quantize(
                Decimal("0.01")
            )
        )
        for budget in data.budgets
    }

    assert set(states.values()) == {
        BudgetStatus.HEALTHY,
        BudgetStatus.WARNING,
        BudgetStatus.EXCEEDED,
    }, states


def test_the_budget_amounts_are_round_numbers() -> None:
    """A budget of 6,275.56 reads as a figure the application computed rather
    than one a person chose."""
    assert all(budget.amount % 100 == 0 for budget in history().budgets)


def test_the_budgets_cover_the_current_month() -> None:
    for budget in history().budgets:
        assert budget.period_start <= TODAY <= budget.period_end


def test_the_budgets_do_not_overlap_each_other() -> None:
    """ADR-023 refuses two budgets covering one category at once."""
    categories = [budget.category for budget in history().budgets]

    assert len(categories) == len(set(categories))


# ─── It can be rehearsed ──────────────────────────────────────────────────


def test_the_same_seed_gives_the_same_history() -> None:
    """A demo that generates different figures each run cannot be rehearsed,
    and screenshots taken from it disagree with each other."""
    assert history() == history()


def test_a_different_seed_gives_a_different_history() -> None:
    assert history(seed=1) != history(seed=2)


def test_a_shorter_window_produces_less() -> None:
    assert len(history(days=90).transactions) < len(history(days=365).transactions)


def test_the_rows_come_out_in_order() -> None:
    """So a caller writing them one at a time builds history forwards."""
    days = [row.date for row in history().transactions]

    assert days == sorted(days)


def test_the_history_is_big_enough_to_look_real_and_small_enough_to_seed() -> None:
    """Seeding is one API call per row, so this is also how long a demo setup
    takes to run."""
    count = len(history().transactions)

    assert 300 <= count <= 900, f"{count} rows"


def test_the_gym_is_present_even_though_it_is_not_a_subscription() -> None:
    assert any(row.description == GYM.merchant for row in history().transactions)
