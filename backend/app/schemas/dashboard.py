"""Response models for the dashboard.

One payload, deliberately. Five endpoints would mean five round trips and five
chances for the screen to show figures taken at five different moments.
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict

from app.core.money import MoneyOut, PercentageOut
from app.schemas.subscription import SubscriptionSummary
from app.schemas.transaction import TransactionResponse


class PeriodTotalsResponse(BaseModel):
    """Income, expense and what was kept."""

    model_config = ConfigDict(from_attributes=True)

    income: MoneyOut
    expense: MoneyOut
    #: Negative when more went out than came in — not clamped, because that is
    #: the month the user most needs to see.
    net: MoneyOut
    transaction_count: int


class CategoryShareResponse(BaseModel):
    """One row of the spending breakdown."""

    model_config = ConfigDict(from_attributes=True)

    #: None for the folded "Other categories" row, which is not a real category.
    category_id: int | None
    name: str
    color: str | None
    total: MoneyOut
    percentage: PercentageOut


class BudgetHealthResponse(BaseModel):
    """How many budgets are in each state, not the budgets themselves."""

    model_config = ConfigDict(from_attributes=True)

    total: int
    on_track: int
    warning: int
    exceeded: int
    needs_attention: int


class DashboardResponse(BaseModel):
    """Everything the first screen needs, from one request."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date_type
    period_end: date_type
    totals: PeriodTotalsResponse
    #: Largest first, with the tail folded into one "Other categories" row.
    spending: list[CategoryShareResponse]
    recent: list[TransactionResponse]
    budgets: BudgetHealthResponse
    subscriptions: SubscriptionSummary
