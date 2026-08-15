"""The category set every new account starts with.

Each user receives their own copy of these rows at registration (ADR-006), so
they can be renamed, recoloured or deactivated without affecting anyone else.
This list is only a starting point — nothing in the application treats these
names as fixed.

**The colours were measured, not chosen by eye** (ADR-026). An earlier version
of this file claimed they were "chosen to stay distinguishable"; running them
through a contrast/colour-vision validator showed three read as grey, one pair
was indistinguishable under protanopia, and another pair was below the
normal-vision floor. The values below pass all five checks as an adjacent-pair
sequence, which is the right test because a colour here always appears as a
swatch beside its own name.

They are **not** a chart series palette. Nine categorical hues cannot be made
safe for every pair at once — measured, not assumed — so charts rank categories
with a single sequential hue and let the axis labels carry identity.
"""

from __future__ import annotations

from typing import NamedTuple

from app.models.enums import CategoryType


class DefaultCategory(NamedTuple):
    name: str
    category_type: CategoryType
    color: str


#: The de-emphasis grey, used only for "Other". Deliberately outside the
#: validated set: it is below the chroma floor, which is exactly right for a
#: catch-all that should recede rather than compete.
OTHER_GREY = "#8b939c"


DEFAULT_CATEGORIES: tuple[DefaultCategory, ...] = (
    # Income — five hues, validated as a sequence.
    DefaultCategory("Salary", CategoryType.INCOME, "#1a7f4b"),
    DefaultCategory("Freelance", CategoryType.INCOME, "#0369a1"),
    DefaultCategory("Scholarship", CategoryType.INCOME, "#a06a1f"),
    DefaultCategory("Gift", CategoryType.INCOME, "#7a5cb8"),
    DefaultCategory("Other Income", CategoryType.INCOME, "#00968a"),
    # Expenses — nine hues, validated as a sequence, plus the grey catch-all.
    DefaultCategory("Food", CategoryType.EXPENSE, "#c0392b"),
    DefaultCategory("Transport", CategoryType.EXPENSE, "#2b9ab5"),
    DefaultCategory("Education", CategoryType.EXPENSE, "#d9782e"),
    DefaultCategory("Shopping", CategoryType.EXPENSE, "#1a56c4"),
    DefaultCategory("Entertainment", CategoryType.EXPENSE, "#c43f8a"),
    DefaultCategory("Bills", CategoryType.EXPENSE, "#4d8b1f"),
    DefaultCategory("Healthcare", CategoryType.EXPENSE, "#8a4fbd"),
    DefaultCategory("Rent", CategoryType.EXPENSE, "#b06a12"),
    DefaultCategory("Subscriptions", CategoryType.EXPENSE, "#e0457b"),
    DefaultCategory("Other", CategoryType.EXPENSE, OTHER_GREY),
)
