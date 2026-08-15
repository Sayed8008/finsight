"""Tests for billing cycle arithmetic.

Month-end is the whole point of this file. Adding a month to 31 January must
give the end of February, and — the part that is easy to miss — doing it twice
must still land on the 31st in March rather than drifting to the 28th forever.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.enums import BillingCycle
from app.services.billing_cycle import (
    add_months,
    days_until,
    monthly_equivalent,
    next_billing_after,
    occurrence,
    yearly_equivalent,
)

WEEKLY = BillingCycle.WEEKLY
MONTHLY = BillingCycle.MONTHLY
QUARTERLY = BillingCycle.QUARTERLY
YEARLY = BillingCycle.YEARLY


# ─── add_months: the month-end trap ───────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        # The ordinary case.
        ("2026-03-15", 1, "2026-04-15"),
        # 31 February does not exist, so clamp to the end of the month.
        ("2026-01-31", 1, "2026-02-28"),
        ("2028-01-31", 1, "2028-02-29"),  # leap year
        ("2026-01-30", 1, "2026-02-28"),
        ("2026-01-29", 1, "2026-02-28"),
        # 31 to a 30-day month.
        ("2026-03-31", 1, "2026-04-30"),
        ("2026-05-31", 1, "2026-06-30"),
        # Crossing a year boundary.
        ("2026-12-15", 1, "2027-01-15"),
        ("2026-12-31", 2, "2027-02-28"),
        # Quarters and years.
        ("2026-01-31", 3, "2026-04-30"),
        ("2028-02-29", 12, "2029-02-28"),  # leap day, one year on
        ("2026-11-30", 12, "2027-11-30"),
    ],
)
def test_add_months_clamps_to_the_last_valid_day(start: str, months: int, expected: str) -> None:
    assert add_months(date.fromisoformat(start), months) == date.fromisoformat(expected)


def test_add_months_of_zero_changes_nothing() -> None:
    assert add_months(date(2026, 1, 31), 0) == date(2026, 1, 31)


# ─── Drift: the reason occurrences come from the anchor ───────────────────


def test_a_month_end_subscription_does_not_drift() -> None:
    """The bug this design exists to prevent.

    Stepping from each previous date would give 31 Jan, 28 Feb, 28 Mar, 28 Apr
    — the subscription silently leaves the 31st after one short month. Counting
    from the anchor keeps it on the last day, as a real biller does.
    """
    anchor = date(2026, 1, 31)

    dates = [occurrence(anchor, MONTHLY, n) for n in range(5)]

    assert dates == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
    ]


def test_a_leap_day_subscription_returns_to_the_29th() -> None:
    anchor = date(2028, 2, 29)

    assert occurrence(anchor, YEARLY, 1) == date(2029, 2, 28)
    assert occurrence(anchor, YEARLY, 4) == date(2032, 2, 29)


def test_weekly_occurrences_are_exact_multiples_of_seven_days() -> None:
    anchor = date(2026, 3, 2)

    assert occurrence(anchor, WEEKLY, 3) == date(2026, 3, 23)


def test_quarterly_and_yearly_occurrences() -> None:
    anchor = date(2026, 1, 15)

    assert occurrence(anchor, QUARTERLY, 2) == date(2026, 7, 15)
    assert occurrence(anchor, YEARLY, 2) == date(2028, 1, 15)


# ─── next_billing_after ───────────────────────────────────────────────────


def test_the_next_date_is_strictly_after_the_given_day() -> None:
    """On the billing day itself, the *next* charge is the following cycle."""
    anchor = date(2026, 1, 15)

    assert next_billing_after(anchor, MONTHLY, date(2026, 3, 15)) == date(2026, 4, 15)


def test_a_day_before_the_first_charge_returns_the_anchor() -> None:
    anchor = date(2026, 6, 1)

    assert next_billing_after(anchor, MONTHLY, date(2026, 1, 1)) == anchor


def test_the_next_date_after_a_long_gap_is_correct() -> None:
    """Three years of weekly charges must not be found by counting up from zero."""
    anchor = date(2023, 1, 4)  # a Wednesday

    result = next_billing_after(anchor, WEEKLY, date(2026, 3, 15))

    assert result > date(2026, 3, 15)
    assert (result - anchor).days % 7 == 0
    assert (result - date(2026, 3, 15)).days <= 7


def test_the_next_date_respects_month_end_clamping() -> None:
    anchor = date(2026, 1, 31)

    assert next_billing_after(anchor, MONTHLY, date(2026, 2, 15)) == date(2026, 2, 28)
    assert next_billing_after(anchor, MONTHLY, date(2026, 2, 28)) == date(2026, 3, 31)


@pytest.mark.parametrize("cycle", [WEEKLY, MONTHLY, QUARTERLY, YEARLY])
def test_the_next_date_is_always_in_the_future(cycle: BillingCycle) -> None:
    """A property that must hold for every cycle, not just the ones with examples."""
    anchor = date(2026, 1, 31)

    for day in (date(2026, 1, 30), date(2026, 1, 31), date(2027, 7, 4), date(2030, 12, 31)):
        assert next_billing_after(anchor, cycle, day) > day


def test_consecutive_calls_walk_forward_one_cycle_at_a_time() -> None:
    anchor = date(2026, 1, 31)
    seen = []
    cursor = date(2026, 1, 30)

    for _ in range(4):
        cursor = next_billing_after(anchor, MONTHLY, cursor)
        seen.append(cursor)

    assert seen == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


# ─── Cost equivalents ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("amount", "cycle", "monthly", "yearly"),
    [
        ("500.00", MONTHLY, "500.00", "6000.00"),
        ("6000.00", YEARLY, "500.00", "6000.00"),
        ("1500.00", QUARTERLY, "500.00", "6000.00"),
        # 100 a week is 5200 a year, so 433.33 a month — not 400.
        ("100.00", WEEKLY, "433.33", "5200.00"),
    ],
)
def test_cost_equivalents(amount: str, cycle: BillingCycle, monthly: str, yearly: str) -> None:
    assert monthly_equivalent(Decimal(amount), cycle) == Decimal(monthly)
    assert yearly_equivalent(Decimal(amount), cycle) == Decimal(yearly)


def test_a_weekly_cost_is_not_four_weeks_to_the_month() -> None:
    """Treating a month as four weeks understates a weekly cost by about 8%."""
    four_weeks = Decimal("100.00") * 4

    assert monthly_equivalent(Decimal("100.00"), WEEKLY) > four_weeks


def test_equivalents_stay_decimal_and_are_rounded_to_two_places() -> None:
    result = monthly_equivalent(Decimal("9.99"), WEEKLY)

    assert isinstance(result, Decimal)
    assert result == Decimal("43.29")


def test_monthly_times_twelve_is_within_rounding_of_yearly() -> None:
    """The two figures are shown side by side, so they must not contradict."""
    monthly = monthly_equivalent(Decimal("100.00"), WEEKLY)
    yearly = yearly_equivalent(Decimal("100.00"), WEEKLY)

    assert abs(monthly * 12 - yearly) <= Decimal("0.05")


# ─── days_until ───────────────────────────────────────────────────────────


def test_days_until_counts_forward_and_backward() -> None:
    today = date(2026, 3, 15)

    assert days_until(date(2026, 3, 20), today) == 5
    assert days_until(date(2026, 3, 15), today) == 0
    assert days_until(date(2026, 3, 10), today) == -5
