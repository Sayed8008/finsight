"""Money: how it is rounded, and how it crosses the wire.

Every rule about amounts lives here, so that rounding and
division-by-zero are decided once rather than reinvented at each call site
(ADR-003).

Three annotated types are exported for schemas to use:

  * `MoneyOut`         — an amount in a response. Serialises to a JSON
                         *string*, because a JSON number is an IEEE double and
                         would reintroduce exactly the imprecision `Decimal`
                         was chosen to avoid.
  * `PositiveMoney`    — an amount in a request body. Must be greater than
                         zero: direction is carried by `transaction_type`, not
                         by the sign of the amount.
  * `NonNegativeMoney` — an amount in a *filter*, where zero is a legitimate
                         lower bound.

All three accept a JSON string or number as input; Pydantic converts either to
`Decimal` without going through `float`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer

# Matches DECIMAL(14,2) in MySQL: at most 14 significant digits, 2 of them
# after the point. Declaring them here means the API rejects an over-long
# amount with a 422 rather than letting the database raise on INSERT.
MONEY_MAX_DIGITS = 14
MONEY_DECIMAL_PLACES = 2

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")

# One hundred, as a Decimal, so percentage arithmetic never touches a float.
HUNDRED = Decimal("100")


def quantise(value: Decimal) -> Decimal:
    """Round to two decimal places, half away from zero.

    `ROUND_HALF_UP` is stated explicitly because Python's default is
    `ROUND_HALF_EVEN` (banker's rounding), which rounds 0.005 to 0.00. That is
    the correct default for repeated statistical operations and the wrong one
    for money a person is going to read: everyone expects half a unit to round
    up.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def to_wire(value: Decimal) -> str:
    """Format an amount for JSON.

    `format(..., "f")` rather than `str()`: `str()` on a Decimal can produce
    scientific notation (`str(Decimal("1E+2")) == "1E+2"`), which is valid
    JSON but not something a client should have to parse.
    """
    return format(quantise(value), "f")


def percentage_of(part: Decimal, whole: Decimal) -> Decimal:
    """`part` as a percentage of `whole`, or zero when `whole` is zero.

    A budget of nothing, or a month with no spending, is a real state rather
    than an error — so this returns zero instead of raising. Deciding that
    once here is what stops it being decided differently in three places.
    """
    if whole == 0:
        return ZERO
    return quantise(part / whole * HUNDRED)


#: An amount in a response body. Serialised as a JSON string (ADR-003).
#: `when_used="json"` keeps `model_dump()` returning a `Decimal`, so Python
#: callers and tests still work with the real numeric type.
MoneyOut = Annotated[
    Decimal,
    PlainSerializer(to_wire, return_type=str, when_used="json"),
]

#: A percentage in a response. Given the same treatment as an amount, and for
#: the same reason: it is a `Decimal`, and a JSON number would round it.
PercentageOut = Annotated[
    Decimal,
    PlainSerializer(to_wire, return_type=str, when_used="json"),
]

#: An amount in a request body: strictly positive, at most two decimal places.
PositiveMoney = Annotated[
    Decimal,
    Field(gt=0, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES),
]

#: An amount used as a filter bound, where zero is meaningful.
NonNegativeMoney = Annotated[
    Decimal,
    Field(ge=0, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES),
]
