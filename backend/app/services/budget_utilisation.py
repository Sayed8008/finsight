"""How far through a budget you are.

Pure arithmetic: given a limit and what has been spent against it, produce the
remaining amount, the percentage used, and a status. No database, no HTTP,
nothing to mock — which is why it lives in its own module rather than inside
`BudgetService`. Every threshold the interface colours by is decided here, once.

None of this is stored (ADR-015). A `spent` column would be a cache that goes
stale the instant a transaction is added, edited, recategorised or deleted, and
keeping it correct would mean invalidation logic on every write path.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.money import ZERO, percentage_of, quantise


class BudgetStatus(StrEnum):
    """How a budget is doing.

    Deliberately *not* in `app/models/enums.py`. Everything there maps to a
    database column; this is computed on read and must never acquire one.
    """

    HEALTHY = "healthy"
    WARNING = "warning"
    EXCEEDED = "exceeded"


#: Percentage at which a budget starts warning. 80% is the conventional
#: threshold, and it is a percentage rather than an absolute amount so it means
#: the same thing for a 500 budget and a 50,000 one.
WARNING_AT = Decimal("80")

#: Percentage at which a budget counts as exceeded. Note this is *at* 100, not
#: above it: spending exactly the limit leaves nothing, and in a finance
#: application the safer signal is the louder one.
EXCEEDED_AT = Decimal("100")


@dataclass(frozen=True)
class Utilisation:
    """A budget's limit and progress against it."""

    amount: Decimal
    spent: Decimal
    #: `amount - spent`. Negative when overspent, deliberately: clamping it at
    #: zero would hide by how much, which is the number that matters most.
    remaining: Decimal
    percentage_used: Decimal
    status: BudgetStatus

    @classmethod
    def of(cls, amount: Decimal, spent: Decimal) -> Utilisation:
        """Work out where a budget stands."""
        percentage = percentage_of(spent, amount)
        return cls(
            amount=quantise(amount),
            spent=quantise(spent),
            remaining=quantise(amount - spent),
            percentage_used=percentage,
            status=status_for(percentage),
        )

    @property
    def is_overspent(self) -> bool:
        return self.remaining < ZERO

    @property
    def overspend(self) -> Decimal:
        """How far past the limit, as a positive number. Zero if within it."""
        return -self.remaining if self.is_overspent else ZERO


def status_for(percentage_used: Decimal) -> BudgetStatus:
    """Turn a percentage into a status.

    Thresholds are applied to the *rounded* percentage — the same value the
    interface displays. Comparing the raw ratio instead would let a budget show
    "80.00% used" beside a green bar, because 79.996% rounds up for display but
    not for the comparison. Whatever the user reads should be what decided the
    colour.
    """
    if percentage_used >= EXCEEDED_AT:
        return BudgetStatus.EXCEEDED
    if percentage_used >= WARNING_AT:
        return BudgetStatus.WARNING
    return BudgetStatus.HEALTHY
