"""User account model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.budget import Budget
    from app.models.category import Category
    from app.models.subscription import Subscription
    from app.models.transaction import Transaction


class User(Base, TimestampMixin):
    """A person with an account.

    Every other table in the application hangs off this one. That single
    invariant — every row belongs to exactly one user — is what makes the
    "users may only read their own data" rule enforceable in one place rather
    than endpoint by endpoint.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # Argon2id hashes are ~95 characters; 255 leaves room for future
    # parameter changes without another migration.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # ISO 4217 code. Single-currency for now, but recording it means adding
    # multi-currency support later does not require backfilling this column.
    currency_code: Mapped[str] = mapped_column(String(3), default="BDT", nullable=False)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda enum: [member.value for member in enum]),
        default=UserRole.USER,
        nullable=False,
    )

    # Deactivate rather than delete: removing a user would destroy their
    # financial history, which is rarely what anyone actually wants.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # `cascade="all, delete-orphan"` means deleting a user removes their data
    # too, rather than leaving rows pointing at a user that no longer exists.
    categories: Mapped[list[Category]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    budgets: Mapped[list[Budget]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
