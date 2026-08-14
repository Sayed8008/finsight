"""Typed data transferred between the client and the API.

The interface works with these rather than raw dictionaries, so a renamed or
missing field fails once, here, at the boundary — instead of surfacing as a
`KeyError` inside a widget three screens later.
"""

from __future__ import annotations

from dataclasses import dataclass
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
