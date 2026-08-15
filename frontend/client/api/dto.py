"""Typed data transferred between the client and the API.

The interface works with these rather than raw dictionaries, so a renamed or
missing field fails once, here, at the boundary — instead of surfacing as a
`KeyError` inside a widget three screens later.

Amounts arrive as JSON strings and are converted to `Decimal` here (ADR-003).
That conversion belongs at the boundary: doing it in each widget would mean one
of them eventually reaching for `float`, and a total that is out by a penny
after enough rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Token:
    """An access token and how long it remains valid."""

    access_token: str
    token_type: str
    expires_in: int

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Token:
        return cls(
            access_token=payload["access_token"],
            token_type=payload.get("token_type", "bearer"),
            expires_in=int(payload.get("expires_in", 0)),
        )


#: Titles that are not names. Matched case-insensitively with any trailing dot
#: removed, so "Md.", "MD" and "md" all count. Kept deliberately short: the
#: cost of missing one is a slightly odd greeting, while the cost of being
#: over-eager is dropping a real name.
HONORIFICS = frozenset(
    {"md", "mohammad", "muhammad", "mst", "mrs", "mr", "ms", "miss", "dr", "prof", "eng"}
)


@dataclass(frozen=True)
class User:
    """The signed-in user, as the API describes them."""

    id: int
    email: str
    full_name: str
    currency_code: str
    role: str
    is_active: bool

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> User:
        return cls(
            id=int(payload["id"]),
            email=payload["email"],
            full_name=payload["full_name"],
            currency_code=payload.get("currency_code", "BDT"),
            role=payload.get("role", "user"),
            is_active=bool(payload.get("is_active", True)),
        )

    @property
    def first_name(self) -> str:
        """The name to greet someone by.

        Not simply the first word. "Md. Abu Sayed" would give "Md." — an
        honorific, not a name — and greeting a user by their title reads as a
        bug to the one person guaranteed to notice. Leading honorifics are
        skipped, and a name that is *only* an honorific falls back to the whole
        string rather than to nothing.
        """
        words = self.full_name.split()
        if not words:
            return self.email

        for word in words:
            if word.lower().rstrip(".") not in HONORIFICS:
                return word
        return self.full_name


INCOME = "income"
EXPENSE = "expense"

#: Zero, as a Decimal. Used for empty states, so no widget invents `0.0`.
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Category:
    """A category, as sent by the API."""

    id: int
    name: str
    category_type: str
    color: str | None = None
    icon: str | None = None
    is_active: bool = True

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Category:
        return cls(
            id=int(payload["id"]),
            name=payload["name"],
            category_type=payload["category_type"],
            color=payload.get("color"),
            icon=payload.get("icon"),
            # Absent when a category is embedded in a transaction: a
            # transaction's own category is shown whether or not it has since
            # been retired.
            is_active=bool(payload.get("is_active", True)),
        )

    @property
    def is_income(self) -> bool:
        return self.category_type == INCOME


@dataclass(frozen=True)
class Transaction:
    """One recorded income or expense."""

    id: int
    amount: Decimal
    transaction_type: str
    date: date_type
    category: Category
    description: str | None = None
    payment_method: str | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Transaction:
        return cls(
            id=int(payload["id"]),
            # A string in the JSON, deliberately. `Decimal(str)` is exact;
            # `Decimal(float)` would already have lost precision by the time it
            # got here.
            amount=Decimal(payload["amount"]),
            transaction_type=payload["transaction_type"],
            date=date_type.fromisoformat(payload["date"]),
            category=Category.from_json(payload["category"]),
            description=payload.get("description"),
            payment_method=payload.get("payment_method"),
        )

    @property
    def is_income(self) -> bool:
        return self.transaction_type == INCOME


@dataclass(frozen=True)
class TransactionPage:
    """One page of transactions, and enough to describe the rest.

    `total` counts everything matching the current filters, not the rows in
    `items` — which is what lets the pager say "page 3 of 12" rather than only
    offering "next".
    """

    items: tuple[Transaction, ...]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> TransactionPage:
        return cls(
            items=tuple(Transaction.from_json(item) for item in payload["items"]),
            total=int(payload["total"]),
            page=int(payload["page"]),
            page_size=int(payload["page_size"]),
            pages=int(payload["pages"]),
        )

    @classmethod
    def empty(cls, page_size: int) -> TransactionPage:
        """The page to show before anything has loaded, or after a failure."""
        return cls(items=(), total=0, page=1, page_size=page_size, pages=0)


#: Budget statuses, mirroring `BudgetStatus` on the server. Held as plain
#: strings rather than an enum: the client's job is to colour what it is told,
#: not to decide the thresholds, and an unrecognised value must render rather
#: than raise.
HEALTHY = "healthy"
WARNING = "warning"
EXCEEDED = "exceeded"


@dataclass(frozen=True)
class Budget:
    """A spending limit, together with progress against it.

    Everything from `spent` down is computed by the server on each read and
    stored nowhere (ADR-015). The client does not recompute any of it — that
    would be a second implementation of the thresholds, free to disagree with
    the first.
    """

    id: int
    category: Category
    amount: Decimal
    period_start: date_type
    period_end: date_type
    spent: Decimal
    #: Negative when overspent.
    remaining: Decimal
    percentage_used: Decimal
    status: str
    is_current: bool
    days_remaining: int | None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Budget:
        days = payload.get("days_remaining")
        return cls(
            id=int(payload["id"]),
            category=Category.from_json(payload["category"]),
            amount=Decimal(payload["amount"]),
            period_start=date_type.fromisoformat(payload["period_start"]),
            period_end=date_type.fromisoformat(payload["period_end"]),
            spent=Decimal(payload["spent"]),
            remaining=Decimal(payload["remaining"]),
            percentage_used=Decimal(payload["percentage_used"]),
            status=payload["status"],
            is_current=bool(payload["is_current"]),
            days_remaining=int(days) if days is not None else None,
        )

    @property
    def is_overspent(self) -> bool:
        return self.remaining < 0

    @property
    def overspend(self) -> Decimal:
        """How far past the limit, as a positive number. Zero if within it."""
        return -self.remaining if self.is_overspent else Decimal("0.00")


#: Subscription statuses, mirroring the server's enum. Plain strings, for the
#: same reason budget statuses are.
ACTIVE = "active"
PAUSED = "paused"
CANCELLED = "cancelled"

#: How each billing cycle reads in the interface.
CYCLE_LABELS = {
    "weekly": "Weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "yearly": "Yearly",
}


@dataclass(frozen=True)
class Subscription:
    """A recurring payment being tracked.

    `category` is optional here, unlike on a transaction: a subscription
    detected from transaction history may not be categorised yet.
    """

    id: int
    name: str
    amount: Decimal
    billing_cycle: str
    status: str
    start_date: date_type
    next_billing_date: date_type
    end_date: date_type | None
    category: Category | None
    payment_method: str | None
    notes: str | None
    monthly_cost: Decimal
    yearly_cost: Decimal
    days_until_renewal: int
    is_due_soon: bool

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Subscription:
        category = payload.get("category")
        end_date = payload.get("end_date")
        return cls(
            id=int(payload["id"]),
            name=payload["name"],
            amount=Decimal(payload["amount"]),
            billing_cycle=payload["billing_cycle"],
            status=payload["status"],
            start_date=date_type.fromisoformat(payload["start_date"]),
            next_billing_date=date_type.fromisoformat(payload["next_billing_date"]),
            end_date=date_type.fromisoformat(end_date) if end_date else None,
            category=Category.from_json(category) if category else None,
            payment_method=payload.get("payment_method"),
            notes=payload.get("notes"),
            monthly_cost=Decimal(payload["monthly_cost"]),
            yearly_cost=Decimal(payload["yearly_cost"]),
            days_until_renewal=int(payload["days_until_renewal"]),
            is_due_soon=bool(payload["is_due_soon"]),
        )

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE

    @property
    def is_overdue(self) -> bool:
        """Active, and its renewal date has already passed."""
        return self.is_active and self.days_until_renewal < 0

    @property
    def cycle_label(self) -> str:
        return CYCLE_LABELS.get(self.billing_cycle, self.billing_cycle.title())


@dataclass(frozen=True)
class SubscriptionSummary:
    """What the user is committed to, across active subscriptions."""

    active_count: int
    paused_count: int
    cancelled_count: int
    monthly_total: Decimal
    yearly_total: Decimal
    next_renewal: Subscription | None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> SubscriptionSummary:
        upcoming = payload.get("next_renewal")
        return cls(
            active_count=int(payload["active_count"]),
            paused_count=int(payload["paused_count"]),
            cancelled_count=int(payload["cancelled_count"]),
            monthly_total=Decimal(payload["monthly_total"]),
            yearly_total=Decimal(payload["yearly_total"]),
            next_renewal=Subscription.from_json(upcoming) if upcoming else None,
        )

    @classmethod
    def empty(cls) -> SubscriptionSummary:
        return cls(0, 0, 0, Decimal("0.00"), Decimal("0.00"), None)


@dataclass(frozen=True)
class PeriodTotals:
    """Income, expense and what was kept over a period."""

    income: Decimal
    expense: Decimal
    net: Decimal
    transaction_count: int

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> PeriodTotals:
        return cls(
            income=Decimal(payload["income"]),
            expense=Decimal(payload["expense"]),
            net=Decimal(payload["net"]),
            transaction_count=int(payload["transaction_count"]),
        )

    @property
    def overspent(self) -> bool:
        return self.net < 0


@dataclass(frozen=True)
class CategoryShare:
    """One row of the spending breakdown."""

    category_id: int | None
    name: str
    color: str | None
    total: Decimal
    percentage: Decimal

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> CategoryShare:
        return cls(
            category_id=payload.get("category_id"),
            name=payload["name"],
            color=payload.get("color"),
            total=Decimal(payload["total"]),
            percentage=Decimal(payload["percentage"]),
        )

    @property
    def is_folded_tail(self) -> bool:
        """The "Other categories" row, which is a sum rather than a category."""
        return self.category_id is None


@dataclass(frozen=True)
class BudgetHealth:
    """How many budgets sit in each state."""

    total: int
    on_track: int
    warning: int
    exceeded: int
    needs_attention: int

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> BudgetHealth:
        return cls(
            total=int(payload["total"]),
            on_track=int(payload["on_track"]),
            warning=int(payload["warning"]),
            exceeded=int(payload["exceeded"]),
            needs_attention=int(payload["needs_attention"]),
        )


#: Insight severities, mirroring the server's enum. Plain strings, as with
#: budget and subscription statuses: the client colours what it is told and
#: decides no thresholds of its own.
CRITICAL = "critical"
SEVERITY_WARNING = "warning"
INFO = "info"
GOOD = "good"

#: Display order, matching the server's. Held here only so a client-side sort
#: cannot disagree with the order things arrived in.
SEVERITY_ORDER = {CRITICAL: 0, SEVERITY_WARNING: 1, INFO: 2, GOOD: 3}


@dataclass(frozen=True)
class Insight:
    """One finding, and the explanation for it."""

    code: str
    severity: str
    title: str
    detail: str
    category_id: int | None = None
    subscription_id: int | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Insight:
        return cls(
            code=payload["code"],
            severity=payload["severity"],
            title=payload["title"],
            detail=payload["detail"],
            category_id=payload.get("category_id"),
            subscription_id=payload.get("subscription_id"),
        )

    @property
    def is_bad_news(self) -> bool:
        return self.severity in (CRITICAL, SEVERITY_WARNING)


@dataclass(frozen=True)
class Insights:
    """Everything the rules found for a period."""

    period_start: date_type
    period_end: date_type
    items: tuple[Insight, ...]
    needs_attention: int
    counts: dict[str, int]

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Insights:
        return cls(
            period_start=date_type.fromisoformat(payload["period_start"]),
            period_end=date_type.fromisoformat(payload["period_end"]),
            items=tuple(Insight.from_json(row) for row in payload["insights"]),
            needs_attention=int(payload["needs_attention"]),
            counts={key: int(value) for key, value in payload["counts"].items()},
        )

    @classmethod
    def empty(cls) -> Insights:
        today = date_type.today()
        return cls(today, today, (), 0, {})


@dataclass(frozen=True)
class Dashboard:
    """Everything the first screen needs, from one request."""

    period_start: date_type
    period_end: date_type
    totals: PeriodTotals
    spending: tuple[CategoryShare, ...]
    recent: tuple[Transaction, ...]
    budgets: BudgetHealth
    subscriptions: SubscriptionSummary
    #: The same findings the insights screen shows. Rendered here, not
    #: recomputed — the dashboard decides nothing about what matters.
    insights: tuple[Insight, ...]
    needs_attention: int

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Dashboard:
        return cls(
            period_start=date_type.fromisoformat(payload["period_start"]),
            period_end=date_type.fromisoformat(payload["period_end"]),
            totals=PeriodTotals.from_json(payload["totals"]),
            spending=tuple(CategoryShare.from_json(row) for row in payload["spending"]),
            recent=tuple(Transaction.from_json(row) for row in payload["recent"]),
            budgets=BudgetHealth.from_json(payload["budgets"]),
            subscriptions=SubscriptionSummary.from_json(payload["subscriptions"]),
            insights=tuple(Insight.from_json(row) for row in payload["insights"]),
            needs_attention=int(payload["needs_attention"]),
        )

    @classmethod
    def empty(cls) -> Dashboard:
        """The shape to show before anything has loaded, or after a failure."""
        today = date_type.today()
        return cls(
            period_start=today,
            period_end=today,
            totals=PeriodTotals(ZERO, ZERO, ZERO, 0),
            spending=(),
            recent=(),
            budgets=BudgetHealth(0, 0, 0, 0, 0),
            subscriptions=SubscriptionSummary.empty(),
            insights=(),
            needs_attention=0,
        )


@dataclass(frozen=True)
class MonthTotals:
    """One month of the trend."""

    year: int
    month: int
    first_day: date_type
    income: Decimal
    expense: Decimal
    net: Decimal

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> MonthTotals:
        return cls(
            year=int(payload["year"]),
            month=int(payload["month"]),
            first_day=date_type.fromisoformat(payload["first_day"]),
            income=Decimal(payload["income"]),
            expense=Decimal(payload["expense"]),
            net=Decimal(payload["net"]),
        )

    @property
    def label(self) -> str:
        """Short month name; the year is added only where it changes."""
        return f"{self.first_day:%b}"


@dataclass(frozen=True)
class Trend:
    """Income and expense per month, empty months included as zeroes."""

    months: tuple[MonthTotals, ...]
    has_activity: bool

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Trend:
        return cls(
            months=tuple(MonthTotals.from_json(row) for row in payload["months"]),
            has_activity=bool(payload["has_activity"]),
        )

    @classmethod
    def empty(cls) -> Trend:
        return cls(months=(), has_activity=False)


@dataclass(frozen=True)
class Change:
    """A figure against its previous value."""

    current: Decimal
    previous: Decimal
    difference: Decimal
    #: None when the previous value was zero — a start, not a percentage.
    percentage: Decimal | None
    is_new: bool

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Change:
        percentage = payload.get("percentage")
        return cls(
            current=Decimal(payload["current"]),
            previous=Decimal(payload["previous"]),
            difference=Decimal(payload["difference"]),
            percentage=Decimal(percentage) if percentage is not None else None,
            is_new=bool(payload["is_new"]),
        )

    @property
    def rose(self) -> bool:
        return self.difference > 0

    @property
    def fell(self) -> bool:
        return self.difference < 0

    @property
    def unchanged(self) -> bool:
        return self.difference == 0


@dataclass(frozen=True)
class CategoryChange:
    """One category's spend, this period against last."""

    category_id: int | None
    name: str
    color: str | None
    change: Change

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> CategoryChange:
        return cls(
            category_id=payload.get("category_id"),
            name=payload["name"],
            color=payload.get("color"),
            change=Change.from_json(payload["change"]),
        )


@dataclass(frozen=True)
class Comparison:
    """Two periods, side by side."""

    period_start: date_type
    period_end: date_type
    previous_start: date_type
    previous_end: date_type
    income: Change
    expense: Change
    net: Change
    categories: tuple[CategoryChange, ...]

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Comparison:
        return cls(
            period_start=date_type.fromisoformat(payload["period_start"]),
            period_end=date_type.fromisoformat(payload["period_end"]),
            previous_start=date_type.fromisoformat(payload["previous_start"]),
            previous_end=date_type.fromisoformat(payload["previous_end"]),
            income=Change.from_json(payload["income"]),
            expense=Change.from_json(payload["expense"]),
            net=Change.from_json(payload["net"]),
            categories=tuple(CategoryChange.from_json(row) for row in payload["categories"]),
        )

    @classmethod
    def empty(cls) -> Comparison:
        today = date_type.today()
        nothing = Change(ZERO, ZERO, ZERO, None, False)
        return cls(today, today, today, today, nothing, nothing, nothing, ())
