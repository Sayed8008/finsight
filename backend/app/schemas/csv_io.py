"""Request and response models for CSV import and export.

The preview response is the important one, and it is deliberately verbose.
Its job is to let somebody decide whether to write several thousand rows into
their own financial history, and a summary that says "412 rows look fine"
without showing any of them cannot support that decision. So it carries counts,
the reasons anything is blocked, a sample of rows exactly as they were read,
and every category name the file used with what will become of it.

The sample is the part that earns its place: reading `2026-03-04` back out of
`04/03/2026` is how a user discovers in two seconds that they picked the wrong
date order, which is the mistake that would otherwise be found months later.
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict

from app.core.money import MoneyOut
from app.models.enums import CategoryType, TransactionType
from app.services.import_service import CategoryAction, DuplicateSource


class PreviewRow(BaseModel):
    """One row as it was read, shown so the reading can be checked."""

    model_config = ConfigDict(from_attributes=True)

    line_number: int
    date: date_type
    amount: MoneyOut
    transaction_type: TransactionType
    category_name: str | None
    description: str | None
    payment_method: str | None


class RowProblemOut(BaseModel):
    """One reason one row cannot be imported.

    The line number is the line in the file, so "row 412" means the same thing
    to the user's spreadsheet as it does here.
    """

    model_config = ConfigDict(from_attributes=True)

    line_number: int
    column: str
    value: str
    message: str


class DuplicateOut(BaseModel):
    """A row that already exists, and where it already exists."""

    model_config = ConfigDict(from_attributes=True)

    line_number: int
    date: date_type
    amount: MoneyOut
    description: str
    #: Whether it repeats an earlier row in this file or one already recorded.
    source: DuplicateSource


class CategoryPlanOut(BaseModel):
    """One category name the file used, and what will happen to it."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    category_type: CategoryType
    action: CategoryAction
    #: How many rows use it, so a name worth correcting can be told from a
    #: name used once.
    rows: int
    category_id: int | None


class ImportPreview(BaseModel):
    """Everything the import would do, having done none of it."""

    #: What the file holds, and what would come of it.
    total_rows: int
    would_import: int
    failed_rows: int
    duplicate_rows: int

    #: Empty when the file is ready to import. Anything in here is a sentence
    #: naming a count and what to do about it, and the import will refuse.
    blockers: list[str]

    #: Rows whose date would be a different day read the other way round. Not
    #: an error — a warning that a choice was made on the user's behalf.
    ambiguous_dates: int
    #: Which encoding actually read the file, so a mangled description in the
    #: sample has a visible cause.
    encoding: str
    #: Which fields were recognised in the header row.
    columns: list[str]

    sample: list[PreviewRow]
    problems: list[RowProblemOut]
    duplicates: list[DuplicateOut]
    categories: list[CategoryPlanOut]

    #: Send this back with the file to import it. It fingerprints the file
    #: *and* the options, so an import can only ever apply what was previewed.
    digest: str


class ImportResult(BaseModel):
    """What an import actually did."""

    imported: int
    skipped_duplicates: int
    skipped_invalid: int
    created_categories: list[str]
    #: The range the imported rows cover, so the client can say what changed
    #: without asking for it back.
    first_date: date_type | None
    last_date: date_type | None
