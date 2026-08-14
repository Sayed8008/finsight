"""Tests for transaction filtering, sorting and pagination.

These call the repository directly against real MySQL — no HTTP, no service
layer — because what is being tested is the SQL. Running them on SQLite would
defeat the purpose: `LIKE` case sensitivity, `ORDER BY` on an ENUM and DECIMAL
comparison all differ between the two, so a green run there would say nothing
about the database this application actually uses (ADR-005).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationFailed
from app.models.category import Category
from app.models.enums import CategoryType, TransactionType
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.transaction_repository import (
    SortDirection,
    SortField,
    TransactionFilters,
    TransactionRepository,
)
from tests.conftest import QueryCounter

# A hash-shaped string. Nothing here verifies a password, and using a real
# Argon2 hash would add ~100ms per user for no benefit.
NOT_A_REAL_HASH = "$argon2id$v=19$m=65536,t=3,p=4$not-a-real-hash"


class Ledger:
    """A user with categories and transactions, built for querying.

    A class rather than a bundle of fixtures so a test can say
    `ledger.add(...)` when it needs one more row, without a second fixture
    that exists only to add it.
    """

    def __init__(self, session: Session, email: str = "ledger@example.com") -> None:
        self.session = session
        self.repo = TransactionRepository(session)

        self.user = User(email=email, password_hash=NOT_A_REAL_HASH, full_name="Ledger Owner")
        session.add(self.user)
        session.flush()

        self.categories: dict[str, Category] = {}
        for name, category_type in (
            ("Salary", CategoryType.INCOME),
            ("Freelance", CategoryType.INCOME),
            ("Food", CategoryType.EXPENSE),
            ("Transport", CategoryType.EXPENSE),
            ("Rent", CategoryType.EXPENSE),
            ("Entertainment", CategoryType.EXPENSE),
        ):
            category = Category(user_id=self.user.id, name=name, category_type=category_type)
            session.add(category)
            self.categories[name] = category
        session.flush()

        # Deliberate awkwardness: two rows share 2026-01-05 and two share
        # 2026-03-15 (so tie-breaking is exercised), one description contains a
        # literal % and another a literal _ (so LIKE escaping is exercised).
        for day, kind, category, amount, method, description in (
            ("2026-01-05", TransactionType.EXPENSE, "Food", "250.00", "cash", "Lunch at campus"),
            ("2026-01-05", TransactionType.EXPENSE, "Transport", "60.00", "cash", "Bus fare"),
            ("2026-01-20", TransactionType.INCOME, "Salary", "45000.00", "bank", "January salary"),
            ("2026-02-10", TransactionType.EXPENSE, "Food", "1200.50", "card", "Groceries 50% off"),
            (
                "2026-02-14",
                TransactionType.EXPENSE,
                "Entertainment",
                "499.00",
                "bKash",
                "Netflix subscription",
            ),
            ("2026-03-01", TransactionType.EXPENSE, "Rent", "15000.00", "bank", "March rent"),
            ("2026-03-15", TransactionType.INCOME, "Freelance", "8000.00", "bKash", "Logo design"),
            ("2026-03-15", TransactionType.EXPENSE, "Food", "75.25", "cash", "Tea and snacks_x"),
        ):
            self.add(
                day=day,
                kind=kind,
                category=category,
                amount=amount,
                method=method,
                description=description,
            )
        session.flush()

    def add(
        self,
        *,
        day: str,
        kind: TransactionType,
        category: str,
        amount: str,
        method: str | None = "cash",
        description: str | None = None,
    ) -> Transaction:
        transaction = Transaction(
            user_id=self.user.id,
            amount=Decimal(amount),
            transaction_type=kind,
            category_id=self.categories[category].id,
            date=date.fromisoformat(day),
            description=description,
            payment_method=method,
        )
        self.session.add(transaction)
        self.session.flush()
        return transaction

    def descriptions(self, **kwargs) -> list[str | None]:
        """Descriptions of one page, in the order the database returned them."""
        rows, _ = self.repo.list_page(self.user.id, **kwargs)
        return [row.description for row in rows]


@pytest.fixture
def ledger(db_session: Session) -> Ledger:
    """One user with a small, deliberately varied set of transactions."""
    return Ledger(db_session)


TOTAL_ROWS = 8


# ─── The unfiltered page ──────────────────────────────────────────────────


def test_a_page_returns_every_row_and_the_total(ledger: Ledger) -> None:
    rows, total = ledger.repo.list_page(ledger.user.id)

    assert len(rows) == TOTAL_ROWS
    assert total == TOTAL_ROWS


def test_the_default_order_is_newest_first(ledger: Ledger) -> None:
    rows, _ = ledger.repo.list_page(ledger.user.id)

    dates = [row.date for row in rows]
    assert dates == sorted(dates, reverse=True)


def test_amounts_come_back_as_decimals(ledger: Ledger) -> None:
    """Not floats. `Numeric(14, 2)` plus PyMySQL must hand back Decimal (ADR-003)."""
    rows, _ = ledger.repo.list_page(ledger.user.id, sort_by=SortField.AMOUNT)

    assert all(isinstance(row.amount, Decimal) for row in rows)
    assert rows[0].amount == Decimal("45000.00")


# ─── Pagination ───────────────────────────────────────────────────────────


def test_a_page_is_limited_to_its_size(ledger: Ledger) -> None:
    rows, total = ledger.repo.list_page(ledger.user.id, page=1, page_size=3)

    assert len(rows) == 3
    # The total describes the whole filtered set, not the page.
    assert total == TOTAL_ROWS


def test_pages_do_not_overlap_and_cover_everything(ledger: Ledger) -> None:
    """The property that matters: every row appears exactly once across pages."""
    seen: list[int] = []
    for page in (1, 2, 3):
        rows, _ = ledger.repo.list_page(ledger.user.id, page=page, page_size=3)
        seen.extend(row.id for row in rows)

    assert len(seen) == TOTAL_ROWS
    assert len(set(seen)) == TOTAL_ROWS


def test_paging_is_stable_when_rows_share_a_sort_value(ledger: Ledger) -> None:
    """Two rows share each of two dates, so ORDER BY date alone is ambiguous.

    Without the id tie-breaker, MySQL may order tied rows differently per
    query, which lets a row appear on two pages while another is never shown.
    """
    first_run = [
        row.id
        for page in (1, 2, 3, 4)
        for row in ledger.repo.list_page(ledger.user.id, page=page, page_size=2)[0]
    ]
    second_run = [
        row.id
        for page in (1, 2, 3, 4)
        for row in ledger.repo.list_page(ledger.user.id, page=page, page_size=2)[0]
    ]

    assert first_run == second_run
    assert len(set(first_run)) == TOTAL_ROWS


def test_a_page_past_the_end_is_empty_but_the_total_still_counts(ledger: Ledger) -> None:
    rows, total = ledger.repo.list_page(ledger.user.id, page=99, page_size=3)

    assert rows == []
    assert total == TOTAL_ROWS


# ─── Filtering ────────────────────────────────────────────────────────────


def test_filtering_by_date_range_includes_both_ends(ledger: Ledger) -> None:
    """A range ending on the 20th includes the 20th — what selecting a month means."""
    rows, total = ledger.repo.list_page(
        ledger.user.id,
        TransactionFilters(date_from=date(2026, 1, 5), date_to=date(2026, 1, 20)),
    )

    assert total == 3
    assert {row.date for row in rows} == {date(2026, 1, 5), date(2026, 1, 20)}


def test_filtering_by_type(ledger: Ledger) -> None:
    rows, total = ledger.repo.list_page(
        ledger.user.id, TransactionFilters(transaction_type=TransactionType.INCOME)
    )

    assert total == 2
    assert {row.transaction_type for row in rows} == {TransactionType.INCOME}


def test_filtering_by_category(ledger: Ledger) -> None:
    food = ledger.categories["Food"].id

    rows, total = ledger.repo.list_page(ledger.user.id, TransactionFilters(category_id=food))

    assert total == 3
    assert {row.category_id for row in rows} == {food}


def test_filtering_by_payment_method(ledger: Ledger) -> None:
    _, total = ledger.repo.list_page(ledger.user.id, TransactionFilters(payment_method="bKash"))

    assert total == 2


def test_filtering_by_amount_range(ledger: Ledger) -> None:
    rows, total = ledger.repo.list_page(
        ledger.user.id,
        TransactionFilters(amount_min=Decimal("100.00"), amount_max=Decimal("1300.00")),
    )

    # 250.00, 499.00 and 1200.50 — both bounds inclusive.
    assert total == 3
    assert all(Decimal("100.00") <= row.amount <= Decimal("1300.00") for row in rows)


def test_searching_descriptions_matches_a_substring(ledger: Ledger) -> None:
    _, total = ledger.repo.list_page(ledger.user.id, TransactionFilters(search="salary"))

    assert total == 1


def test_a_percent_sign_in_a_search_term_is_a_literal(ledger: Ledger) -> None:
    """Unescaped, "50%" as a LIKE pattern would match every description."""
    rows, total = ledger.repo.list_page(ledger.user.id, TransactionFilters(search="50%"))

    assert total == 1
    assert rows[0].description == "Groceries 50% off"


def test_an_underscore_in_a_search_term_is_a_literal(ledger: Ledger) -> None:
    """Unescaped, `_` is LIKE's single-character wildcard."""
    _, matching = ledger.repo.list_page(ledger.user.id, TransactionFilters(search="snacks_x"))
    _, wildcard_would_match = ledger.repo.list_page(
        ledger.user.id, TransactionFilters(search="snacksXx")
    )

    assert matching == 1
    assert wildcard_would_match == 0


