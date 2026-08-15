"""Response models for the savings journey."""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, computed_field

from app.core.money import MoneyOut, PercentageOut


class SavingsMonthResponse(BaseModel):
    """One completed month's own performance."""

    model_config = ConfigDict(from_attributes=True)

    year: int
    month: int
    income: MoneyOut
    expense: MoneyOut
    #: Income less expense. Negative for a month that spent more than it
    #: earned, and sent as a negative rather than flipped to a "deficit"
    #: field — the sign is the meaning.
    net: MoneyOut
    #: Share of income kept. Zero for a month with no income at all.
    rate: PercentageOut

    @computed_field  # type: ignore[prop-decorator]
    @property
    def first_day(self) -> date_type:
        """A real date, so a client formats one rather than assembling it."""
        return date_type(self.year, self.month, 1)


class SavingsBadgeResponse(BaseModel):
    """One award, and the figure that earned it."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    detail: str


class SavingsSummaryResponse(BaseModel):
    """The figures shown above the chart."""

    model_config = ConfigDict(from_attributes=True)

    latest: SavingsMonthResponse | None
    previous: SavingsMonthResponse | None
    best: SavingsMonthResponse | None
    #: Latest against previous, in money.
    change: MoneyOut
    #: The same change as a share. Null when the previous month saved nothing
    #: or lost money — a percentage against a non-positive base is a fiction.
    change_percentage: PercentageOut | None
    is_personal_best: bool


class SavingsJourneyResponse(BaseModel):
    """Monthly savings history, with what it earned and what it shows."""

    model_config = ConfigDict(from_attributes=True)

    #: Chronological, oldest first. Only completed months appear.
    months: list[SavingsMonthResponse]
    summary: SavingsSummaryResponse
    #: Earned against the whole history, not the requested window.
    badges: list[SavingsBadgeResponse]
    observations: list[str]
    has_history: bool
