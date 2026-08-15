"""CSV import and export endpoints.

Three routes, and the shape of them is the design:

  * `GET  /csv/transactions` — the whole filtered set, as a file;
  * `POST /csv/preview`      — what an import *would* do. Writes nothing;
  * `POST /csv/import`       — do it, given the fingerprint the preview returned.

Import is two requests rather than one on purpose. A single endpoint that
parsed and wrote in one go would have to decide by itself what to do about an
unreadable row or an unrecognised category, and every such decision is one the
user should be shown before it is made. Splitting them means the second request
carries a fingerprint of the first, so an import can only apply a file somebody
has actually looked at.

These live under their own `/csv` prefix rather than on the transactions
router. Path order matters in FastAPI — `/transactions/{transaction_id}` is
declared there, and a later-registered `/transactions/export` would be handed
to that `int` path parameter and rejected before reaching its own handler. A
separate prefix removes the trap instead of documenting it.

The handlers are `def`, not `async def`, like every other route here
(ADR-002) — so the upload is read through `file.file`, the plain synchronous
object underneath `UploadFile`, and the whole thing runs in FastAPI's
threadpool.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile

from app.api.v1.deps import CurrentUser, SessionDep

# The export takes exactly the filters the list takes, from the same
# declarations. Restating them here would let "export what I am looking at"
# quietly come to mean something else the first time one of them changed.
from app.api.v1.transactions import (
    AmountMax,
    AmountMin,
    CategoryFilter,
    DateFrom,
    DateTo,
    MethodFilter,
    Search,
    TypeFilter,
)
from app.core.exceptions import ValidationFailed
from app.repositories.transaction_repository import TransactionFilters
from app.schemas.csv_io import (
    CategoryPlanOut,
    DuplicateOut,
    ImportPreview,
    ImportResult,
    PreviewRow,
    RowProblemOut,
)
from app.services.import_service import (
    MAX_FILE_BYTES,
    SAMPLE_SIZE,
    ImportOptions,
    ImportPlan,
    ImportService,
    UnknownCategoryPolicy,
)
from app.services.transaction_csv import DateOrder

router = APIRouter(prefix="/csv", tags=["csv"])

CsvFile = Annotated[UploadFile, File(description="A CSV file of transactions.")]

DateOrderParam = Annotated[
    DateOrder,
    Query(
        description="How the file writes its dates. Asked for rather than guessed: "
        "`03/04/2026` is two different days depending on where the file came from.",
    ),
]
UnknownCategories = Annotated[
    UnknownCategoryPolicy,
    Query(description="What to do about category names this account does not have."),
]
DefaultCategory = Annotated[
    int | None,
    Query(
        gt=0,
        description="Where to file rows with no category of their own. Also what makes a "
        "file with no category column importable at all.",
    ),
]
SkipDuplicates = Annotated[
    bool,
    Query(description="Leave out rows that repeat something already recorded."),
]
SkipInvalid = Annotated[
    bool,
    Query(description="Import the rows that could be read and leave out the rest."),
]
Digest = Annotated[
    str,
    Query(
        min_length=64,
        max_length=64,
        description="The `digest` from the preview of this exact file and these exact options.",
    ),
]


def _options(
    date_order: DateOrder,
    unknown_categories: UnknownCategoryPolicy,
    default_category_id: int | None,
    skip_duplicates: bool,
    skip_invalid: bool,
) -> ImportOptions:
    return ImportOptions(
        date_order=date_order,
        unknown_categories=unknown_categories,
        default_category_id=default_category_id,
        skip_duplicates=skip_duplicates,
        skip_invalid=skip_invalid,
    )


def _read_upload(file: UploadFile) -> bytes:
    """The uploaded bytes, refusing anything implausible for a CSV.

    One byte past the limit is enough to know: the file is never held in memory
    at its full size just to be told it is too large.
    """
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValidationFailed(
            f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. "
            "A transaction export is text, so a file this size is probably not one."
        )
    if not content:
        raise ValidationFailed("That file is empty.")
    return content


# ─── Export ───────────────────────────────────────────────────────────────


@router.get(
    "/transactions",
    summary="Export transactions as CSV",
    response_class=Response,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "Every matching transaction, oldest first.",
        }
    },
)
def export_transactions(
    current_user: CurrentUser,
    session: SessionDep,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    transaction_type: TypeFilter = None,
    category_id: CategoryFilter = None,
    payment_method: MethodFilter = None,
    amount_min: AmountMin = None,
    amount_max: AmountMax = None,
    search: Search = None,
) -> Response:
    """Download the filtered transactions as a CSV file.

    Not paginated: an export is the whole matching set by definition, and a
    page of one would be a quietly truncated file that looks complete.

    Amounts are plain decimal text with no thousands separator and no currency
    symbol, and dates are ISO — the file is data before it is a report, and
    both choices are what let it be read straight back in.
    """
    filters = TransactionFilters(
        date_from=date_from,
        date_to=date_to,
        transaction_type=transaction_type,
        category_id=category_id,
        payment_method=payment_method,
        amount_min=amount_min,
        amount_max=amount_max,
        search=search,
    )

    document = ImportService(session).export(current_user.id, filters)
    filename = f"finsight-transactions-{date_type.today():%Y-%m-%d}.csv"

    return Response(
        content=document.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Import ───────────────────────────────────────────────────────────────


@router.post(
    "/preview",
    response_model=ImportPreview,
    summary="What an import would do",
    responses={422: {"description": "The file cannot be read at all"}},
)
def preview_import(
    current_user: CurrentUser,
    session: SessionDep,
    file: CsvFile,
    date_order: DateOrderParam = DateOrder.ISO,
    unknown_categories: UnknownCategories = UnknownCategoryPolicy.REFUSE,
    default_category_id: DefaultCategory = None,
    skip_duplicates: SkipDuplicates = True,
    skip_invalid: SkipInvalid = False,
) -> ImportPreview:
    """Read a file and report everything importing it would do. Writes nothing.

    A blocked preview is a successful response, not an error: the blockers are
    the reason the user is being shown this at all, and the rest of the report
    is what they need in order to clear them. Only a file that cannot be read
    as a file — no date column, no rows — is a 422.
    """
    options = _options(
        date_order, unknown_categories, default_category_id, skip_duplicates, skip_invalid
    )
    plan = ImportService(session).plan(current_user.id, _read_upload(file), options)

    return _as_preview(plan)


@router.post(
    "/import",
    response_model=ImportResult,
    summary="Import a previewed file",
    responses={
        409: {"description": "The file or the options are not the ones that were previewed"},
        422: {"description": "The file cannot be imported as it stands"},
    },
)
def commit_import(
    current_user: CurrentUser,
    session: SessionDep,
    file: CsvFile,
    digest: Digest,
    date_order: DateOrderParam = DateOrder.ISO,
    unknown_categories: UnknownCategories = UnknownCategoryPolicy.REFUSE,
    default_category_id: DefaultCategory = None,
    skip_duplicates: SkipDuplicates = True,
    skip_invalid: SkipInvalid = False,
) -> ImportResult:
    """Apply a previewed file, in one database transaction.

    `digest` is what makes this safe to offer. It comes from the preview and
    covers the file *and* the options, so a file cannot be imported without
    having been read back to the user first, and a file previewed one way
    cannot be imported another.

    Every row lands or none does. A file that half imports leaves an account in
    a state nobody chose and nobody can easily undo.
    """
    options = _options(
        date_order, unknown_categories, default_category_id, skip_duplicates, skip_invalid
    )
    outcome = ImportService(session).commit(
        current_user.id, _read_upload(file), options, digest
    )

    return ImportResult(
        imported=outcome.imported,
        skipped_duplicates=outcome.skipped_duplicates,
        skipped_invalid=outcome.skipped_invalid,
        created_categories=list(outcome.created_categories),
        first_date=outcome.first_date,
        last_date=outcome.last_date,
    )


def _as_preview(plan: ImportPlan) -> ImportPreview:
    """Turn a plan into its response.

    Samples rather than lists in full. A ready set can be five thousand rows,
    and a response that repeats the file back is not a summary of it — ten rows
    is enough to see that the dates and amounts were read the way they were
    meant, and the counts beside them say how many more there are.

    Categories are *not* sampled. There are a few dozen of them at most, and
    each one is a decision the user has to make rather than an example of one.
    """
    return ImportPreview(
        total_rows=plan.total_rows,
        would_import=plan.would_import,
        failed_rows=plan.failed_rows,
        duplicate_rows=len(plan.duplicates),
        blockers=list(plan.blockers),
        ambiguous_dates=plan.ambiguous_dates,
        encoding=plan.encoding,
        columns=list(plan.columns),
        sample=[PreviewRow.model_validate(row) for row in plan.ready[:SAMPLE_SIZE]],
        problems=[RowProblemOut.model_validate(row) for row in plan.problems[:SAMPLE_SIZE]],
        duplicates=[DuplicateOut.model_validate(row) for row in plan.duplicates[:SAMPLE_SIZE]],
        categories=[CategoryPlanOut.model_validate(row) for row in plan.categories],
        digest=plan.digest,
    )