def test_filters_combine(ledger: Ledger) -> None:
    """Each filter narrows the last, rather than replacing it."""
    rows, total = ledger.repo.list_page(
        ledger.user.id,
        TransactionFilters(
            transaction_type=TransactionType.EXPENSE,
            category_id=ledger.categories["Food"].id,
            payment_method="cash",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        ),
    )

    assert total == 1
    assert rows[0].description == "Lunch at campus"


def test_filters_that_match_nothing_return_an_empty_page(ledger: Ledger) -> None:
    rows, total = ledger.repo.list_page(
        ledger.user.id, TransactionFilters(search="nothing matches this")
    )

    assert rows == []
    assert total == 0


def test_a_reversed_date_range_is_rejected_rather_than_returning_nothing() -> None:
    """An empty result would look like missing data instead of a mistake."""
    with pytest.raises(ValidationFailed):
        TransactionFilters(date_from=date(2026, 6, 1), date_to=date(2026, 1, 1))


def test_a_reversed_amount_range_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        TransactionFilters(amount_min=Decimal("500.00"), amount_max=Decimal("100.00"))


def test_an_equal_range_is_allowed(ledger: Ledger) -> None:
    """A single day, or an exact amount, is a legitimate range."""
    _, total = ledger.repo.list_page(
        ledger.user.id,
        TransactionFilters(date_from=date(2026, 1, 5), date_to=date(2026, 1, 5)),
    )

    assert total == 2


