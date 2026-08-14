"""Tests for the ORM models and the constraints they declare.

These verify that the database actually enforces the rules the models claim,
rather than trusting that the declarations were written correctly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

# MySQL reports the two kinds of violation with different exception classes:
#
#   UNIQUE / FOREIGN KEY  -> IntegrityError
#   CHECK                 -> OperationalError (error 3819)
#
# Both derive from DatabaseError, which is what the CHECK-constraint tests
# below assert on. Worth knowing, because expecting IntegrityError everywhere
# produces a failing test against a schema that is in fact working correctly.
from app.models import (
    BillingCycle,
    Budget,
    Category,
    CategoryType,
    Subscription,
    SubscriptionStatus,
    Transaction,
    TransactionType,
    User,
    UserRole,
)


def make_user(db_session: Session, email: str = "sayed@example.test") -> User:
    user = User(email=email, password_hash="not-a-real-hash", full_name="Test User")
    db_session.add(user)
    db_session.flush()
    return user


def make_category(
    db_session: Session,
    user: User,
    name: str = "Food",
    category_type: CategoryType = CategoryType.EXPENSE,
) -> Category:
    category = Category(user_id=user.id, name=name, category_type=category_type)
    db_session.add(category)
    db_session.flush()
    return category


# ─── User ─────────────────────────────────────────────────────────────────


def test_user_defaults(db_session: Session) -> None:
    user = make_user(db_session)

    assert user.id is not None
    assert user.role is UserRole.USER
    assert user.is_active is True
    assert user.currency_code == "BDT"
    assert user.created_at is not None
    assert user.updated_at is not None


def test_email_must_be_unique(db_session: Session) -> None:
    make_user(db_session, "duplicate@example.test")

    with pytest.raises(IntegrityError):
        make_user(db_session, "duplicate@example.test")


# ─── Category ─────────────────────────────────────────────────────────────


def test_category_name_unique_per_user_and_type(db_session: Session) -> None:
    user = make_user(db_session)
    make_category(db_session, user, "Food", CategoryType.EXPENSE)

    with pytest.raises(IntegrityError):
        make_category(db_session, user, "Food", CategoryType.EXPENSE)


def test_same_name_allowed_across_types(db_session: Session) -> None:
    """ "Other" is a reasonable name for both an income and an expense group."""
    user = make_user(db_session)
    make_category(db_session, user, "Other", CategoryType.EXPENSE)
    make_category(db_session, user, "Other", CategoryType.INCOME)

    assert len(user.categories) == 2


def test_same_name_allowed_for_different_users(db_session: Session) -> None:
    first = make_user(db_session, "one@example.test")
    second = make_user(db_session, "two@example.test")

    make_category(db_session, first, "Food")
    make_category(db_session, second, "Food")

    assert len(first.categories) == 1
    assert len(second.categories) == 1


# ─── Transaction ──────────────────────────────────────────────────────────


def test_transaction_stores_exact_decimal_amount(db_session: Session) -> None:
    """Money must survive a round-trip unchanged — no floating-point drift."""
    user = make_user(db_session)
    category = make_category(db_session, user)

    db_session.add(
        Transaction(
            user_id=user.id,
            category_id=category.id,
            amount=Decimal("1234.56"),
            transaction_type=TransactionType.EXPENSE,
            date=date(2026, 8, 15),
        )
    )
    db_session.flush()
    db_session.expire_all()

    stored = db_session.query(Transaction).one()
    assert stored.amount == Decimal("1234.56")
    assert isinstance(stored.amount, Decimal)


def test_repeated_decimal_amounts_sum_exactly(db_session: Session) -> None:
    """Ten payments of 0.10 must total exactly 1.00, not 0.9999999999999999."""
    user = make_user(db_session)
    category = make_category(db_session, user)

    for _ in range(10):
        db_session.add(
            Transaction(
                user_id=user.id,
                category_id=category.id,
                amount=Decimal("0.10"),
                transaction_type=TransactionType.EXPENSE,
                date=date(2026, 8, 15),
            )
        )
    db_session.flush()

    total = sum(t.amount for t in db_session.query(Transaction).all())
    assert total == Decimal("1.00")


def test_transaction_amount_must_be_positive(db_session: Session) -> None:
    """Direction is carried by transaction_type, so amounts are never signed."""
    user = make_user(db_session)
    category = make_category(db_session, user)

    db_session.add(
        Transaction(
            user_id=user.id,
            category_id=category.id,
            amount=Decimal("-50.00"),
            transaction_type=TransactionType.EXPENSE,
            date=date(2026, 8, 15),
        )
    )

    with pytest.raises(DatabaseError):
        db_session.flush()


# ─── Budget ───────────────────────────────────────────────────────────────


def test_budget_period_must_be_ordered(db_session: Session) -> None:
    user = make_user(db_session)
    category = make_category(db_session, user)

    db_session.add(
        Budget(
            user_id=user.id,
            category_id=category.id,
            amount=Decimal("10000.00"),
            period_start=date(2026, 8, 31),
            period_end=date(2026, 8, 1),
        )
    )

    with pytest.raises(DatabaseError):
        db_session.flush()


def test_one_budget_per_category_and_period(db_session: Session) -> None:
    """Two budgets for the same category and period make "remaining" ambiguous."""
    user = make_user(db_session)
    category = make_category(db_session, user)

    for _ in range(2):
        db_session.add(
            Budget(
                user_id=user.id,
                category_id=category.id,
                amount=Decimal("10000.00"),
                period_start=date(2026, 8, 1),
                period_end=date(2026, 8, 31),
            )
        )

    with pytest.raises(IntegrityError):
        db_session.flush()


# ─── Subscription ─────────────────────────────────────────────────────────


def test_subscription_defaults_to_active(db_session: Session) -> None:
    user = make_user(db_session)

    subscription = Subscription(
        user_id=user.id,
        name="Netflix",
        amount=Decimal("650.00"),
        billing_cycle=BillingCycle.MONTHLY,
        start_date=date(2026, 1, 4),
        next_billing_date=date(2026, 9, 4),
    )
    db_session.add(subscription)
    db_session.flush()

    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.category_id is None


def test_subscription_end_date_cannot_precede_start(db_session: Session) -> None:
    user = make_user(db_session)

    db_session.add(
        Subscription(
            user_id=user.id,
            name="Spotify",
            amount=Decimal("219.00"),
            billing_cycle=BillingCycle.MONTHLY,
            start_date=date(2026, 6, 1),
            next_billing_date=date(2026, 9, 1),
            end_date=date(2026, 5, 1),
        )
    )

    with pytest.raises(DatabaseError):
        db_session.flush()


# ─── Relationships ────────────────────────────────────────────────────────


def test_deleting_a_user_removes_their_data(db_session: Session) -> None:
    user = make_user(db_session)
    category = make_category(db_session, user)
    db_session.add(
        Transaction(
            user_id=user.id,
            category_id=category.id,
            amount=Decimal("100.00"),
            transaction_type=TransactionType.EXPENSE,
            date=date(2026, 8, 15),
        )
    )
    db_session.flush()

    db_session.delete(user)
    db_session.flush()

    assert db_session.query(Transaction).count() == 0
    assert db_session.query(Category).count() == 0
