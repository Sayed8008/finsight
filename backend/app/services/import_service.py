"""Importing transactions from a CSV file, and exporting them back out.

Import is the one place in this application where a single click can put
thousands of wrong rows into somebody's account, so the whole design is about
making that impossible rather than about making it convenient.

**Preview, then commit — never one step.** `plan()` reads the file, resolves
every category, finds every duplicate and decides everything the import would
do, and writes nothing. `commit()` does it again and only then writes. A file
that half imports is worse than one that does not import at all, so the write
is a single transaction that rolls back whole.

**The commit can only apply what was previewed.** The preview returns a
fingerprint of the file *and the options it was read with*; the commit sends it
back and is refused if it no longer matches. That is what makes "you are
importing what you were shown" a checkable claim rather than a hope — it also
stops a file previewed as day-first from being imported as month-first, which
would write a set of rows nobody ever looked at.

**Two questions the user answers, not the parser.** Unknown categories and
malformed rows both have an obvious tempting default — create them, skip them —
and both defaults lose data quietly. So the default is to refuse the file and
say exactly which rows and which names caused it. The permissive options exist,
but the interface can only offer them *after* the preview has named what they
would do, which is the difference between a choice and a shrug.

**Nothing is done per row that can be done once.** Categories are one query,
duplicate detection is one query, and the insert is one statement per few
hundred rows. A five-thousand-row file that cost five thousand lookups would be
correct and unusable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date as date_type
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, ValidationFailed
from app.models.category import Category
from app.models.enums import CategoryType, TransactionType
from app.models.transaction import Transaction
from app.repositories.transaction_repository import TransactionFilters, TransactionRepository
from app.services.transaction_csv import (
    CsvFormatError,
    DateOrder,
    ExportRow,
    ParsedRow,
    RowProblem,
    content_digest,
    read_csv,
    write_csv,
)
from app.services.transaction_service import REQUIRED_CATEGORY_TYPE

logger = logging.getLogger(__name__)

#: The largest file that will be read. Two megabytes is far more than
#: `MAX_ROWS` of transactions needs, so anything past it is a different kind of
#: file rather than a big one.
MAX_FILE_BYTES = 2 * 1024 * 1024

#: Tried in order. A file that has been near Excel on Windows is often
#: Windows-1252 rather than UTF-8, and refusing it over one accented character
#: helps nobody — but which one succeeded is reported, so a mojibake
#: description in the preview has a visible cause.
ENCODINGS = ("utf-8-sig", "cp1252")

#: Rows per INSERT. The point is that it is a constant rather than one: at 500,
#: a five-thousand-row import is ten statements. Large enough to matter, small
#: enough that the statement stays well inside MySQL's packet limit.
INSERT_CHUNK = 500

#: How many examples of anything the preview carries. Enough to see that the
#: dates and amounts were read the way they were meant; not so many that the
#: response becomes the file again.
SAMPLE_SIZE = 10

#: Stands in for "a category that does not exist yet" while planning. Real ids
#: are never zero, and the row is resolved properly once the category has been
#: created inside the import's own transaction.
CATEGORY_TO_BE_CREATED = 0


class ImportChanged(Conflict):
    """The file or the options are not the ones that were previewed."""

    message = (
        "This file is not the one that was previewed, or the options have changed since. "
        "Preview it again before importing."
    )


class UnknownCategoryPolicy(StrEnum):
    """What to do about a category name the account does not have.

    REFUSE is the default deliberately. Creating categories silently is how an
    account ends up with "Food", "food " and "Groceries" after three imports,
    and by then nothing can tell which was meant.
    """

    REFUSE = "refuse"
    CREATE = "create"


class CategoryAction(StrEnum):
    """What the import will do about one category name in the file."""

    MATCHED = "matched"
    CREATE = "create"
    UNKNOWN = "unknown"
    INACTIVE = "inactive"
    WRONG_TYPE = "wrong_type"


class DuplicateSource(StrEnum):
    """What a duplicate row duplicates."""

    #: An earlier row in the same file.
    FILE = "file"
    #: A transaction already recorded.
    HISTORY = "history"


@dataclass(frozen=True)
class ImportOptions:
    """Every decision the user makes before a file is read."""

    date_order: DateOrder = DateOrder.ISO
    unknown_categories: UnknownCategoryPolicy = UnknownCategoryPolicy.REFUSE
    #: Where rows with no category of their own are filed. Also what makes a
    #: file with no category column importable at all.
    default_category_id: int | None = None
    skip_duplicates: bool = True
    #: Import the rows that parsed and leave the rest. Off by default: a
    #: partial import nobody asked for is the failure this whole module exists
    #: to prevent.
    skip_invalid: bool = False

    @property
    def fingerprint(self) -> str:
        """The options, as one string, for the digest.

        Every field is in it. An option left out here would be an option a user
        could change between previewing and importing without the fingerprint
        noticing.
        """
        return "|".join(
            (
                str(self.date_order),
                str(self.unknown_categories),
                str(self.default_category_id),
                str(self.skip_duplicates),
                str(self.skip_invalid),
            )
        )


@dataclass(frozen=True)
class CategoryPlan:
    """One category name in the file, and what will become of it."""

    name: str
    category_type: CategoryType
    action: CategoryAction
    rows: int
    category_id: int | None = None

    @property
    def is_blocking(self) -> bool:
        return self.action in (
            CategoryAction.UNKNOWN,
            CategoryAction.INACTIVE,
            CategoryAction.WRONG_TYPE,
        )


@dataclass(frozen=True)
class DuplicateRow:
    """A row that already exists, here or in the account."""

    line_number: int
    date: date_type
    amount: Decimal
    description: str
    source: DuplicateSource


@dataclass(frozen=True)
class ImportPlan:
    """Everything the import would do, having done none of it."""

    total_rows: int
    #: Which fields were recognised in the header row, so a file whose "Memo"
    #: column went unread says so rather than silently importing without it.
    columns: tuple[str, ...]
    #: Rows that parsed, resolved to a category, and are not duplicates.
    ready: tuple[ParsedRow, ...]
    #: The category each ready row will be filed under, by line number.
    assignments: dict[int, int]
    problems: tuple[RowProblem, ...]
    failed_rows: int
    duplicates: tuple[DuplicateRow, ...]
    categories: tuple[CategoryPlan, ...]
    ambiguous_dates: int
    encoding: str
    digest: str
    blockers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def would_import(self) -> int:
        return 0 if self.blockers else len(self.ready)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)

    @property
    def categories_to_create(self) -> tuple[CategoryPlan, ...]:
        return tuple(plan for plan in self.categories if plan.action is CategoryAction.CREATE)


@dataclass(frozen=True)
class ImportOutcome:
    """What an import actually did."""

    imported: int
    skipped_duplicates: int
    skipped_invalid: int
    created_categories: tuple[str, ...]
    first_date: date_type | None
    last_date: date_type | None


class ImportService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._transactions = TransactionRepository(session)

    # ─── Planning ─────────────────────────────────────────────────────────

    def plan(self, user_id: int, content: bytes, options: ImportOptions) -> ImportPlan:
        """Work out everything the import would do. Writes nothing."""
        if len(content) > MAX_FILE_BYTES:
            raise ValidationFailed(
                f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. "
                "A transaction export is text, so a file this size is probably not one."
            )

        text, encoding = self._decode(content)
        try:
            read = read_csv(
                text,
                date_order=options.date_order,
                category_required=options.default_category_id is None,
            )
        except CsvFormatError as exc:
            # A file-level failure — no date column, no rows at all. There is
            # nothing to preview, so it is an error rather than a plan with a
            # blocker on it.
            raise ValidationFailed(str(exc)) from exc

        categories, assignments, category_problems = self._resolve_categories(
            user_id, read.rows, options
        )

        placeable = [row for row in read.rows if row.line_number in assignments]
        ready, duplicates = self._split_duplicates(user_id, placeable, options)

        problems = tuple(sorted(read.problems + category_problems, key=lambda p: p.line_number))
        failed_rows = read.failed_rows + len({problem.line_number for problem in category_problems})

        return ImportPlan(
            total_rows=read.total_rows,
            columns=read.columns,
            ready=tuple(ready),
            assignments=assignments,
            problems=problems,
            failed_rows=failed_rows,
            duplicates=tuple(duplicates),
            categories=categories,
            ambiguous_dates=read.ambiguous_dates,
            encoding=encoding,
            digest=content_digest(content, options.fingerprint),
            blockers=self._blockers(categories, failed_rows, len(ready), duplicates, options),
        )

    @staticmethod
    def _decode(content: bytes) -> tuple[str, str]:
        """The file as text, and which encoding read it."""
        for encoding in ENCODINGS:
            try:
                return content.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise ValidationFailed(
            "That file is not text this reader can decode. Save it as CSV (UTF-8) and try again."
        )

    # ─── Categories ───────────────────────────────────────────────────────

    def _resolve_categories(
        self,
        user_id: int,
        rows: Sequence[ParsedRow],
        options: ImportOptions,
    ) -> tuple[tuple[CategoryPlan, ...], dict[int, int], tuple[RowProblem, ...]]:
        """Decide where every row is filed, in one query.

        One query, not one per row: a five-thousand-row file names at most a
        few dozen distinct categories, and the map is built once. This is the
        difference between an import that takes a moment and one that takes a
        minute for no reason.

        The lookup key is *name and type together*, because a category's type
        must agree with its transaction's (see `transaction_service`). Filing
        an income row under an expense category would corrupt every total that
        trusts the pair, so a name that exists under the other type is reported
        as exactly that rather than as "not found".
        """
        owned = self._session.execute(
            select(Category).where(Category.user_id == user_id)
        ).scalars()

        by_key: dict[tuple[str, CategoryType], Category] = {}
        by_name: dict[str, list[Category]] = {}
        for category in owned:
            key = category.name.strip().lower()
            by_key[(key, category.category_type)] = category
            by_name.setdefault(key, []).append(category)

        default = self._default_category(by_key, options.default_category_id)

        assignments: dict[int, int] = {}
        problems: list[RowProblem] = []
        plans: dict[tuple[str, CategoryType], CategoryPlan] = {}

        for row in rows:
            wanted = REQUIRED_CATEGORY_TYPE[row.transaction_type]

            if row.category_name is None:
                # No category column at all; the fallback carries the file.
                if default is None or default.category_type is not wanted:
                    problems.append(
                        RowProblem(
                            line_number=row.line_number,
                            column="category",
                            value="",
                            message=(
                                f"This row is {row.transaction_type} and the category chosen for "
                                "rows without one is not. Give the file a category column, or "
                                "choose a category of the right kind."
                            ),
                        )
                    )
                    continue
                assignments[row.line_number] = default.id
                continue

            key = (row.category_name.strip().lower(), wanted)
            existing = by_key.get(key)
            plan_key = key

            if existing is not None and existing.is_active:
                action, category_id = CategoryAction.MATCHED, existing.id
                assignments[row.line_number] = existing.id
            elif existing is not None:
                action, category_id = CategoryAction.INACTIVE, existing.id
            elif by_name.get(key[0]):
                action, category_id = CategoryAction.WRONG_TYPE, None
            elif options.unknown_categories is UnknownCategoryPolicy.CREATE:
                action, category_id = CategoryAction.CREATE, None
                # The row is placeable; the id arrives when the category is
                # created, inside the same transaction as the rows themselves.
                assignments[row.line_number] = CATEGORY_TO_BE_CREATED
            else:
                action, category_id = CategoryAction.UNKNOWN, None

            previous = plans.get(plan_key)
            plans[plan_key] = CategoryPlan(
                # The *first* spelling seen wins. A file writing "Skydiving"
                # twice and "skydiving" once names one category, and taking the
                # last occurrence would make which one depend on row order.
                name=previous.name if previous else row.category_name.strip(),
                category_type=wanted,
                action=action,
                rows=(previous.rows if previous else 0) + 1,
                category_id=category_id,
            )

        return (
            tuple(sorted(plans.values(), key=lambda plan: (plan.action, plan.name))),
            assignments,
            tuple(problems),
        )

    @staticmethod
    def _default_category(
        by_key: dict[tuple[str, CategoryType], Category], category_id: int | None
    ) -> Category | None:
        if category_id is None:
            return None
        for category in by_key.values():
            if category.id == category_id and category.is_active:
                return category
        raise ValidationFailed("The category chosen for uncategorised rows is not available.")

    # ─── Duplicates ───────────────────────────────────────────────────────

    def _split_duplicates(
        self,
        user_id: int,
        rows: Sequence[ParsedRow],
        options: ImportOptions,
    ) -> tuple[list[ParsedRow], list[DuplicateRow]]:
        """Separate rows that already exist from rows that do not.

        Two sources, and both are worth telling apart in the preview: a row
        repeated inside the file, and a row that matches something already
        recorded — the second being what happens when a statement is imported
        twice, which is the single most likely way to use this feature wrongly.

        The history is fetched once, for the date range the file covers. A file
        of one month does not read a year of transactions, and a file of five
        thousand rows still costs one query rather than five thousand.
        """
        if not rows:
            return [], []

        seen = self._existing_keys(user_id, rows)
        kept: list[ParsedRow] = []
        duplicates: list[DuplicateRow] = []

        for row in rows:
            key = row.duplicate_key
            if key is None or key not in seen:
                if key is not None:
                    seen[key] = DuplicateSource.FILE
                kept.append(row)
                continue

            duplicates.append(
                DuplicateRow(
                    line_number=row.line_number,
                    date=row.date,
                    amount=row.amount,
                    description=row.description or "",
                    source=seen[key],
                )
            )
            if not options.skip_duplicates:
                kept.append(row)

        return kept, duplicates

    def _existing_keys(
        self, user_id: int, rows: Sequence[ParsedRow]
    ) -> dict[tuple[date_type, Decimal, TransactionType, str], DuplicateSource]:
        """What this account already holds over the file's date range."""
        statement = select(
            Transaction.date,
            Transaction.amount,
            Transaction.transaction_type,
            Transaction.description,
        ).where(
            Transaction.user_id == user_id,
            Transaction.date >= min(row.date for row in rows),
            Transaction.date <= max(row.date for row in rows),
            Transaction.description.is_not(None),
            Transaction.description != "",
        )

        rows = self._session.execute(statement)
        return {
            (day, amount, kind, " ".join(description.lower().split())): DuplicateSource.HISTORY
            for day, amount, kind, description in rows
        }

    # ─── Blocking ─────────────────────────────────────────────────────────

    @staticmethod
    def _blockers(
        categories: Sequence[CategoryPlan],
        failed_rows: int,
        ready: int,
        duplicates: Sequence[DuplicateRow],
        options: ImportOptions,
    ) -> tuple[str, ...]:
        """Why this file will not import as things stand.

        Each one is a sentence naming the count and what to do about it. A
        blocked plan still previews in full — the user needs to see what is
        wrong in order to decide, which is the whole point of previewing.
        """
        reasons: list[str] = []

        unknown = [plan for plan in categories if plan.action is CategoryAction.UNKNOWN]
        if unknown:
            names = ", ".join(plan.name for plan in unknown[:5])
            reasons.append(
                f"{len(unknown)} category name(s) are not in this account: {names}. "
                "Create them as part of the import, or correct the file."
            )

        inactive = [plan for plan in categories if plan.action is CategoryAction.INACTIVE]
        if inactive:
            reasons.append(
                f"{len(inactive)} category name(s) have been deactivated: "
                f"{', '.join(plan.name for plan in inactive[:5])}. Restore them first."
            )

        wrong_type = [plan for plan in categories if plan.action is CategoryAction.WRONG_TYPE]
        if wrong_type:
            reasons.append(
                f"{len(wrong_type)} category name(s) exist for the other direction: "
                f"{', '.join(plan.name for plan in wrong_type[:5])}. An expense cannot be "
                "filed under an income category."
            )

        if failed_rows and not options.skip_invalid:
            reasons.append(
                f"{failed_rows} row(s) could not be read. Correct them, or choose to import "
                "the rest and leave them out."
            )

        if not reasons and ready == 0:
            reasons.append(
                "Nothing in this file would be imported."
                + (
                    f" All {len(duplicates)} row(s) are already recorded."
                    if duplicates and options.skip_duplicates
                    else ""
                )
            )

        return tuple(reasons)

    # ─── Committing ───────────────────────────────────────────────────────

    def commit(
        self, user_id: int, content: bytes, options: ImportOptions, digest: str
    ) -> ImportOutcome:
        """Apply a previewed file, in one transaction.

        The plan is built again rather than remembered. Remembering it would
        mean holding server-side state between two requests and trusting it to
        still describe the file — the fingerprint does the same job without
        anything to go stale, and re-planning is the same handful of queries.
        """
        plan = self.plan(user_id, content, options)

        if plan.digest != digest:
            raise ImportChanged

        if plan.is_blocked:
            raise ValidationFailed(plan.blockers[0])

        try:
            created = self._create_categories(user_id, plan)
            self._insert_rows(user_id, plan, created)
            self._session.commit()
        except Exception:
            # One transaction, rolled back whole. A file that half imports is
            # the failure this module exists to prevent, and "half" includes
            # the categories it created on the way.
            self._session.rollback()
            raise

        dates = [row.date for row in plan.ready]
        logger.info(
            "Imported %s transaction(s) for user id=%s (%s duplicate(s) and %s unreadable "
            "row(s) left out, %s category/categories created)",
            len(plan.ready),
            user_id,
            len(plan.duplicates) if options.skip_duplicates else 0,
            plan.failed_rows,
            len(created),
        )

        return ImportOutcome(
            imported=len(plan.ready),
            skipped_duplicates=len(plan.duplicates) if options.skip_duplicates else 0,
            skipped_invalid=plan.failed_rows,
            # The names, not the internal keys the id map is built on.
            created_categories=tuple(
                sorted(category.name for category in plan.categories_to_create)
            ),
            first_date=min(dates) if dates else None,
            last_date=max(dates) if dates else None,
        )

    def _create_categories(self, user_id: int, plan: ImportPlan) -> dict[str, int]:
        """Create the categories the file named, before the rows that need them."""
        created: dict[str, int] = {}
        for category_plan in plan.categories_to_create:
            category = Category(
                user_id=user_id,
                name=category_plan.name,
                category_type=category_plan.category_type,
            )
            self._session.add(category)
            self._session.flush()
            created[self._category_key(category_plan.name, category_plan.category_type)] = (
                category.id
            )
        return created

    @staticmethod
    def _category_key(name: str, category_type: CategoryType) -> str:
        return f"{name.strip().lower()}|{category_type}"

    def _insert_rows(self, user_id: int, plan: ImportPlan, created: dict[str, int]) -> None:
        """Write the rows, a few hundred at a time.

        A Core `insert()` with a list of values, rather than adding five
        thousand ORM objects: the ORM would round-trip each one to fetch the id
        it was given, and nothing here wants the ids back. This is the
        difference the row count actually notices.
        """
        values = [
            {
                "user_id": user_id,
                "amount": row.amount,
                "transaction_type": row.transaction_type,
                "category_id": self._category_for(row, plan, created),
                "date": row.date,
                "description": row.description,
                "payment_method": row.payment_method,
            }
            for row in plan.ready
        ]

        for start in range(0, len(values), INSERT_CHUNK):
            self._session.execute(insert(Transaction), values[start : start + INSERT_CHUNK])

    def _category_for(self, row: ParsedRow, plan: ImportPlan, created: dict[str, int]) -> int:
        assigned = plan.assignments[row.line_number]
        if assigned:
            return assigned
        # Zero means "a category that did not exist when the plan was made".
        wanted = REQUIRED_CATEGORY_TYPE[row.transaction_type]
        return created[self._category_key(row.category_name or "", wanted)]

    # ─── Exporting ────────────────────────────────────────────────────────

    def export(self, user_id: int, filters: TransactionFilters | None = None) -> str:
        """Every matching transaction, as CSV.

        The same filters the list endpoint takes, applied by the same code, so
        "export what I am looking at" means exactly what is on screen. Not
        paginated: a page of an export is not an export.
        """
        rows = self._transactions.list_all(user_id, filters)
        logger.info("Exported %s transaction(s) for user id=%s", len(rows), user_id)
        return write_csv(_as_export_rows(rows))


def _as_export_rows(rows: Iterable[Transaction]) -> list[ExportRow]:
    return [
        ExportRow(
            date=row.date,
            amount=row.amount,
            transaction_type=row.transaction_type,
            category=row.category.name,
            description=row.description,
            payment_method=row.payment_method,
        )
        for row in rows
    ]


__all__ = [
    "MAX_FILE_BYTES",
    "CategoryAction",
    "CategoryPlan",
    "DuplicateRow",
    "DuplicateSource",
    "ImportChanged",
    "ImportOptions",
    "ImportOutcome",
    "ImportPlan",
    "ImportService",
    "UnknownCategoryPolicy",
]
