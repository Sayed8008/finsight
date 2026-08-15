"""Turning the numbers the server sends into the text a person reads.

Money and percentages arrive as `Decimal` (ADR-003) precisely so that nothing
between the database and the screen introduces a rounding error. Formatting is
the last step where one can still be introduced, and `f"{value:.0f}"` does
introduce one twice over:

  * It **drops the fraction**. The server computed 62.50%, and `:.0f` prints
    "62%" — the half is simply gone.
  * It rounds **half to even**, because formatting a `Decimal` uses the decimal
    context, whose default is `ROUND_HALF_EVEN`. So 62.50 rounds *down* to 62
    while 37.50 rounds *up* to 38. Two shares of one total, rounded in opposite
    directions.

Both together are what made the spending chart read "Food 62%, Transport 38%"
for a 500/300 split: neither figure matched the server, and they only summed to
100 by accident. The bars themselves were drawn from the amounts and were
correct all along, which is why the labels looked wrong *beside* them.

`ROUND_HALF_UP` matches `backend/app/core/money.py`, so a figure rounded for
display rounds the same way it would have on the server.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

#: One decimal place. Enough to show that 62.5 and 37.5 are halves rather than
#: whole numbers, without implying the precision that 62.50% would.
TENTHS = Decimal("0.1")


def percentage_text(value: Decimal) -> str:
    """A percentage as it should be shown, without the `%` sign.

    Rounded half *up* to one decimal place, and a trailing ".0" dropped so a
    clean share reads "50" rather than "50.0":

        >>> percentage_text(Decimal("62.50"))
        '62.5'
        >>> percentage_text(Decimal("37.50"))
        '37.5'
        >>> percentage_text(Decimal("50.00"))
        '50'
    """
    rounded = value.quantize(TENTHS, rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral_value():
        return f"{rounded:.0f}"
    return f"{rounded:.1f}"
