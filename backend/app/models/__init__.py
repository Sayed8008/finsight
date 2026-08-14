"""SQLAlchemy ORM models.

Importing every model here matters for two reasons:

  * SQLAlchemy resolves relationships by class name, so all mapped classes
    must be imported before the first query is issued;
  * Alembic discovers the schema through `Base.metadata`, which is only
    populated by the models that have actually been imported. A model missing
    from this list is silently left out of migrations.
"""

from app.db.base import Base
from app.models.budget import Budget
from app.models.category import Category
from app.models.enums import (
    BillingCycle,
    CategoryType,
    SubscriptionStatus,
    TransactionType,
    UserRole,
)
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.models.user import User

__all__ = [
    "Base",
    "BillingCycle",
    "Budget",
    "Category",
    "CategoryType",
    "Subscription",
    "SubscriptionStatus",
    "Transaction",
    "TransactionType",
    "User",
    "UserRole",
]
