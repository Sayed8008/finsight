"""Enumerations used by the database models.

These are `StrEnum`, so each member *is* a string: `TransactionType.INCOME ==
"income"` is true. That means they serialise straight to JSON and compare
cleanly against values coming from the API, without conversion code.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Account role.

    Only USER is used at present. The column exists from the start because
    adding authorisation logic later is easy, but retrofitting it onto
    endpoints that never considered roles is not.
    """

    USER = "user"
    ADMIN = "admin"


class CategoryType(StrEnum):
    """Whether a category groups money coming in or going out."""

    INCOME = "income"
    EXPENSE = "expense"


class TransactionType(StrEnum):
    """Direction of a transaction.

    Amounts are always stored positive; this column carries the direction.
    Storing signed amounts *and* a type is a redundancy that eventually
    disagrees with itself.
    """

    INCOME = "income"
    EXPENSE = "expense"


class BillingCycle(StrEnum):
    """How often a subscription is charged."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class SubscriptionStatus(StrEnum):
    """Whether a subscription is currently being paid for.

    PAUSED is distinct from CANCELLED: a paused subscription is expected to
    resume, so it stays out of current cost totals but remains visible.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
