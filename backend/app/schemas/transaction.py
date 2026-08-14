"""Request and response models for transactions.

Amounts use the annotated types from `app/core/money.py`: strictly positive on
the way in, a JSON *string* on the way out (ADR-003). A transaction's direction
is carried by `transaction_type`, never by the sign of the amount — storing
both a signed amount and a type is a redundancy that eventually disagrees with
itself.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.money import MoneyOut, PositiveMoney
from app.models.enums import CategoryType, TransactionType

DESCRIPTION_MAX_LENGTH = 255
PAYMENT_METHOD_MAX_LENGTH = 50


def _clean_optional_text(value: str | None) -> str | None:
    """Trim, collapse internal whitespace, and treat "  " as absent.

    A description of three spaces is not data. Normalising it to `None` at the
    boundary means nothing downstream — search, CSV export, the table — has to
    decide whether a blank string counts as a value.
    """
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


class TransactionCreate(BaseModel):
    """Body of POST /transactions."""

    amount: PositiveMoney
    transaction_type: TransactionType
    category_id: int = Field(gt=0)
    date: date_type
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    payment_method: str | None = Field(default=None, max_length=PAYMENT_METHOD_MAX_LENGTH)

    @field_validator("description", "payment_method")
    @classmethod
    def _normalise_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class TransactionUpdate(BaseModel):
    """Body of PATCH /transactions/{id}.

    Every field optional; absent means "leave it alone". The service applies
    only what was sent (`exclude_unset=True`) and re-checks the type/category
    agreement against the result, because changing either side of that pair can
    break it.
    """

    amount: PositiveMoney | None = None
    transaction_type: TransactionType | None = None
    category_id: int | None = Field(default=None, gt=0)
    date: date_type | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    payment_method: str | None = Field(default=None, max_length=PAYMENT_METHOD_MAX_LENGTH)

    @field_validator("description", "payment_method")
    @classmethod
    def _normalise_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class TransactionCategory(BaseModel):
    """The category of a transaction, embedded in its response.

    Nested rather than referenced by id alone: the table shows a category name
    and colour on every row, and a client that received only `category_id`
    would have to look each one up. The row's category arrives on the same
    query that fetched the row (see `TransactionRepository.list_page`), so
    including it costs nothing.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category_type: CategoryType
    color: str | None


class TransactionResponse(BaseModel):
    """A transaction as the API describes it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: MoneyOut
    transaction_type: TransactionType
    date: date_type
    description: str | None
    payment_method: str | None
    category: TransactionCategory
    created_at: datetime
    updated_at: datetime
