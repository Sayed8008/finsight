"""Tests for the budget arithmetic.

Pure unit tests — no database, no HTTP. These pin the thresholds the whole
interface colours by, and the boundaries where one status becomes another.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.services.budget_utilisation import BudgetStatus, Utilisation, status_for


def used(amount: str, spent: str) -> Utilisation:
    return Utilisation.of(Decimal(amount), Decimal(spent))


# ─── The figures ──────────────────────────────────────────────────────────


def test_a_budget_with_nothing_spent() -> None:
    result = used("5000.00", "0.00")

    assert result.remaining == Decimal("5000.00")
    assert result.percentage_used == Decimal("0.00")
    assert result.status is BudgetStatus.HEALTHY


def test_remaining_is_the_limit_less_the_spend() -> None:
    assert used("5000.00", "1250.50").remaining == Decimal("3749.50")


def test_percentage_is_rounded_to_two_places() -> None:
    # 1000/3000 is 33.333...%
    assert used("3000.00", "1000.00").percentage_used == Decimal("33.33")


def test_everything_stays_decimal() -> None:
    """A float anywhere here would drift once these are summed (ADR-003)."""
    result = used("0.10", "0.03")

    assert isinstance(result.remaining, Decimal)
    assert result.remaining == Decimal("0.07")


# ─── Overspending ─────────────────────────────────────────────────────────


def test_remaining_goes_negative_rather_than_clamping_at_zero() -> None:
    """By how much a budget was blown is the number that matters most."""
    result = used("1000.00", "1250.00")

    assert result.remaining == Decimal("-250.00")
    assert result.is_overspent
    assert result.overspend == Decimal("250.00")


def test_a_budget_within_its_limit_has_no_overspend() -> None:
    result = used("1000.00", "400.00")

    assert not result.is_overspent
    assert result.overspend == Decimal("0.00")


def test_percentage_can_exceed_one_hundred() -> None:
    assert used("1000.00", "1500.00").percentage_used == Decimal("150.00")


# ─── Status thresholds ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("percentage", "expected"),
    [
        ("0.00", BudgetStatus.HEALTHY),
        ("79.99", BudgetStatus.HEALTHY),
        ("80.00", BudgetStatus.WARNING),  # warning begins exactly at 80
        ("99.99", BudgetStatus.WARNING),
        ("100.00", BudgetStatus.EXCEEDED),  # nothing left counts as exceeded
        ("100.01", BudgetStatus.EXCEEDED),
        ("1000.00", BudgetStatus.EXCEEDED),
    ],
)
def test_status_boundaries(percentage: str, expected: BudgetStatus) -> None:
    assert status_for(Decimal(percentage)) is expected


def test_spending_the_budget_exactly_is_exceeded_not_warning() -> None:
    """Nothing is left, so the louder signal is the safer one."""
    result = used("1000.00", "1000.00")

    assert result.remaining == Decimal("0.00")
    assert result.status is BudgetStatus.EXCEEDED


def test_status_agrees_with_the_percentage_that_is_displayed() -> None:
    """The rounded percentage decides the colour, so the two cannot disagree.

    799.96 of 1000 is 79.996%, which displays as 80.00%. Comparing the raw
    ratio would show "80.00% used" beside a green bar.
    """
    result = used("1000.00", "799.96")

    assert result.percentage_used == Decimal("80.00")
    assert result.status is BudgetStatus.WARNING


# ─── Degenerate input ─────────────────────────────────────────────────────


def test_a_zero_budget_does_not_divide_by_zero() -> None:
    """The schema and the database both forbid it; the maths still must not crash."""
    result = used("0.00", "50.00")

    assert result.percentage_used == Decimal("0.00")
    assert result.remaining == Decimal("-50.00")


def test_utilisation_is_immutable() -> None:
    """A computed value that something could edit would be a cache again."""
    result = used("1000.00", "100.00")

    with pytest.raises(FrozenInstanceError):
        result.spent = Decimal("999.00")
