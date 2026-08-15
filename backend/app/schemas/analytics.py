"""Response models for analytics."""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict

from app.core.money import MoneyOut, PercentageOut


class MonthTotalsResponse(BaseModel):
    """One month of the trend."""

    model_config = ConfigDict(from_attributes=True)

    year: int
    month: int
    #: The first of the month, so a client has a real date to format and does
    #: not have to assemble one from two integers.
    first_day: date_type
    income: MoneyOut
    expense: MoneyOut
    net: MoneyOut


class TrendResponse(BaseModel):
    """Income and expense per month, with empty months included as zeroes."""

    model_config = ConfigDict(from_attributes=True)

    months: list[MonthTotalsResponse]
    has_activity: bool


class ChangeResponse(BaseModel):
    """A figure against its previous value."""

    model_config = ConfigDict(from_attributes=True)

    current: MoneyOut
    previous: MoneyOut
    difference: MoneyOut
    #: Null when the previous value was zero. Going from nothing to something
    #: is not a percentage increase, and any number here would be a fiction.
    percentage: PercentageOut | None
    is_new: bool


class CategoryChangeResponse(BaseModel):
    """One category's spend, this period against last."""

    model_config = ConfigDict(from_attributes=True)

    category_id: int | None
    name: str
    color: str | None
    change: ChangeResponse


class ComparisonResponse(BaseModel):
    """Two periods side by side, with the difference per category."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date_type
    period_end: date_type
    #: Derived, not supplied: the same length, ending the day before.
    previous_start: date_type
    previous_end: date_type
    income: ChangeResponse
    expense: ChangeResponse
    net: ChangeResponse
    #: Biggest movement first, in either direction, across categories that
    #: appear in *either* period.
    categories: list[CategoryChangeResponse]
