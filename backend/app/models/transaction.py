"""Transaction model — a single income or expense entry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import TransactionType

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import User


class Transaction(Base, TimestampMixin):
    """One movement of money, in or out."""

    __tablename__ = "transactions"
    __table_args__ = (
        # Amounts carry no sign; `transaction_type` states the direction.
        CheckConstraint("amount > 0", name="amount_positive"),
        # Serves the paginated list, date-range filters and monthly
        # aggregates — together the large majority of queries against this
        # table. One composite index covers all three because they all lead
        # with user_id.
        Index("ix_transactions_user_date", "user_id", "date"),
        Index("ix_transactions_user_category", "user_id", "category_id"),
        Index("ix_transactions_user_type", "user_id", "transaction_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # DECIMAL, never float: binary floating point cannot represent decimal
    # fractions exactly, and the error accumulates across sums (ADR-003).
    # 14 digits with 2 decimal places allows up to 999,999,999,999.99.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, values_callable=lambda enum: [member.value for member in enum]),
        nullable=False,
    )

    # RESTRICT, not CASCADE: deleting a category must not silently delete the
    # transactions filed under it. Categories are deactivated instead.
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )

    # A calendar date, not a timestamp — "spent on the 4th" has no meaningful
    # time-of-day, and using a date avoids timezone questions entirely.
    date: Mapped[date] = mapped_column(Date, nullable=False)

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # A plain string for now. It becomes a table only if it earns one — see
    # the deferred tables in docs/DECISIONS.md.
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    user: Mapped[User] = relationship(back_populates="transactions")
    category: Mapped[Category] = relationship(back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} {self.transaction_type} {self.amount} on {self.date}>"
