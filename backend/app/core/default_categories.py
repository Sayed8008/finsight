"""The category set every new account starts with.

Each user receives their own copy of these rows at registration (ADR-006), so
they can be renamed, recoloured or deactivated without affecting anyone else.
This list is only a starting point — nothing in the application treats these
names as fixed.

Colours are chosen to stay distinguishable when used as chart series: no two
adjacent hues, and none so pale that a thin line or small slice disappears.
"""

from __future__ import annotations

from typing import NamedTuple

from app.models.enums import CategoryType


class DefaultCategory(NamedTuple):
    name: str
    category_type: CategoryType
    color: str


DEFAULT_CATEGORIES: tuple[DefaultCategory, ...] = (
    # Income
    DefaultCategory("Salary", CategoryType.INCOME, "#1a7f4b"),
    DefaultCategory("Freelance", CategoryType.INCOME, "#2f9e6b"),
    DefaultCategory("Scholarship", CategoryType.INCOME, "#4bb98a"),
    DefaultCategory("Gift", CategoryType.INCOME, "#7fd0ab"),
    DefaultCategory("Other Income", CategoryType.INCOME, "#a8dfc6"),
    # Expenses
    DefaultCategory("Food", CategoryType.EXPENSE, "#c4472f"),
    DefaultCategory("Transport", CategoryType.EXPENSE, "#d9782e"),
    DefaultCategory("Education", CategoryType.EXPENSE, "#1a56c4"),
    DefaultCategory("Shopping", CategoryType.EXPENSE, "#8a4fbd"),
    DefaultCategory("Entertainment", CategoryType.EXPENSE, "#c43f8a"),
    DefaultCategory("Bills", CategoryType.EXPENSE, "#4a5259"),
    DefaultCategory("Healthcare", CategoryType.EXPENSE, "#2b9ab5"),
    DefaultCategory("Rent", CategoryType.EXPENSE, "#7a6a4f"),
    DefaultCategory("Subscriptions", CategoryType.EXPENSE, "#5b6ee0"),
    DefaultCategory("Other", CategoryType.EXPENSE, "#8b939c"),
)