# ─── Sorting ──────────────────────────────────────────────────────────────


def test_sorting_by_amount(ledger: Ledger) -> None:
    rows, _ = ledger.repo.list_page(
        ledger.user.id, sort_by=SortField.AMOUNT, direction=SortDirection.ASC
    )

    amounts = [row.amount for row in rows]
    assert amounts == sorted(amounts)


def test_sorting_by_amount_is_numeric_not_lexicographic(ledger: Ledger) -> None:
    """As text, "75.25" would sort after "45000.00"."""
    rows, _ = ledger.repo.list_page(
        ledger.user.id, sort_by=SortField.AMOUNT, direction=SortDirection.DESC
    )

    assert rows[0].amount == Decimal("45000.00")


def test_sorting_by_category_uses_the_name_not_the_id(ledger: Ledger) -> None:
    rows, _ = ledger.repo.list_page(
        ledger.user.id, sort_by=SortField.CATEGORY, direction=SortDirection.ASC
    )

    names = [row.category.name for row in rows]
    assert names == sorted(names)


def test_sorting_by_description(ledger: Ledger) -> None:
    rows, _ = ledger.repo.list_page(
        ledger.user.id, sort_by=SortField.DESCRIPTION, direction=SortDirection.ASC
    )

    descriptions = [row.description for row in rows if row.description]
    assert descriptions == sorted(descriptions)


def test_direction_reverses_the_order(ledger: Ledger) -> None:
    ascending = ledger.descriptions(sort_by=SortField.AMOUNT, direction=SortDirection.ASC)
    descending = ledger.descriptions(sort_by=SortField.AMOUNT, direction=SortDirection.DESC)

    assert ascending == list(reversed(descending))


# ─── One user's rows are invisible to another ─────────────────────────────


def test_a_query_never_returns_another_users_rows(db_session: Session) -> None:
    """The `user_id` clause is not optional — see `_filter_clauses`."""
    mine = Ledger(db_session, email="mine@example.com")
    theirs = Ledger(db_session, email="theirs@example.com")

    rows, total = mine.repo.list_page(mine.user.id)

    assert total == TOTAL_ROWS
    assert {row.user_id for row in rows} == {mine.user.id}
    assert theirs.user.id not in {row.user_id for row in rows}


def test_another_users_transaction_is_not_retrievable_by_id(db_session: Session) -> None:
    mine = Ledger(db_session, email="mine@example.com")
    theirs = Ledger(db_session, email="theirs@example.com")
    their_row, _ = theirs.repo.list_page(theirs.user.id)

    assert mine.repo.get_for_user(their_row[0].id, mine.user.id) is None


def test_payment_methods_are_listed_per_user(db_session: Session) -> None:
    mine = Ledger(db_session, email="mine@example.com")
    Ledger(db_session, email="theirs@example.com")
    mine.add(
        day="2026-04-01",
        kind=TransactionType.EXPENSE,
        category="Food",
        amount="10.00",
        method="Nagad",
    )

    methods = mine.repo.payment_methods_used(mine.user.id)

    assert set(methods) == {"cash", "bank", "card", "bKash", "Nagad"}
    # MySQL's default collation (utf8mb4_0900_ai_ci) is case-insensitive, so
    # "bank" sorts before "bKash". Asserted this way rather than as a literal
    # list, so the test states the rule instead of memorising one result.
    assert methods == sorted(methods, key=str.lower)


# ─── Query count ──────────────────────────────────────────────────────────


def test_a_page_of_rows_with_categories_costs_two_queries(
    ledger: Ledger, query_counter: QueryCounter
) -> None:
    """The N+1 check: one query for the page, one for the count — never one per row.

    A functional test cannot catch this. The rows would be correct either way;
    the only difference is eight extra round trips that become eight hundred
    once the table is real.
    """
    query_counter.reset()

    rows, _ = ledger.repo.list_page(ledger.user.id)
    # Touching the relationship is what would trigger a lazy load per row.
    assert [row.category.name for row in rows]

    assert len(query_counter.selects) == 2
