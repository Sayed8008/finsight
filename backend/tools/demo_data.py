"""A year of plausible financial history, for demonstrations and screenshots.

Pure and deterministic: dates and a seed in, values out. Not part of the
application — nothing under `app/` imports it — but written to the same standard
as the code it feeds, because a demo built on nonsense demonstrates nothing.

**Why deterministic.** A demo that generates different figures each run cannot
be rehearsed, and screenshots taken from it disagree with each other and with
whatever is on screen on the day. One seed, one history.

**Why it is not simply random.** The point of the demo is the two features that
are actually interesting — subscription detection and CSV import — and both need
history with real structure in it:

  * three genuine subscriptions, one of them with a price rise partway through,
    so detection has something to find and something to get right;
  * a gym paid at irregular intervals for similar amounts, so detection has
    something to correctly *not* find. A demo where everything is detected
    proves only that the threshold is low;
  * a merchant whose description carries no name at all, which is the
    limitation ADR-007 records and the honest thing to show;
  * enough ordinary spending, with variation, that the charts have shape and the
    budgets sit at interesting percentages rather than at 0 or 200.

There is a unit test that runs the real detector over this history and asserts
it finds exactly the three subscriptions and not the gym. That test is what
makes this file trustworthy — otherwise "plausible" is just a claim.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.models.enums import BillingCycle, TransactionType

#: Fixed, so a demo can be rehearsed and screenshots agree with each other.
DEFAULT_SEED = 20260815

#: How much history to build. A year covers four quarterly charges, gives the
#: trend chart twelve months, and is what makes detection worth running.
DEFAULT_DAYS = 365


@dataclass(frozen=True)
class DemoTransaction:
    """One row to create, in the shape `POST /transactions` takes."""

    date: date
    amount: Decimal
    transaction_type: TransactionType
    category: str
    description: str
    payment_method: str | None = None

    def as_payload(self, category_id: int) -> dict[str, object]:
        return {
            "amount": f"{self.amount:.2f}",
            "transaction_type": str(self.transaction_type),
            "category_id": category_id,
            "date": self.date.isoformat(),
            "description": self.description,
            "payment_method": self.payment_method,
        }


@dataclass(frozen=True)
class DemoSubscription:
    """One subscription to track, in the shape `POST /subscriptions` takes."""

    name: str
    amount: Decimal
    billing_cycle: BillingCycle
    start_date: date
    category: str

    def as_payload(self, category_id: int) -> dict[str, object]:
        return {
            "name": self.name,
            "amount": f"{self.amount:.2f}",
            "billing_cycle": str(self.billing_cycle),
            "start_date": self.start_date.isoformat(),
            "category_id": category_id,
        }


@dataclass(frozen=True)
class DemoBudget:
    """One budget to set, in the shape `POST /budgets` takes."""

    category: str
    amount: Decimal
    period_start: date
    period_end: date

    def as_payload(self, category_id: int) -> dict[str, object]:
        return {
            "category_id": category_id,
            "amount": f"{self.amount:.2f}",
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
        }


@dataclass(frozen=True)
class DemoHistory:
    """Everything a demonstration account should contain."""

    transactions: tuple[DemoTransaction, ...] = ()
    #: Deliberately only *some* of the recurring charges below. The rest are
    #: left untracked so that "Find subscriptions" has something to propose.
    subscriptions: tuple[DemoSubscription, ...] = ()
    budgets: tuple[DemoBudget, ...] = ()
    #: The categories used, so a caller can check they all exist before writing
    #: anything.
    categories: tuple[str, ...] = field(default=())


# ─── The recurring charges ────────────────────────────────────────────────


@dataclass(frozen=True)
class Recurring:
    """A charge that repeats, and how regularly."""

    merchant: str
    amount: Decimal
    every_days: int
    category: str
    #: Applied from this many charges in, so a price rise appears mid-history.
    raised_to: Decimal | None = None
    raised_after: int = 0
    #: Days of slack either side of the nominal interval. Real billing wobbles;
    #: a perfectly regular year would flatter the detector.
    jitter_days: int = 0


SUBSCRIPTIONS: tuple[Recurring, ...] = (
    Recurring("NETFLIX.COM", Decimal("499.00"), 30, "Subscriptions"),
    # A 10% rise partway through. Deliberately inside the detector's 15%
    # tolerance (ADR-031): the demonstration is that a price rise stays *one*
    # subscription. An earlier draft used 199 → 249, which is 25% and which the
    # detector correctly split into two — the test caught it, and the fix was
    # to the demo rather than to the tolerance.
    Recurring(
        "SPOTIFY AB",
        Decimal("199.00"),
        30,
        "Subscriptions",
        raised_to=Decimal("219.00"),
        raised_after=7,
        jitter_days=1,
    ),
    Recurring("ADOBE SYSTEMS", Decimal("2100.00"), 91, "Subscriptions", jitter_days=2),
)

#: Charged at irregular intervals for similar amounts. Detection must *not*
#: propose this, and a demo where everything is detected proves nothing about
#: the threshold. The gaps below are 18, 44, 25 and 51 days.
GYM_DAYS = (0, 18, 62, 87, 138, 191, 244)
GYM = Recurring("FITNESS FIRST GULSHAN", Decimal("1500.00"), 0, "Healthcare")

#: Normalises to nothing, so detection skips it and says so. The limitation
#: ADR-007 recorded from the start, made visible rather than hidden.
OPAQUE_MERCHANT = "POS PURCHASE 4021"


# ─── The ordinary spending ────────────────────────────────────────────────


@dataclass(frozen=True)
class Habit:
    """Everyday spending, with the variation everyday spending has."""

    description: str
    category: str
    low: int
    high: int
    #: Roughly how many days between one and the next.
    every_days: int
    payment_method: str


HABITS: tuple[Habit, ...] = (
    Habit("SHWAPNO SUPERSHOP", "Food", 900, 2600, 6, "bKash"),
    Habit("CAMPUS CANTEEN", "Food", 90, 320, 3, "Cash"),
    Habit("UBER", "Transport", 120, 480, 5, "bKash"),
    Habit("CNG FARE", "Transport", 60, 200, 4, "Cash"),
    Habit("DARAZ ORDER", "Shopping", 450, 3800, 21, "Card"),
    Habit("STAR CINEPLEX", "Entertainment", 350, 900, 30, "Card"),
    Habit("BOOK SHOP", "Education", 300, 1800, 45, "Cash"),
    Habit("PHARMACY", "Healthcare", 150, 900, 35, "Cash"),
)

MONTHLY_SALARY = Decimal("52000.00")
MONTHLY_RENT = Decimal("14000.00")
MONTHLY_INTERNET = Decimal("1200.00")

#: Freelance work arrives when it arrives. Irregular income is what makes the
#: trend chart worth looking at rather than a flat line and a staircase.
FREELANCE_MONTHS = (1, 3, 4, 7, 9, 11)


def build_history(
    *, today: date, days: int = DEFAULT_DAYS, seed: int = DEFAULT_SEED
) -> DemoHistory:
    """A year of history ending today.

    `today` is a parameter rather than read from the clock, for the same reason
    it is one in `insight_rules`: a function that asks what day it is cannot be
    tested, and a demo generated at 23:59 would otherwise differ from the same
    demo generated a minute later.
    """
    rng = random.Random(seed)
    start = today - timedelta(days=days)

    transactions: list[DemoTransaction] = []
    transactions.extend(_income(start, today))
    transactions.extend(_fixed_costs(start, today))
    transactions.extend(_recurring_charges(start, today, rng))
    transactions.extend(_habits(start, today, rng))
    transactions.extend(_opaque_charges(start, today))

    ordered = tuple(sorted(transactions, key=lambda item: (item.date, item.description)))

    return DemoHistory(
        transactions=ordered,
        subscriptions=_tracked_subscriptions(start),
        budgets=_budgets(today, transactions),
        categories=tuple(sorted({item.category for item in ordered})),
    )


# ─── Pieces ───────────────────────────────────────────────────────────────


def _month_starts(start: date, today: date) -> list[date]:
    """The first of each month covered, so monthly items land on a real day."""
    months: list[date] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= today:
        months.append(cursor)
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return months


def _on_day(month: date, day: int, start: date, today: date) -> date | None:
    """A given day of a month, if it is inside the window and exists."""
    try:
        moment = month.replace(day=day)
    except ValueError:
        return None
    return moment if start <= moment <= today else None


def _income(start: date, today: date) -> list[DemoTransaction]:
    rows: list[DemoTransaction] = []
    for index, month in enumerate(_month_starts(start, today)):
        # Paid on the first, rent on the fifth. An earlier draft paid on the
        # 28th, which is just as realistic and made every screenshot taken
        # mid-month show "Money in 0.00" and a critical "you spent more than
        # you earned" — true for the period, and a poor thing to demonstrate.
        payday = _on_day(month, 1, start, today)
        if payday is not None:
            rows.append(
                DemoTransaction(
                    date=payday,
                    amount=MONTHLY_SALARY,
                    transaction_type=TransactionType.INCOME,
                    category="Salary",
                    description="MONTHLY SALARY",
                    payment_method="Bank transfer",
                )
            )

        if index % 12 in FREELANCE_MONTHS:
            when = _on_day(month, 14, start, today)
            if when is not None:
                rows.append(
                    DemoTransaction(
                        date=when,
                        # Varied deliberately: identical freelance payments
                        # would look like a subscription being paid *to* the
                        # user, and income is never proposed anyway.
                        amount=Decimal(9000 + (index % 5) * 1750),
                        transaction_type=TransactionType.INCOME,
                        category="Freelance",
                        description="UPWORK PAYOUT",
                        payment_method="Bank transfer",
                    )
                )
    return rows


def _fixed_costs(start: date, today: date) -> list[DemoTransaction]:
    rows: list[DemoTransaction] = []
    for month in _month_starts(start, today):
        rent_day = _on_day(month, 5, start, today)
        if rent_day is not None:
            rows.append(
                DemoTransaction(
                    date=rent_day,
                    amount=MONTHLY_RENT,
                    transaction_type=TransactionType.EXPENSE,
                    category="Rent",
                    description="HOUSE RENT",
                    payment_method="Bank transfer",
                )
            )

        internet_day = _on_day(month, 8, start, today)
        if internet_day is not None:
            rows.append(
                DemoTransaction(
                    date=internet_day,
                    amount=MONTHLY_INTERNET,
                    transaction_type=TransactionType.EXPENSE,
                    category="Bills",
                    description="LINK3 INTERNET",
                    payment_method="bKash",
                )
            )
    return rows


def _recurring_charges(
    start: date, today: date, rng: random.Random
) -> list[DemoTransaction]:
    """The subscriptions, as they appear in transaction history.

    These are ordinary expense rows. Nothing marks them as recurring — which is
    the point: detection has to find them the way it would in a real account.
    """
    rows: list[DemoTransaction] = []

    for plan in SUBSCRIPTIONS:
        occurrence = 0
        when = start + timedelta(days=rng.randint(0, 20))
        while when <= today:
            amount = plan.amount
            if plan.raised_to is not None and occurrence >= plan.raised_after:
                amount = plan.raised_to

            rows.append(
                DemoTransaction(
                    date=when,
                    amount=amount,
                    transaction_type=TransactionType.EXPENSE,
                    category=plan.category,
                    description=plan.merchant,
                    payment_method="Card",
                )
            )
            occurrence += 1
            drift = rng.randint(-plan.jitter_days, plan.jitter_days) if plan.jitter_days else 0
            when += timedelta(days=plan.every_days + drift)

    for offset in GYM_DAYS:
        when = start + timedelta(days=offset)
        if when <= today:
            rows.append(
                DemoTransaction(
                    date=when,
                    amount=GYM.amount,
                    transaction_type=TransactionType.EXPENSE,
                    category=GYM.category,
                    description=GYM.merchant,
                    payment_method="Cash",
                )
            )

    return rows


def _habits(start: date, today: date, rng: random.Random) -> list[DemoTransaction]:
    rows: list[DemoTransaction] = []
    for habit in HABITS:
        when = start + timedelta(days=rng.randint(0, habit.every_days))
        while when <= today:
            rows.append(
                DemoTransaction(
                    date=when,
                    # Whole taka. A supermarket receipt for 1,847.23 is not
                    # wrong, but a screenshot full of stray paisa reads as
                    # generated data rather than as somebody's spending.
                    amount=Decimal(rng.randint(habit.low, habit.high)),
                    transaction_type=TransactionType.EXPENSE,
                    category=habit.category,
                    description=habit.description,
                    payment_method=habit.payment_method,
                )
            )
            gap = max(1, habit.every_days + rng.randint(-2, 3))
            when += timedelta(days=gap)
    return rows


def _opaque_charges(start: date, today: date) -> list[DemoTransaction]:
    """Charges whose description carries no merchant.

    Included on purpose. ADR-007 records that these are unmatchable, and a demo
    that quietly leaves them out is a demo of a limitation that does not exist.
    """
    rows: list[DemoTransaction] = []
    for offset in (40, 71, 102, 133):
        when = start + timedelta(days=offset)
        if when <= today:
            rows.append(
                DemoTransaction(
                    date=when,
                    amount=Decimal("650.00"),
                    transaction_type=TransactionType.EXPENSE,
                    category="Other",
                    description=OPAQUE_MERCHANT,
                    payment_method="Card",
                )
            )
    return rows


def _tracked_subscriptions(start: date) -> tuple[DemoSubscription, ...]:
    """Only Netflix is tracked up front.

    The other two are left for "Find subscriptions" to propose, which is the
    demonstration. Tracking all three would leave detection with nothing to say,
    and tracking none would leave the subscriptions screen empty on the way in.
    """
    return (
        DemoSubscription(
            name="Netflix",
            amount=Decimal("499.00"),
            billing_cycle=BillingCycle.MONTHLY,
            start_date=start + timedelta(days=3),
            category="Subscriptions",
        ),
    )


#: What share of each budget should already be spent, so the screen shows one
#: of each state. The server's thresholds are 80% for warning and 100% for
#: exceeded (`budget_utilisation`), and these sit either side of both.
BUDGET_TARGETS: tuple[tuple[str, Decimal], ...] = (
    ("Food", Decimal("0.45")),
    ("Transport", Decimal("0.88")),
    ("Entertainment", Decimal("1.15")),
)

#: Used when a category has no spending yet this month, which happens if the
#: demo is seeded on the first or second of a month.
FALLBACK_BUDGET = Decimal("3000.00")


def _budgets(today: date, transactions: list[DemoTransaction]) -> tuple[DemoBudget, ...]:
    """Budgets for the current month, sized against what has actually been spent.

    Derived from the generated history rather than written as fixed amounts.
    Fixed amounts only land in interesting states on the day they were chosen
    for: a 12,000 food budget is 24% used on the 15th and 55% used on the 30th,
    so a screenshot taken mid-month showed three green bars — which
    demonstrates a progress bar, not a budget. Sizing from month-to-date
    spending gives one comfortable, one close to its limit and one over,
    whatever day the demo is seeded.
    """
    first = today.replace(day=1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    spent: dict[str, Decimal] = {}
    for row in transactions:
        if row.transaction_type is TransactionType.EXPENSE and first <= row.date <= today:
            spent[row.category] = spent.get(row.category, Decimal(0)) + row.amount

    budgets: list[DemoBudget] = []
    for category, share in BUDGET_TARGETS:
        so_far = spent.get(category, Decimal(0))
        amount = (so_far / share) if so_far else FALLBACK_BUDGET
        # Rounded to the nearest hundred: a budget of 6,275.56 reads as a
        # figure the application computed rather than one a person chose.
        rounded = (amount / 100).quantize(Decimal("1")) * 100
        budgets.append(DemoBudget(category, max(rounded, Decimal("500.00")), first, last))

    return tuple(budgets)


__all__ = [
    "DEFAULT_DAYS",
    "DEFAULT_SEED",
    "GYM",
    "OPAQUE_MERCHANT",
    "SUBSCRIPTIONS",
    "DemoBudget",
    "DemoHistory",
    "DemoSubscription",
    "DemoTransaction",
    "build_history",
]
