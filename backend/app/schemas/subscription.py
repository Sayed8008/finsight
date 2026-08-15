"""Request and response models for subscriptions.

`category` is optional throughout, unlike on a transaction. A subscription
detected from transaction history (Phase 9.5) may not have been categorised
yet, so the column is nullable and every consumer has to cope with that.
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.money import MoneyOut, PositiveMoney
from app.models.enums import BillingCycle, SubscriptionStatus
from app.schemas.category import CategoryResponse

NAME_MAX_LENGTH = 120
PAYMENT_METHOD_MAX_LENGTH = 50
NOTES_MAX_LENGTH = 2000


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Name cannot be blank.")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


class SubscriptionCreate(BaseModel):
    """Body of POST /subscriptions.

    `next_billing_date` is deliberately absent: it is derived from
    `start_date` and the cycle. Accepting both would let a client send a pair
    that disagree, and there is no way to tell which one was meant.
    """

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    amount: PositiveMoney
    billing_cycle: BillingCycle
    start_date: date_type
    category_id: int | None = Field(default=None, gt=0)
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    end_date: date_type | None = None
    payment_method: str | None = Field(default=None, max_length=PAYMENT_METHOD_MAX_LENGTH)
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _normalise_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("payment_method", "notes")
    @classmethod
    def _normalise_optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @model_validator(mode="after")
    def _check_dates(self) -> SubscriptionCreate:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("The end date cannot be before the start date.")
        return self


class SubscriptionUpdate(BaseModel):
    """Body of PATCH /subscriptions/{id}.

    `next_billing_date` is absent here too. It moves either because the anchor
    or cycle changed — in which case the service recomputes it — or because a
    charge was taken, which is what `POST /{id}/renew` is for.
    """

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    amount: PositiveMoney | None = None
    billing_cycle: BillingCycle | None = None
    start_date: date_type | None = None
    category_id: int | None = Field(default=None, gt=0)
    status: SubscriptionStatus | None = None
    end_date: date_type | None = None
    payment_method: str | None = Field(default=None, max_length=PAYMENT_METHOD_MAX_LENGTH)
    notes: str | None = Field(default=None, max_length=NOTES_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _normalise_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None

    @field_validator("payment_method", "notes")
    @classmethod
    def _normalise_optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @model_validator(mode="after")
    def _check_dates(self) -> SubscriptionUpdate:
        """Only checkable when both dates are sent; otherwise the service does it."""
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("The end date cannot be before the start date.")
        return self


class SubscriptionResponse(BaseModel):
    """A subscription with its derived costs and renewal timing."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    amount: MoneyOut
    billing_cycle: BillingCycle
    status: SubscriptionStatus
    start_date: date_type
    next_billing_date: date_type
    end_date: date_type | None
    #: None until the subscription is categorised (Phase 9.5).
    category: CategoryResponse | None
    payment_method: str | None
    notes: str | None

    # ─── Computed per request, stored nowhere (ADR-015) ───────────────────
    monthly_cost: MoneyOut
    yearly_cost: MoneyOut
    #: Negative once the renewal date has passed, which happens to an active
    #: subscription nobody has marked as renewed.
    days_until_renewal: int
    #: Whether the next charge falls inside the "due soon" window.
    is_due_soon: bool


class SubscriptionSummary(BaseModel):
    """What the user is committed to, across every active subscription."""

    active_count: int
    paused_count: int
    cancelled_count: int
    monthly_total: MoneyOut
    yearly_total: MoneyOut
    #: Paused and cancelled subscriptions are excluded from the totals: a
    #: paused subscription is not being charged, so counting it would overstate
    #: what the user actually pays.
    next_renewal: SubscriptionResponse | None
