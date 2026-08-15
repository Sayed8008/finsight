"""Billing cycle arithmetic: when a subscription renews, and what it costs.

Pure functions over dates and `Decimal`. No database, no HTTP — the same shape
as `budget_utilisation`, and for the same reason: this is where a subtle bug
would hide, so it is where the tests can reach without any setup.

Two things here are easy to get wrong.

**Month-end.** Adding a month to 31 January cannot produce 31 February. The
rule is to clamp to the last valid day of the target month.

**Drift.** Clamping introduces a second problem the moment you apply it twice.
Advancing 31 January by a month gives 28 February; advancing *that* by a month
gives 28 March, and the subscription has silently moved off the 31st for good.
So renewals are never computed by stepping from the previous one — every date
is computed as `start_date + n cycles`, from the original anchor. 31 January
then yields 28 Feb, 31 Mar, 30 Apr, 31 May, which is what a real biller does.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from app.core.money import quantise
from app.models.enums import BillingCycle

DAYS_IN_WEEK = 7
MONTHS_IN_YEAR = 12
WEEKS_IN_YEAR = Decimal("52")

#: How many months one cycle spans. Weekly is absent deliberately — it is not a
#: whole number of months and is handled as days instead.
MONTHS_PER_CYCLE: dict[BillingCycle, int] = {
    BillingCycle.MONTHLY: 1,
    BillingCycle.QUARTERLY: 3,
    BillingCycle.YEARLY: 12,
}

#: How many times a cycle is charged in a year. One table, so the weekly figure
#: cannot be 4-per-month in one place and 52-per-year in another — those differ
#: by about 8%, which is the sort of error nobody notices in a total.
CHARGES_PER_YEAR: dict[BillingCycle, Decimal] = {
    BillingCycle.WEEKLY: WEEKS_IN_YEAR,
    BillingCycle.MONTHLY: Decimal("12"),
    BillingCycle.QUARTERLY: Decimal("4"),
    BillingCycle.YEARLY: Decimal("1"),
}


def add_months(day: date, months: int) -> date:
    """Move a date by whole months, clamping to the last valid day.

    31 January plus one month is 28 February (29 in a leap year), because
    31 February does not exist. `calendar.monthrange` supplies the length of
    the target month, so leap years need no special case.
    """
    total = day.month - 1 + months
    year = day.year + total // MONTHS_IN_YEAR
    month = total % MONTHS_IN_YEAR + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def occurrence(anchor: date, cycle: BillingCycle, n: int) -> date:
    """The nth billing date on or after the anchor. `n=0` is the anchor itself.

    Always measured from the anchor, never from the previous occurrence, so
    clamping cannot accumulate into drift.
    """
    if cycle is BillingCycle.WEEKLY:
        return anchor + timedelta(days=DAYS_IN_WEEK * n)
    return add_months(anchor, MONTHS_PER_CYCLE[cycle] * n)


def next_billing_after(anchor: date, cycle: BillingCycle, after: date) -> date:
    """The first billing date strictly after `after`.

    Estimates the right cycle count and then steps, rather than counting up
    from zero — a weekly subscription started three years ago would otherwise
    take 150 iterations. The correction loop is bounded by a couple of steps
    because clamping can move a date by at most a few days.
    """
    if after < anchor:
        return anchor

    if cycle is BillingCycle.WEEKLY:
        elapsed = (after - anchor).days
        return anchor + timedelta(days=DAYS_IN_WEEK * (elapsed // DAYS_IN_WEEK + 1))

    step = MONTHS_PER_CYCLE[cycle]
    months_elapsed = (after.year - anchor.year) * MONTHS_IN_YEAR + (after.month - anchor.month)
    n = months_elapsed // step

    # Walk back to before `after`, then forward to the first date past it. Both
    # loops run at most twice; the estimate is only ever off by one cycle.
    while n > 0 and occurrence(anchor, cycle, n - 1) > after:
        n -= 1
    while occurrence(anchor, cycle, n) <= after:
        n += 1

    return occurrence(anchor, cycle, n)


def monthly_equivalent(amount: Decimal, cycle: BillingCycle) -> Decimal:
    """What this subscription costs per month, on average.

    A weekly charge is 52 per year, not 48: treating a month as four weeks
    understates a weekly subscription by about 8%, which is invisible in one
    row and material in a total.
    """
    return quantise(amount * CHARGES_PER_YEAR[cycle] / Decimal(MONTHS_IN_YEAR))


def yearly_equivalent(amount: Decimal, cycle: BillingCycle) -> Decimal:
    """What this subscription costs per year."""
    return quantise(amount * CHARGES_PER_YEAR[cycle])


def days_until(day: date, today: date) -> int:
    """Days from `today` until `day`. Negative once the date has passed."""
    return (day - today).days
