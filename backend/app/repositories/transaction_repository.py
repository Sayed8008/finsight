"""Data access for transactions: filtering, sorting and pagination in SQL.

`TransactionFilters` is a *query object* — one value holding every optional
criterion, validated on construction. It lives beside the query that consumes
it rather than in the API layer, because it describes a question about stored
data, not an HTTP request. The alternative, a method with eleven keyword
arguments, grows a new parameter every time a filter is added and forces every
caller in between to pass it along.

Filtering happens here, in the database, and never in Python. Fetching a
user's rows and sifting them in the application would get slower in exact
proportion to the history it is meant to search, and would make `total` a lie:
a client can only sort or filter the page it was handed, so "sort by amount"
would order 25 rows rather than four thousand (ADR-021).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session, contains_eager

from app.core.exceptions import ValidationFailed
from app.models.category import Category
from app.models.enums import TransactionType
from app.models.transaction import Transaction

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200


class SortField(StrEnum):
    """A column the transaction list may be ordered by."""

    DATE = "date"
    AMOUNT = "amount"
    DESCRIPTION = "description"
    CATEGORY = "category"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True)
class TransactionFilters:
    """Every way the transaction list can be narrowed. All optional, all
    combinable — they compose into one WHERE clause.

    Frozen because a filter set is a value: two with the same criteria are
    interchangeable, and nothing should be able to alter one after a query has
    been built from it.
    """

    date_from: date | None = None
    date_to: date | None = None
    transaction_type: TransactionType | None = None
    category_id: int | None = None
    payment_method: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    #: Matched against the description as a substring, case-insensitively.
    search: str | None = None

    def __post_init__(self) -> None:
        """Reject a range that cannot match anything.

        A reversed range is a mistake worth reporting, not an empty result to
        puzzle over: `date_from=2026-06-01&date_to=2026-01-01` would otherwise
        return nothing at all and look like missing data.

        Validated here rather than in the API layer so the rule holds for
        every caller, including tests that build filters directly.
        """
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationFailed("The start date cannot be after the end date.")

        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValidationFailed("The smallest amount cannot be greater than the largest amount.")


#: Which column each sort field maps to. `CATEGORY` sorts by the category's
#: name rather than its id, because an id is not an order anyone means.
_SORT_COLUMNS: dict[SortField, ColumnElement] = {
    SortField.DATE: Transaction.date,
    SortField.AMOUNT: Transaction.amount,
    SortField.DESCRIPTION: Transaction.description,
    SortField.CATEGORY: Category.name,
}


class TransactionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ─── Reading ──────────────────────────────────────────────────────────

    def list_page(
        self,
        user_id: int,
        filters: TransactionFilters | None = None,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        sort_by: SortField = SortField.DATE,
        direction: SortDirection = SortDirection.DESC,
    ) -> tuple[list[Transaction], int]:
        """One page of this user's transactions, and the total that matched.

        Two queries: the page, and a `COUNT(*)` over the same filters. Both are
        built from `_filter_clauses`, so they cannot drift apart — a count that
        applied different criteria than the page it describes would produce a
        pager that disagrees with its own table.

        The category is loaded with the same join that makes sorting by
        category name possible (`contains_eager`), so rendering a page of rows
        with their category names costs one query rather than one per row.
        """
        filters = filters or TransactionFilters()
        clauses = self._filter_clauses(user_id, filters)

        statement: Select[tuple[Transaction]] = (
            select(Transaction)
            # An inner join is safe: `category_id` is NOT NULL, so every
            # transaction has exactly one category.
            .join(Transaction.category)
            .options(contains_eager(Transaction.category))
            .where(*clauses)
            .order_by(*self._order_by(sort_by, direction))
            .limit(page_size)
            .offset((page - 1) * page_size)
        )

        rows = list(self._session.execute(statement).scalars())
        return rows, self.count(user_id, filters)

    def count(self, user_id: int, filters: TransactionFilters | None = None) -> int:
        """How many transactions match, ignoring pagination."""
        filters = filters or TransactionFilters()
        statement = select(func.count(Transaction.id)).where(
            *self._filter_clauses(user_id, filters)
        )
        return self._session.execute(statement).scalar_one()

    def get_for_user(self, transaction_id: int, user_id: int) -> Transaction | None:
        """One transaction, or None if it does not exist *or* is not this user's.

        The two are deliberately indistinguishable, so the API can answer 404
        for both rather than confirming that another user's row exists.
        """
        statement = select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == user_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def payment_methods_used(self, user_id: int) -> list[str]:
        """The distinct payment methods this user has actually recorded.

        `payment_method` is free text rather than a table (see
        docs/DATABASE.md), so this is what lets the interface offer a filter
        list of real values instead of asking the user to remember how they
        spelled "bKash" last time.
        """
        statement = (
            select(Transaction.payment_method)
            .where(
                Transaction.user_id == user_id,
                Transaction.payment_method.is_not(None),
                Transaction.payment_method != "",
            )
            .distinct()
            .order_by(Transaction.payment_method)
        )
        return list(self._session.execute(statement).scalars())

    # ─── Writing ──────────────────────────────────────────────────────────

    def add(self, transaction: Transaction) -> Transaction:
        """Stage a new transaction and assign its primary key.

        `flush` sends the INSERT so the id is available; the service decides
        when to commit.
        """
        self._session.add(transaction)
        self._session.flush()
        return transaction

    def delete(self, transaction: Transaction) -> None:
        self._session.delete(transaction)
        self._session.flush()

    # ─── Query construction ───────────────────────────────────────────────

    @staticmethod
    def _filter_clauses(user_id: int, filters: TransactionFilters) -> list[ColumnElement[bool]]:
        """Turn a filter set into WHERE clauses.

        The `user_id` clause is first and unconditional. It is not a filter the
        caller may choose to leave out — it is the point at which "users may
        only reach their own data" becomes true for this table.
        """
        clauses: list[ColumnElement[bool]] = [Transaction.user_id == user_id]

        if filters.date_from is not None:
            clauses.append(Transaction.date >= filters.date_from)
        if filters.date_to is not None:
            # Inclusive: a range ending on the 30th includes the 30th, which is
            # what a person selecting a month means.
            clauses.append(Transaction.date <= filters.date_to)

        if filters.transaction_type is not None:
            clauses.append(Transaction.transaction_type == filters.transaction_type)

        if filters.category_id is not None:
            clauses.append(Transaction.category_id == filters.category_id)

        if filters.payment_method:
            clauses.append(Transaction.payment_method == filters.payment_method)

        if filters.amount_min is not None:
            clauses.append(Transaction.amount >= filters.amount_min)
        if filters.amount_max is not None:
            clauses.append(Transaction.amount <= filters.amount_max)

        if filters.search:
            # `autoescape` escapes % and _ in the term. Without it, searching
            # for "50%" would match every description, and a user searching
            # for a literal underscore would get single-character wildcards.
            clauses.append(Transaction.description.contains(filters.search, autoescape=True))

        return clauses

    @staticmethod
    def _order_by(sort_by: SortField, direction: SortDirection) -> list[ColumnElement]:
        """The ORDER BY terms, always ending in a unique tie-breaker.

        Without the trailing `id`, rows sharing a sort value — several
        transactions on the same date, which is the common case — have no
        defined order between them. MySQL is then free to return them
        differently for each page, so a row can appear on both page 1 and
        page 2 while another is never shown at all.
        """
        column = _SORT_COLUMNS[sort_by]
        ordered = column.asc() if direction is SortDirection.ASC else column.desc()

        # Newest-first within a tie, matching the default sort's intent.
        return [ordered, Transaction.id.desc()]
