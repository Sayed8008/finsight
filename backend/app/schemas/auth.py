"""Request and response models for authentication.

Pydantic schemas define the shape of data crossing the API boundary. They are
kept separate from the ORM models on purpose: a database model has columns the
outside world must never see (`password_hash`), and a request body has fields
that are not columns at all (a plaintext `password`). Conflating the two is
how password hashes end up in JSON responses.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole

# Argon2 has no input length limit, but an unbounded password field would let
# someone submit a megabyte of text and make the server spend real CPU on it.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class RegisterRequest(BaseModel):
    """Body of POST /auth/register."""

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank.")
        return cleaned

    @field_validator("password")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot be only whitespace.")
        return value


class LoginRequest(BaseModel):
    """Body of POST /auth/login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class TokenResponse(BaseModel):
    """Issued on successful registration or login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")


class UserResponse(BaseModel):
    """A user as the API describes them.

    Note what is absent: `password_hash` has no field here, so it cannot be
    serialised by accident.
    """

    # Lets the model be built directly from a SQLAlchemy object with
    # `UserResponse.model_validate(user)`, reading attributes rather than
    # expecting a dict.
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    currency_code: str
    role: UserRole
    is_active: bool
    created_at: datetime
