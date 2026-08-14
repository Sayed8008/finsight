"""Transaction category model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import CategoryType

if TYPE_CHECKING:
    from app.models.budget import Budget
    from app.models.subscription import Subscription
    from app.models.transaction import Transaction
    from app.models.user import User


class Category(Base, TimestampMixin):
    """A grouping for transactions, such as Food or Salary.

    Categories are per-user: each account gets its own copy of the defaults
    when it is created. Sharing one global set between users would mean every
    query needed `WHERE user_id = ? OR user_id IS NULL`, and renaming a
    category would change it for everyone (ADR-006).
    """

    __tablename__ = "categories"
    __table_args__ = (
        # The same name may exist once as income and once as expense
        # ("Other"), but not twice within one type for one user.
        UniqueConstraint("user_id", "category_type", "name", name="user_type_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)

    category_type: Mapped[CategoryType] = mapped_column(
        Enum(CategoryType, values_callable=lambda enum: [member.value for member in enum]),
        nullable=False,
    )

    # Hex colour such as "#1a56c4", used for chart series and category chips.
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Categories are deactivated rather than deleted, because deleting one
    # would orphan every transaction ever filed under it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="categories")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="category")
    budgets: Mapped[list[Budget]] = relationship(back_populates="category")
    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.name!r} type={self.category_type}>"
