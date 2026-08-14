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
        return self.full_name.split()[0] if self.full_name.strip() else self.email


INCOME = "income"
EXPENSE = "expense"


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
