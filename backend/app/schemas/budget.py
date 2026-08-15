"""Request and response models for budgets.

`BudgetResponse` carries five fields that exist in no table — `spent`,
`remaining`, `percentage_used`, `status` and the two "is it running now"
fields. They are computed per request (ADR-015). Sending them with the budget,
rather than making the client fetch transactions and add them up, is the whole
point of the endpoint: the arithmetic happens once, on the side that has the
data.
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.money import MoneyOut, PercentageOut, PositiveMoney
from app.schemas.category import CategoryResponse
from app.services.budget_utilisation import BudgetStatus


class BudgetCreate(BaseModel):
    """Body of POST /budgets."""

    category_id: int = Field(gt=0)
    amount: PositiveMoney
    period_start: date_type
    period_end: date_type

    @model_validator(mode="after")
    def _check_period_order(self) -> BudgetCreate:
        """Reject a period that ends before it starts.

        The database has the same check. Doing it here as well turns a 500 from
        a constraint violation into a 422 that says what is wrong, and a
        model validator rather than a field one because it needs both fields.
        """
        if self.period_end < self.period_start:
            raise ValueError("The period cannot end before it starts.")
        return self


class BudgetUpdate(BaseModel):
    """Body of PATCH /budgets/{id}.

    `category_id` may be changed — unlike a transaction's type, moving a budget
    to another category is a coherent edit, and the overlap and category rules
    are re-checked against the result.
    """

    category_id: int | None = Field(default=None, gt=0)
    amount: PositiveMoney | None = None
    period_start: date_type | None = None
    period_end: date_type | None = None

    @model_validator(mode="after")
    def _check_period_order(self) -> BudgetUpdate:
        """Only checkable when both ends are supplied.

        A PATCH may move one end only, in which case the pair is validated in
        the service against the budget's existing values — the schema cannot
        see them.
        """
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("The period cannot end before it starts.")
        return self


class BudgetResponse(BaseModel):
    """A budget together with how far through it the user is."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    category: CategoryResponse
    amount: MoneyOut
    period_start: date_type
    period_end: date_type

    # ─── Computed per request, stored nowhere ─────────────────────────────
    spent: MoneyOut
    #: Negative when overspent — by design, since that is the figure that
    #: matters most when it happens.
    remaining: MoneyOut
    percentage_used: PercentageOut
    status: BudgetStatus
    #: Whether today falls inside the period.
    is_current: bool
    #: Days left including today, or None once the period has ended.
    days_remaining: int | None
