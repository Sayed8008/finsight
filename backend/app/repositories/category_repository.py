"""Data access for categories.

Every method takes a `user_id` and puts it in the WHERE clause. That is not
defensive duplication of the API's authentication — it is the point at which
"users may only reach their own data" becomes true. A method that could be
called without a `user_id` is a method that can leak, so none is offered.

Repositories do not commit; the service owns the transaction boundary.
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.enums import CategoryType


class CategoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(
        self,
        user_id: int,
        *,
        category_type: CategoryType | None = None,
        include_inactive: bool = False,
    ) -> list[Category]:
        """Categories belonging to one user.

        Ordered by type then name so the client can render grouped lists
        without sorting them again, and so the order is stable between calls —
        an unordered SELECT may return rows differently on any given day.

        Worth knowing: MySQL sorts an ENUM column by the order its values were
        *declared*, not alphabetically. `CategoryType` declares INCOME first,
        so income categories come back first — which is the order wanted for
        display, but is a coincidence rather than a design. Renaming or
        reordering the enum members would change this query's output.
        """
        statement: Select[tuple[Category]] = select(Category).where(Category.user_id == user_id)

        if category_type is not None:
            statement = statement.where(Category.category_type == category_type)
        if not include_inactive:
            statement = statement.where(Category.is_active.is_(True))

        statement = statement.order_by(Category.category_type, Category.name)
        return list(self._session.execute(statement).scalars())

    def get_for_user(self, category_id: int, user_id: int) -> Category | None:
        """One category, or None if it does not exist *or* is not this user's.

        The two cases are deliberately indistinguishable to the caller, so the
        API can answer 404 for both. Answering 403 for someone else's row
        would confirm that the row exists.
        """
        statement = select(Category).where(
            Category.id == category_id,
            Category.user_id == user_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def name_exists(
        self,
        user_id: int,
        category_type: CategoryType,
        name: str,
        *,
        exclude_id: int | None = None,
    ) -> bool:
        """Whether this user already has a category of this type and name.

        Matched case-insensitively with an explicit LOWER() on both sides
        rather than relying on the column's collation, so the check does not
        change meaning if the schema is ever created with a case-sensitive one.
        The table is a few dozen rows per user, so scanning it costs nothing.

        `exclude_id` is for renaming: a category is allowed to keep its own
        name.
        """
        statement = select(Category.id).where(
            Category.user_id == user_id,
            Category.category_type == category_type,
            func.lower(Category.name) == name.lower(),
        )
        if exclude_id is not None:
            statement = statement.where(Category.id != exclude_id)

        return self._session.execute(statement).first() is not None

    def add(self, category: Category) -> Category:
        """Stage a new category and assign its primary key.

        `flush` sends the INSERT so `category.id` is available, but leaves the
        surrounding transaction open for the service to commit.
        """
        self._session.add(category)
        self._session.flush()
        return category
