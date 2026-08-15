"""Tests for turning a `Decimal` percentage into the text beside a bar.

Reported from manual testing: the spending chart's percentages "looked
visually and mathematically suspicious". They were. A 500/300 split has the
server returning 62.50 and 37.50, and the chart printed *62%* and *38%* — the
same half rounded in two different directions, because `f"{value:.0f}"` on a
`Decimal` uses the decimal context, and its default is banker's rounding.

These are pure arithmetic, so they need no Qt at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from client.core.formatting import percentage_text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # The reported case, both halves of it.
        ("62.50", "62.5"),
        ("37.50", "37.5"),
        # Halves round *up*, never to the nearest even number. Under banker's
        # rounding these four came out 12, 2, 0 and 4 — two of them down.
        ("12.50", "12.5"),
        ("2.50", "2.5"),
        ("0.50", "0.5"),
        ("3.50", "3.5"),
        # A whole share reads as a whole number, with no decimal point to
        # imply a precision that is not there.
        ("50.00", "50"),
        ("100.00", "100"),
        ("0.00", "0"),
        # Thirds keep the one decimal that distinguishes them.
        ("33.33", "33.3"),
        ("16.67", "16.7"),
        # Rounding at the second decimal is half-up too: 66.65 -> 66.7, and
        # 33.34 -> 33.3.
        ("66.65", "66.7"),
        ("33.34", "33.3"),
    ],
)
def test_percentages_are_rounded_half_up_to_one_decimal(value: str, expected: str) -> None:
    assert percentage_text(Decimal(value)) == expected


def test_the_two_halves_of_a_split_do_not_disagree() -> None:
    """The bug, stated as the property it broke.

    62.5 and 37.5 are one total split in two. Whatever rounding is applied has
    to treat them the same way, or the two figures stop adding up.
    """
    food = percentage_text(Decimal("62.50"))
    transport = percentage_text(Decimal("37.50"))

    assert (food, transport) == ("62.5", "37.5")
    assert Decimal(food) + Decimal(transport) == Decimal("100.0")


def test_a_percentage_is_never_reported_as_a_different_number() -> None:
    """Displayed text must round-trip to within half of the last digit shown."""
    for hundredths in range(0, 10001):
        value = Decimal(hundredths) / Decimal("100")
        shown = Decimal(percentage_text(value))

        assert abs(shown - value) <= Decimal("0.05"), value
