"""Request and response models for categories.

Note what `CategoryUpdate` does *not* contain: `category_type`. A category's
type is immutable, because flipping an expense category to income would
silently invalidate every transaction already filed under it. Changing type
means creating a new category and moving the transactions across — a
deliberate act, not a field edit.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import CategoryType

NAME_MAX_LENGTH = 80
ICON_MAX_LENGTH = 40

# Six-digit hex only. Three-digit shorthand would also fit the VARCHAR(7)
# column, but accepting both means every consumer has to handle both.
HEX_COLOUR_PATTERN = r"^#[0-9a-fA-F]{6}$"


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Name cannot be blank.")
    return cleaned


class CategoryCreate(BaseModel):
    """Body of POST /categories."""

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    category_type: CategoryType
    color: str | None = Field(default=None, pattern=HEX_COLOUR_PATTERN)
    icon: str | None = Field(default=None, max_length=ICON_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _normalise_name(cls, value: str) -> str:
        # Collapses internal runs of whitespace as well as trimming the ends,
        # so "Food  Delivery" and "Food Delivery" cannot both exist.
        return _clean_name(value)

    @field_validator("color")
    @classmethod
    def _lowercase_colour(cls, value: str | None) -> str | None:
        return value.lower() if value else value


class CategoryUpdate(BaseModel):
    """Body of PATCH /categories/{id}.

    Every field is optional, and *absent* means "leave this alone" — which is
    what makes PATCH different from PUT. An explicit `null` for `color` or
    `icon` clears it. The service tells the two apart with
    `model_dump(exclude_unset=True)`; without that, omitting a field would
    overwrite it with `None`.
    """

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    color: str | None = Field(default=None, pattern=HEX_COLOUR_PATTERN)
    icon: str | None = Field(default=None, max_length=ICON_MAX_LENGTH)
    # Deactivating is how a category is retired; there is no DELETE (ADR-020).
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _normalise_name(cls, value: str | None) -> str | None:
        return _clean_name(value) if value is not None else None

    @field_validator("color")
    @classmethod
    def _lowercase_colour(cls, value: str | None) -> str | None:
        return value.lower() if value else value


class CategoryResponse(BaseModel):
    """A category as the API describes it.

    `user_id` is absent deliberately: the caller can only ever see their own
    categories, so telling them which user id they are is noise at best.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category_type: CategoryType
    color: str | None
    icon: str | None
    is_active: bool
