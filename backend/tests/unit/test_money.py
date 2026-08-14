"""Tests for the money rules.

These are pure unit tests: no database, no HTTP. What they protect is the
claim in ADR-003 that amounts survive a round trip through JSON unchanged.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.core.money import (
    MoneyOut,
    NonNegativeMoney,
    PositiveMoney,
    percentage_of,
    quantise,
    to_wire,
)


class Amounts(BaseModel):
    """A stand-in for a real schema, used to exercise the annotated types."""

    out: MoneyOut = Decimal("0.00")
    positive: PositiveMoney = Decimal("1.00")
    bound: NonNegativeMoney = Decimal("0.00")


# ─── Rounding ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("650", "650.00"),
        ("650.4", "650.40"),
        ("650.404", "650.40"),
        ("650.405", "650.41"),  # half rounds up, not to even
        ("650.415", "650.42"),  # would be 650.41 under banker's rounding
        ("0.005", "0.01"),
        ("-0.005", "-0.01"),  # half away from zero, symmetrically
    ],
)
def test_quantise_rounds_half_away_from_zero(value: str, expected: str) -> None:
    """Python's default is banker's rounding, which is wrong for money."""
    assert quantise(Decimal(value)) == Decimal(expected)


def test_to_wire_never_uses_scientific_notation() -> None:
    """`str()` on a Decimal can produce "1E+2"; a client should not have to parse that."""
    assert to_wire(Decimal("1E+2")) == "100.00"


def test_to_wire_always_shows_two_decimal_places() -> None:
    assert to_wire(Decimal("650")) == "650.00"
    assert to_wire(Decimal("650.5")) == "650.50"


# ─── Percentages ──────────────────────────────────────────────────────────


def test_percentage_of_computes_a_share() -> None:
    assert percentage_of(Decimal("250.00"), Decimal("1000.00")) == Decimal("25.00")


def test_percentage_of_a_zero_whole_is_zero_not_an_error() -> None:
    """A budget of nothing is a real state, not a failure."""
    assert percentage_of(Decimal("50.00"), Decimal("0.00")) == Decimal("0.00")


def test_percentage_can_exceed_one_hundred() -> None:
    """An exceeded budget must report how far over, not be clamped."""
    assert percentage_of(Decimal("1500.00"), Decimal("1000.00")) == Decimal("150.00")


# ─── Serialisation ────────────────────────────────────────────────────────


def test_amounts_serialise_to_json_as_strings() -> None:
    """A JSON number is an IEEE double; a string survives the wire intact."""
    payload = Amounts(out=Decimal("1234.50")).model_dump(mode="json")

    assert payload["out"] == "1234.50"
    assert isinstance(payload["out"], str)


def test_python_mode_keeps_the_decimal() -> None:
    """Only the wire format is a string — in-process callers get real numbers."""
    assert Amounts(out=Decimal("1234.50")).model_dump()["out"] == Decimal("1234.50")


def test_a_string_amount_is_accepted_and_becomes_a_decimal() -> None:
    assert Amounts(out="1234.50").out == Decimal("1234.50")


def test_a_float_amount_does_not_drift() -> None:
    """0.1 + 0.2 as floats is 0.30000000000000004. Through Decimal it is not."""
    total = Amounts(out="0.10").out + Amounts(out="0.20").out

    assert total == Decimal("0.30")
    assert to_wire(total) == "0.30"


# ─── Input constraints ────────────────────────────────────────────────────


def test_zero_is_rejected_where_an_amount_must_be_positive() -> None:
    """Direction is carried by transaction_type, so an amount of zero is meaningless."""
    with pytest.raises(ValidationError):
        Amounts(positive=Decimal("0.00"))


def test_a_negative_amount_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Amounts(positive=Decimal("-1.00"))


def test_zero_is_accepted_as_a_filter_bound() -> None:
    assert Amounts(bound=Decimal("0.00")).bound == Decimal("0.00")


def test_more_than_two_decimal_places_is_rejected() -> None:
    """Better a 422 than a silent truncation by DECIMAL(14,2) on INSERT."""
    with pytest.raises(ValidationError):
        Amounts(positive=Decimal("10.001"))


def test_an_amount_too_large_for_the_column_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Amounts(positive=Decimal("1234567890123.00"))
