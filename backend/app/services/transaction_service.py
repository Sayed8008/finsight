"""Transaction rules.

One rule matters more than the rest: **a transaction's type must agree with its
category's type.** An expense filed under "Salary" would corrupt every total
that follows — the dashboard, budget utilisation, the analytics breakdown —
because each of those trusts the pair. Enforced here, on create and on update,
rather than in the interface, because the interface is not the authority
(ADR-019).

The other rules:

  * a category must belong to the caller. Referencing another user's category
    answers 404, the same as asking for it directly, so a transaction cannot be
    used to discover which categories exist elsewhere;
  * a deactivated category accepts no *new* transactions, but a transaction
    already filed under one can still be edited — otherwise deactivating a
    category would freeze its history;
  * deleting a transaction really deletes it. Nothing references a transaction,
    and a mistyped amount should not be permanent. This is the opposite of
    categories (ADR-020), where a delete would orphan rows.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import NotFound, ValidationFailed
from app.models.category import Category
from app.models.enums import CategoryType, TransactionType
from app.models.transaction import Transaction
from app.repositories.category_repository import CategoryRepository
from app.repositories.transaction_repository import (
    DEFAULT_PAGE_SIZE,
    SortDirection,
    SortField,
    TransactionFilters,
    TransactionRepository,
)
from app.services.category_service import CategoryNotFound

logger = logging.getLogger(__name__)

#: Which category type a transaction of each type must be filed under. The
#: enums are separate types with equal members, so this states the mapping
#: rather than relying on the two happening to use the same strings.
REQUIRED_CATEGORY_TYPE: dict[TransactionType, CategoryType] = {
    TransactionType.INCOME: CategoryType.INCOME,
    TransactionType.EXPENSE: CategoryType.EXPENSE,
}


class TransactionNotFound(NotFound):
    message = "That transaction was not found."


class CategoryTypeMismatch(ValidationFailed):
    message = "An expense must use an expense category, and income an income category."


class CategoryIsInactive(ValidationFailed):
    message = "That category has been deactivated. Restore it, or choose another."


class TransactionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._transactions = TransactionRepository(session)
        self._categories = CategoryRepository(session)

    # ─── Reading ──────────────────────────────────────────────────────────

    def list_transactions(
        self,
        user_id: int,
        filters: TransactionFilters | None = None,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        sort_by: SortField = SortField.DATE,
        direction: SortDirection = SortDirection.DESC,
    ) -> tuple[list[Transaction], int]:
        """One page of transactions, and how many matched in total."""
        return self._transactions.list_page(
            user_id,
            filters,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            direction=direction,
        )

    def get(self, user_id: int, transaction_id: int) -> Transaction:
        transaction = self._transactions.get_for_user(transaction_id, user_id)
        if transaction is None:
            raise TransactionNotFound
        return transaction

    def payment_methods(self, user_id: int) -> list[str]:
        return self._transactions.payment_methods_used(user_id)

    # ─── Writing ──────────────────────────────────────────────────────────

    def create(self, user_id: int, data: dict[str, Any]) -> Transaction:
        """Record a transaction.

        `data` is the validated request body. Pydantic has already checked the
        shapes — a positive amount, a real date, a known type — so what is left
        here is the part only the database can answer: does this category
        belong to this user, is it still active, and does its type agree.
        """
        category = self._require_own_category(user_id, data["category_id"])
        self._require_active(category)
        self._require_matching_types(data["transaction_type"], category)

        transaction = Transaction(user_id=user_id, **data)
        self._transactions.add(transaction)
        self._session.commit()

        logger.info(
            "Recorded %s of %s for user id=%s (transaction id=%s)",
            transaction.transaction_type,
            transaction.amount,
            user_id,
            transaction.id,
        )
        return transaction

    def update(self, user_id: int, transaction_id: int, changes: dict[str, Any]) -> Transaction:
        """Apply a partial update.

        The type/category check runs against the *result* of the change, not
        the request: either side of the pair can move, so validating only the
        field that was sent would let `PATCH {"transaction_type": "income"}`
        leave an income transaction sitting in an expense category.
        """
        transaction = self.get(user_id, transaction_id)

        new_category_id = changes.get("category_id", transaction.category_id)
        new_type = changes.get("transaction_type", transaction.transaction_type)

        category = self._require_own_category(user_id, new_category_id)
        if new_category_id != transaction.category_id:
            # Only a *change* of category requires an active one. Checking on
            # every edit would make a transaction whose category was later
            # deactivated impossible to correct.
            self._require_active(category)

        self._require_matching_types(new_type, category)

        for field, value in changes.items():
            setattr(transaction, field, value)

        self._session.commit()
        logger.info(
            "Updated transaction id=%s for user id=%s (fields: %s)",
            transaction.id,
            user_id,
            ", ".join(sorted(changes)) or "none",
        )
        return transaction

    def delete(self, user_id: int, transaction_id: int) -> None:
        """Delete a transaction for real.

        Unlike a category, nothing references a transaction, so there is
        nothing to orphan — and a mistyped entry the user cannot remove is a
        worse outcome than a lost row they chose to lose.
        """
        transaction = self.get(user_id, transaction_id)
        self._transactions.delete(transaction)
        self._session.commit()
        logger.info("Deleted transaction id=%s for user id=%s", transaction_id, user_id)

    # ─── Rules ────────────────────────────────────────────────────────────

    def _require_own_category(self, user_id: int, category_id: int) -> Category:
        """The category, if it is this user's — otherwise 404.

        Not 403, and not a distinct "no such category" error: the same answer
        for "does not exist" and "belongs to someone else" is what stops this
        endpoint being used to enumerate another account's categories.
        """
        category = self._categories.get_for_user(category_id, user_id)
        if category is None:
            raise CategoryNotFound
        return category

    @staticmethod
    def _require_active(category: Category) -> None:
        if not category.is_active:
            raise CategoryIsInactive

    @staticmethod
    def _require_matching_types(transaction_type: TransactionType, category: Category) -> None:
        """Refuse an expense in an income category, and the reverse.

        Compared through `REQUIRED_CATEGORY_TYPE` rather than directly. The two
        enums are `StrEnum` with equal members, so
        `CategoryType.INCOME == TransactionType.INCOME` is already true — the
        naive comparison would pass for the wrong reason, and would keep
        passing right up until one enum gained a member the other lacked.
        """
        if category.category_type != REQUIRED_CATEGORY_TYPE[transaction_type]:
            raise CategoryTypeMismatch
