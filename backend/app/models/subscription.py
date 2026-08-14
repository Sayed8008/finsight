"""Subscription model — a recurring payment being tracked."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import BillingCycle, SubscriptionStatus

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.user import User


class Subscription(Base, TimestampMixin):
    """A recurring commitment such as Netflix or a cloud storage plan.

    This is a *record* of a recurring payment, not a mechanism for making one.
    FinSight never contacts a payment provider and never charges anything.

    Monthly and yearly equivalent costs are derived from `amount` and
    `billing_cycle` at read time rather than stored, for the same reason
    budget totals are not stored: they would go stale.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        # Serves the upcoming-renewals query, which asks for active
        # subscriptions ordered by next billing date.
        Index("ix_subscriptions_user_status_billing", "user_id", "status", "next_billing_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Optional: a subscription detected from transaction history may not have
    # been categorised yet.
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    billing_cycle: Mapped[BillingCycle] = mapped_column(
        Enum(BillingCycle, values_callable=lambda enum: [member.value for member in enum]),
        nullable=False,
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(
            SubscriptionStatus,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    next_billing_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="subscriptions")
    category: Mapped[Category | None] = relationship(back_populates="subscriptions")

    def __repr__(self) -> str:
        return (
            f"<Subscription id={self.id} name={self.name!r} "
            f"{self.amount}/{self.billing_cycle} status={self.status}>"
        )
