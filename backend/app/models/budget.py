"""Budget model — a spending limit for one category over one period."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import User


class Budget(Base, TimestampMixin):
    """A spending limit for one category between two dates.

    Note what is *not* stored here: amount spent, amount remaining, percentage
    used and status are all computed on read. Storing them would create a
    cache that goes stale the moment a transaction is added, edited or
    deleted (ADR-003).

    The period is an explicit date range rather than a month/year pair. That
    costs nothing now and means weekly or quarterly budgets later become a
    data change instead of a schema migration.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("period_end >= period_start", name="period_ordered"),
        # One budget per category per period. Two overlapping budgets for the
        # same category would make "how much is left?" ambiguous.
        UniqueConstraint(
            "user_id", "category_id", "period_start", "period_end", name="user_category_period"
        ),
        Index("ix_budgets_user_period", "user_id", "period_start", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # Inclusive on both ends: a monthly budget runs 1st to last day.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped[User] = relationship(back_populates="budgets")
    category: Mapped[Category] = relationship(back_populates="budgets")

    def __repr__(self) -> str:
        return (
            f"<Budget id={self.id} category={self.category_id} "
            f"{self.amount} {self.period_start}..{self.period_end}>"
        )
