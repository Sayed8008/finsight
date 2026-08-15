"""Category rules.

Three rules live here, and nowhere else:

  * a category name is unique per user *within a type* — "Other" may exist as
    both income and expense, but not twice as an expense;
  * a category's type never changes (see `app/schemas/category.py`);
  * a category is retired by deactivation, never deleted (ADR-020).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.models.category import Category
from app.models.enums import CategoryType
from app.repositories.category_repository import CategoryRepository

logger = logging.getLogger(__name__)


class CategoryNotFound(NotFound):
    message = "That category was not found."


class DuplicateCategoryName(Conflict):
    message = "A category with that name already exists for this type."


class CategoryIsInactive(ValidationFailed):
    """Defined here rather than beside whichever feature first needed it.

    Transactions and budgets both refuse to attach new records to a retired
    category. One definition means one message, and the next feature that needs
    the rule finds it where the other category rules live.
    """

    message = "That category has been deactivated. Restore it, or choose another."


class CategoryService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._categories = CategoryRepository(session)

    def list_categories(
        self,
        user_id: int,
        *,
        category_type: CategoryType | None = None,
        include_inactive: bool = False,
    ) -> list[Category]:
        return self._categories.list_for_user(
            user_id,
            category_type=category_type,
            include_inactive=include_inactive,
        )

    def get(self, user_id: int, category_id: int) -> Category:
        """One of this user's categories, or `CategoryNotFound`.

        Also the guard other services use before attaching anything to a
        category. Answering 404 for "belongs to someone else" as well as for
        "does not exist" is what stops a transaction or budget endpoint being
        used to discover which categories another account has.
        """
        category = self._categories.get_for_user(category_id, user_id)
        if category is None:
            raise CategoryNotFound
        return category

    @staticmethod
    def require_active(category: Category) -> None:
        """Refuse to attach anything new to a retired category."""
        if not category.is_active:
            raise CategoryIsInactive

    def create(
        self,
        user_id: int,
        *,
        name: str,
        category_type: CategoryType,
        color: str | None = None,
        icon: str | None = None,
    ) -> Category:
        if self._categories.name_exists(user_id, category_type, name):
            raise DuplicateCategoryName

        category = Category(
            user_id=user_id,
            name=name,
            category_type=category_type,
            color=color,
            icon=icon,
        )

        try:
            self._categories.add(category)
            self._session.commit()
        except IntegrityError:
            # The check above can be passed by two concurrent requests; the
            # unique index is what actually decides. Turning the race into the
            # same error as the ordinary case means the client sees one
            # behaviour rather than two.
            self._session.rollback()
            raise DuplicateCategoryName from None

        logger.info("Created category id=%s for user id=%s", category.id, user_id)
        return category

    def update(self, user_id: int, category_id: int, changes: dict[str, Any]) -> Category:
        """Apply a partial update.

        `changes` holds only the fields the client actually sent — the route
        builds it with `model_dump(exclude_unset=True)`. Iterating over the
        model's full field set instead would overwrite every omitted field
        with `None`, so a request that renamed a category would also erase its
        colour.
        """
        category = self.get(user_id, category_id)

        new_name = changes.get("name")
        if new_name is not None and new_name.lower() != category.name.lower():
            # Type is not editable, so uniqueness is checked within the
            # category's existing type.
            if self._categories.name_exists(
                user_id,
                category.category_type,
                new_name,
                exclude_id=category.id,
            ):
                raise DuplicateCategoryName

        for field, value in changes.items():
            setattr(category, field, value)

        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise DuplicateCategoryName from None

        logger.info(
            "Updated category id=%s for user id=%s (fields: %s)",
            category.id,
            user_id,
            ", ".join(sorted(changes)) or "none",
        )
        return category
