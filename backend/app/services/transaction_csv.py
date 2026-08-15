"""The CSV format transactions are read from and written to.

Pure: text in, values out. No session, no clock, no HTTP — the same shape as
`budget_utilisation`, `billing_cycle`, `insight_rules` and `recurrence`, and
for the same reason. Every decision below can be wrong on its own, and a wrong
one silently changes what somebody's money says.

Reading a spreadsheet is not parsing a data format; it is guessing. This
module's job is to guess as little as it can, and to be loud when it cannot
guess at all.

**Dates are stated, never inferred.** `03/04/2026` is the third of April in
Dhaka and the fourth of March in Detroit, and nothing in the file says which.
The caller states the order and a value that does not fit it is refused rather
than reinterpreted. Rows that *would* read as a different day under the
opposite order are counted, so the preview can say "14 of these dates read
differently the other way round" instead of leaving the user to find out in
six months.

**Amounts are parsed deliberately.** `1,234.56`, `1.234,56`, `(50.00)`,
`৳1 234`, `-50`, `50 BDT` and `50-` all turn up in real exports and all mean
something definite. A third decimal place does not: money here has two, so
`12.3456` is refused rather than quietly rounded into disagreeing with a bank
statement (ADR-003).

**Direction is never assumed.** A row says which way money moved, either in a
type column or through the sign of its amount. A bare `500.00` with neither is
refused, because "probably an expense" is a guess about somebody's finances.

**What is written can be read back.** `read_csv(write_csv(rows))` returns the
same values, which is the only test that covers both halves at once.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from app.core.money import MONEY_DECIMAL_PLACES, quantise
from app.models.enums import TransactionType

# ─── Limits ───────────────────────────────────────────────────────────────

#: The most rows one file may carry. Not a technical ceiling — the import runs
#: comfortably past it — but a bound on how much a single mistaken click can
#: put into an account before anybody looks at the result.
MAX_ROWS = 5000

#: Matching the columns these values are stored in.
MAX_DESCRIPTION_LENGTH = 255
MAX_PAYMENT_METHOD_LENGTH = 50
MAX_CATEGORY_NAME_LENGTH = 80

#: DECIMAL(14,2) leaves twelve digits in front of the point.
MAX_AMOUNT_DIGITS = 12

#: Characters Excel and LibreOffice treat as the start of a formula rather than
#: as text. See `escape_formula`.
FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")

#: A byte-order mark. Written so that Excel opens the export as UTF-8 rather
#: than as the machine's local codepage — which is what turns "৳" and "Müller"
#: into rubble — and stripped when reading, since a file that has been through
#: Excel will have one whether or not we put it there.
BOM = "﻿"


class CsvFormatError(Exception):
    """The file cannot be read at all.

    Distinct from a row problem: this is "there is no date column", not "row 42
    has a bad date". One stops the whole import; the other is something the
    preview lists and the user decides about.
    """


class CellError(Exception):
    """One value could not be read.

    The message is written for whoever has to fix the file, and is shown
    verbatim beside the line number, so it says what was found and what was
    expected rather than naming a parser.
    """


# ─── Dates ────────────────────────────────────────────────────────────────


class DateOrder(StrEnum):
    """Which way round a file writes its dates.

    Asked for rather than detected. Detection is possible only when a file
    happens to contain a day past the twelfth, so it would work on most files
    and fail silently on the rest — and the ones it fails on are the ones where
    every date is ambiguous.
    """

    ISO = "iso"
    DAY_FIRST = "day_first"
    MONTH_FIRST = "month_first"


DATE_ORDER_EXAMPLES: dict[DateOrder, str] = {
    DateOrder.ISO: "2026-03-04",
    DateOrder.DAY_FIRST: "04/03/2026",
    DateOrder.MONTH_FIRST: "03/04/2026",
}

#: Two-digit years are read the way POSIX and Python's own `%y` read them:
#: 00–68 are this century, 69–99 the last. A named convention rather than a
#: guess — and refusing them outright would fail whole files over a formatting
#: choice the user did not make.
TWO_DIGIT_YEAR_PIVOT = 69

_DATE_SEPARATORS = re.compile(r"[/.\-\s]+")


def _date_parts(text: str) -> tuple[str, str, str]:
    """The three numbers in a date, as written."""
    parts = [part for part in _DATE_SEPARATORS.split(text.strip()) if part]
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise CellError(f"{text.strip()!r} is not a date.")
    return parts[0], parts[1], parts[2]


def _year(written: str) -> int:
    if len(written) == 4:
        return int(written)
    if len(written) == 2:
        value = int(written)
        return value + (2000 if value < TWO_DIGIT_YEAR_PIVOT else 1900)
    raise CellError(f"{written!r} is not a year.")


def parse_date(text: str, order: DateOrder) -> date_type:
    """One cell, as a calendar date, under a stated order."""
    value = (text or "").strip()
    if not value:
        raise CellError("A date is required.")

    first, second, third = _date_parts(value)

    if order is DateOrder.ISO:
        if len(first) != 4:
            raise CellError(f"{value!r} is not an ISO date — those start with a four-digit year.")
        year, month, day = _year(first), int(second), int(third)
    elif order is DateOrder.DAY_FIRST:
        day, month, year = int(first), int(second), _year(third)
    else:
        month, day, year = int(first), int(second), _year(third)

    try:
        return date_type(year, month, day)
    except ValueError:
        raise CellError(
            f"{value!r} is not a real date read as {DATE_ORDER_EXAMPLES[order]}."
        ) from None


def reads_both_ways(text: str, order: DateOrder) -> bool:
    """Whether this date would be a *different day* under the opposite order.

    `05/06/2026` would; `20/06/2026` would not, because there is no twentieth
    month. Counting these is what lets the preview warn that a choice was made
    on the user's behalf, rather than presenting a reading as a fact.
    """
    if order is DateOrder.ISO:
        return False
    try:
        written_first, written_second, _ = _date_parts(text)
    except CellError:
        return False
    first, second = int(written_first), int(written_second)
    return first != second and 1 <= first <= 12 and 1 <= second <= 12


# ─── Amounts ──────────────────────────────────────────────────────────────

#: Everything that is not a digit, a separator or a sign. Currency symbols and
#: codes — "৳", "$", "BDT", "Tk" — are noise around the number, not part of it.
_AMOUNT_NOISE = re.compile(r"[^\d.,()+\-]")

#: Unicode minus and en-dash, both of which spreadsheets emit and neither of
#: which is a hyphen. Stripped as noise, they would turn an expense into
#: income.
_MINUS_LOOKALIKES = str.maketrans({"−": "-", "–": "-", "—": "-"})


def _decimal_text(cleaned: str) -> str:
    """Work out which of `.` and `,` is the decimal point, and drop the other.

    With both present, the *last* one is the decimal point: `1,234.56` and
    `1.234,56` are the same amount written by two conventions, and in each the
    other separator groups thousands.

    With one present the case that matters is a group of exactly three digits.
    `1,234` could be one thousand two hundred and thirty-four or, read the
    other way, one and a bit. Money has two decimal places, so three digits
    after the separator can only be grouping — stated here rather than left to
    whichever branch happens to run.
    """
    last_dot = cleaned.rfind(".")
    last_comma = cleaned.rfind(",")

    if last_dot >= 0 and last_comma >= 0:
        if last_dot > last_comma:
            return cleaned.replace(",", "")
        return cleaned.replace(".", "").replace(",", ".")

    separator = "." if last_dot >= 0 else ("," if last_comma >= 0 else "")
    if not separator:
        return cleaned
    if cleaned.count(separator) > 1:
        # 1.234.567 — repeated, so it cannot be a decimal point.
        return cleaned.replace(separator, "")

    head, _, tail = cleaned.partition(separator)
    if len(tail) == 3:
        return head + tail
    return f"{head}.{tail}"


def parse_amount(text: str) -> Decimal:
    """One cell, as a signed amount.

    Signed on purpose. The caller decides what a negative means — here it only
    records that the file said the money went the other way.
    """
    raw = (text or "").strip()
    if not raw:
        raise CellError("An amount is required.")

    cleaned = _AMOUNT_NOISE.sub("", raw.translate(_MINUS_LOOKALIKES))

    # Accounting parentheses: (50.00) is minus fifty.
    negative = "(" in cleaned and ")" in cleaned
    cleaned = cleaned.replace("(", "").replace(")", "")
    # A trailing minus is as common as a leading one in spreadsheet exports.
    negative = negative or cleaned.startswith("-") or cleaned.endswith("-")
    cleaned = cleaned.strip("+-")

    if not any(character.isdigit() for character in cleaned):
        raise CellError(f"{raw!r} is not an amount.")

    try:
        value = Decimal(_decimal_text(cleaned))
    except InvalidOperation:
        raise CellError(f"{raw!r} is not an amount.") from None

    places = -int(value.as_tuple().exponent)
    if places > MONEY_DECIMAL_PLACES:
        raise CellError(
            f"{raw!r} has more than {MONEY_DECIMAL_PLACES} decimal places. "
            "Rounding it here would put the total out of step with the statement it came from."
        )
    if value >= Decimal(10) ** MAX_AMOUNT_DIGITS:
        raise CellError(f"{raw!r} is too large to store.")
    if value == 0:
        raise CellError("An amount must be more than zero.")

    return -quantise(value) if negative else quantise(value)


# ─── Direction ────────────────────────────────────────────────────────────

#: What a file might call each direction. Every word here is unambiguous on its
#: own; anything else is refused rather than approximated, because guessing
#: wrong reverses the sign of a figure the user will never re-check.
TYPE_WORDS: dict[str, TransactionType] = {
    "income": TransactionType.INCOME,
    "in": TransactionType.INCOME,
    "inflow": TransactionType.INCOME,
    "credit": TransactionType.INCOME,
    "cr": TransactionType.INCOME,
    "deposit": TransactionType.INCOME,
    "received": TransactionType.INCOME,
    "expense": TransactionType.EXPENSE,
    "out": TransactionType.EXPENSE,
    "outflow": TransactionType.EXPENSE,
    "debit": TransactionType.EXPENSE,
    "dr": TransactionType.EXPENSE,
    "withdrawal": TransactionType.EXPENSE,
    "payment": TransactionType.EXPENSE,
    "paid": TransactionType.EXPENSE,
    "purchase": TransactionType.EXPENSE,
    "spend": TransactionType.EXPENSE,
}


def parse_type(text: str) -> TransactionType | None:
    """The direction a row states, or None if it states none."""
    value = (text or "").strip().lower()
    if not value:
        return None
    try:
        return TYPE_WORDS[value]
    except KeyError:
        raise CellError(f"{text.strip()!r} is not a direction. Use income or expense.") from None


# ─── Columns ──────────────────────────────────────────────────────────────

DATE = "date"
AMOUNT = "amount"
TYPE = "type"
CATEGORY = "category"
DESCRIPTION = "description"
PAYMENT_METHOD = "payment_method"

#: Header names this reader recognises. Matched after normalising, so "Payment
#: Method", "payment_method" and "PAYMENT-METHOD" are all the same column.
#:
#: Kept to names that can only mean one thing. A synonym list long enough to
#: cover every bank turns into a list that matches the wrong column on one of
#: them, and mapping "Balance" onto "Amount" would import an account balance as
#: a purchase.
COLUMN_SYNONYMS: dict[str, frozenset[str]] = {
    DATE: frozenset({"date", "transaction date", "posted date", "posting date", "value date"}),
    AMOUNT: frozenset({"amount", "value"}),
    TYPE: frozenset({"type", "transaction type", "direction", "kind"}),
    CATEGORY: frozenset({"category", "category name"}),
    DESCRIPTION: frozenset(
        {
            "description",
            "details",
            "detail",
            "narrative",
            "particulars",
            "memo",
            "note",
            "notes",
            "merchant",
            "payee",
        }
    ),
    PAYMENT_METHOD: frozenset({"payment method", "method", "paid with", "mode"}),
}

#: The columns a file cannot do without. `category` is required as well, unless
#: the caller supplies one to fall back on — `transactions.category_id` is NOT
#: NULL and there is no "uncategorised" row to hide behind (ADR-006).
REQUIRED_COLUMNS = (DATE, AMOUNT)


def normalise_header(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def map_columns(headers: Sequence[str]) -> dict[str, int]:
    """Which column index holds which field.

    First match wins, so a file with both "Description" and "Memo" uses the
    first of them rather than whichever the dictionary happened to iterate to.
    """
    found: dict[str, int] = {}
    for index, header in enumerate(headers):
        name = normalise_header(header)
        for column, synonyms in COLUMN_SYNONYMS.items():
            if name in synonyms and column not in found:
                found[column] = index
                break
    return found


# ─── Formula injection ────────────────────────────────────────────────────


def escape_formula(text: str) -> str:
    """Stop a spreadsheet from executing an exported description.

    A description of `=1+1` is text here and a formula the moment the export is
    opened in Excel — and `=HYPERLINK(...)` or a DDE call is the same trick
    pointed somewhere worse. The mitigation is a leading apostrophe, which
    Excel eats and treats the rest as text.

    `unescape_formula` puts it back, so exporting and re-importing returns the
    description the user actually wrote rather than one with a quote glued to
    the front.
    """
    return f"'{text}" if text.startswith(FORMULA_LEADERS) else text


def unescape_formula(text: str) -> str:
    """Undo `escape_formula`, and nothing else.

    Only an apostrophe standing in front of a formula character is removed. A
    description that genuinely begins `'twas` keeps its quote.
    """
    if text.startswith("'") and text[1:].startswith(FORMULA_LEADERS):
        return text[1:]
    return text


# ─── Reading ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedRow:
    """One row of a file, read successfully.

    `amount` is positive; direction lives in `transaction_type`, exactly as it
    does in the database. A row that arrived as `-250.00` is an expense of
    250.00 here, and the sign is not carried any further.
    """

    line_number: int
    date: date_type
    amount: Decimal
    transaction_type: TransactionType
    #: None only when the file has no category column and the caller supplied a
    #: fallback.
    category_name: str | None
    description: str | None
    payment_method: str | None

    @property
    def duplicate_key(self) -> tuple[date_type, Decimal, TransactionType, str] | None:
        """What would make this the same row as another — or None.

        A row with no description has no key, and is therefore never called a
        duplicate. Two undescribed 250.00 expenses on one day are genuinely
        indistinguishable from the same charge imported twice, and the
        asymmetry decides it the way ADR-031 decides merchant matching: a
        duplicate that slips through is a visible extra row anybody can delete,
        while a row wrongly skipped is data silently lost.
        """
        if not self.description:
            return None
        return (
            self.date,
            self.amount,
            self.transaction_type,
            " ".join(self.description.lower().split()),
        )


@dataclass(frozen=True)
class RowProblem:
    """One reason one row cannot be imported."""

    line_number: int
    column: str
    value: str
    message: str


@dataclass(frozen=True)
class ReadResult:
    """Everything reading a file produced."""

    #: The fields that were found, so the preview can say what it recognised.
    columns: tuple[str, ...]
    rows: tuple[ParsedRow, ...]
    problems: tuple[RowProblem, ...]
    #: How many rows failed. Not `len(problems)` — one row can be wrong in
    #: several ways, and reporting all of them saves a second round trip.
    failed_rows: int
    #: Rows whose date would read as a different day under the opposite order.
    ambiguous_dates: int

    @property
    def total_rows(self) -> int:
        return len(self.rows) + self.failed_rows


#: Delimiters worth considering. Semicolon files come from every European
#: spreadsheet, where the comma is already the decimal point.
DELIMITERS = (",", ";", "\t", "|")


def detect_delimiter(header_line: str) -> str:
    """Which character separates the fields.

    Decided from the header line by counting, rather than with `csv.Sniffer`,
    which also tries to infer quoting and gets it wrong on short files. The
    header is the one line guaranteed to hold no free text, so counting there
    is safe: a description containing a semicolon cannot vote.
    """
    counts = {delimiter: header_line.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] else ","


def _cell(row: Sequence[str], columns: dict[str, int], name: str) -> str:
    index = columns.get(name)
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _text_cell(row: Sequence[str], columns: dict[str, int], name: str) -> str | None:
    value = unescape_formula(_cell(row, columns, name))
    return " ".join(value.split()) or None


def read_csv(
    text: str,
    *,
    date_order: DateOrder,
    category_required: bool = True,
) -> ReadResult:
    """Read a whole file, keeping the rows that parsed and why the rest did not.

    Nothing is refused wholesale for the sake of one bad row: the caller shows
    the problems and the user decides. What *is* refused wholesale is a file
    with no usable header, because there is then no question of which column
    meant what.
    """
    body = text.removeprefix(BOM)
    if not body.strip():
        raise CsvFormatError("The file is empty.")

    first_line = body.splitlines()[0]
    reader = csv.reader(io.StringIO(body, newline=""), delimiter=detect_delimiter(first_line))

    try:
        headers = next(reader)
    except StopIteration:  # pragma: no cover - guarded by the emptiness check
        raise CsvFormatError("The file is empty.") from None

    columns = map_columns(headers)
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if category_required and CATEGORY not in columns:
        missing.append(CATEGORY)
    if missing:
        raise CsvFormatError(
            f"The file needs a {' and a '.join(missing)} column. "
            f"Its first row reads: {', '.join(headers) or '(nothing)'}."
        )

    rows: list[ParsedRow] = []
    problems: list[RowProblem] = []
    failed = 0
    ambiguous = 0

    for raw_row in reader:
        if not any(cell.strip() for cell in raw_row):
            # A trailing blank line is not a row anybody wrote.
            continue

        if len(rows) + failed >= MAX_ROWS:
            raise CsvFormatError(
                f"The file has more than {MAX_ROWS:,} rows. Split it and import the parts."
            )

        line = reader.line_num
        if reads_both_ways(_cell(raw_row, columns, DATE), date_order):
            ambiguous += 1

        row, row_problems = _read_row(raw_row, columns, line, date_order, category_required)
        if row is None:
            failed += 1
            problems.extend(row_problems)
        else:
            rows.append(row)

    return ReadResult(
        columns=tuple(sorted(columns)),
        rows=tuple(rows),
        problems=tuple(problems),
        failed_rows=failed,
        ambiguous_dates=ambiguous,
    )


def _read_row(
    raw_row: Sequence[str],
    columns: dict[str, int],
    line: int,
    date_order: DateOrder,
    category_required: bool,
) -> tuple[ParsedRow | None, list[RowProblem]]:
    """One row: either a value, or every reason it is not one."""
    problems: list[RowProblem] = []

    def note(column: str, message: str) -> None:
        problems.append(
            RowProblem(
                line_number=line,
                column=column,
                value=_cell(raw_row, columns, column),
                message=message,
            )
        )

    day: date_type | None = None
    try:
        day = parse_date(_cell(raw_row, columns, DATE), date_order)
    except CellError as exc:
        note(DATE, str(exc))

    signed: Decimal | None = None
    try:
        signed = parse_amount(_cell(raw_row, columns, AMOUNT))
    except CellError as exc:
        note(AMOUNT, str(exc))

    stated: TransactionType | None = None
    type_readable = True
    try:
        stated = parse_type(_cell(raw_row, columns, TYPE))
    except CellError as exc:
        type_readable = False
        note(TYPE, str(exc))

    # Only worth reconciling when both halves were readable: a row whose type
    # cell says "misc" has already been told what is wrong with it, and adding
    # "this row does not say which way the money went" on top would be the same
    # complaint twice.
    direction: TransactionType | None = None
    if signed is not None and type_readable:
        direction, complaint = resolve_direction(stated, signed)
        if complaint:
            note(AMOUNT, complaint)

    category = _cell(raw_row, columns, CATEGORY) or None
    if category_required and not category:
        note(CATEGORY, "Every row needs a category.")
    elif category and len(category) > MAX_CATEGORY_NAME_LENGTH:
        note(CATEGORY, f"A category name is at most {MAX_CATEGORY_NAME_LENGTH} characters.")

    description = _text_cell(raw_row, columns, DESCRIPTION)
    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        note(DESCRIPTION, f"A description is at most {MAX_DESCRIPTION_LENGTH} characters.")

    method = _text_cell(raw_row, columns, PAYMENT_METHOD)
    if method and len(method) > MAX_PAYMENT_METHOD_LENGTH:
        note(PAYMENT_METHOD, f"A payment method is at most {MAX_PAYMENT_METHOD_LENGTH} characters.")

    if problems or day is None or signed is None or direction is None:
        return None, problems

    return (
        ParsedRow(
            line_number=line,
            date=day,
            amount=abs(signed),
            transaction_type=direction,
            category_name=category,
            description=description,
            payment_method=method,
        ),
        [],
    )


#: What a row's direction turned out to be, and what to complain about if it
#: could not be worked out.
NO_DIRECTION_STATED = (
    "This row does not say whether the money came in or went out. "
    "Add a type column, or write money going out with a minus sign."
)
DIRECTION_CONTRADICTED = (
    "The amount is negative but the row is marked as income. "
    "One of the two is wrong, and this reader will not choose."
)


def resolve_direction(
    stated: TransactionType | None, signed: Decimal
) -> tuple[TransactionType | None, str]:
    """Reconcile what a row says with what its sign says.

    Returns the direction and an empty complaint, or None and the reason.

    Three cases, and the third is the one worth stating: a row marked income
    while carrying a negative amount is not a row to pick a winner for.
    Something is wrong with the file, and either reading puts a figure into the
    account that the file does not support.
    """
    if stated is None:
        if signed < 0:
            return TransactionType.EXPENSE, ""
        return None, NO_DIRECTION_STATED

    if signed < 0 and stated is TransactionType.INCOME:
        return None, DIRECTION_CONTRADICTED

    return stated, ""


# ─── Writing ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExportRow:
    """One transaction, as the exporter sees it.

    A plain value rather than an ORM row, so this module stays testable without
    a database and cannot accidentally trigger a lazy load while writing.
    """

    date: date_type
    amount: Decimal
    transaction_type: TransactionType
    category: str
    description: str | None
    payment_method: str | None


EXPORT_HEADERS = ("Date", "Amount", "Type", "Category", "Description", "Payment method")


def write_csv(rows: Iterable[ExportRow], *, include_bom: bool = True) -> str:
    """Every row, as a CSV document.

    Amounts are written as plain decimal text — no thousands separators, no
    currency symbol, two places always — because the file is data before it is
    a report, and a reader should not have to undo formatting to get a number
    back. Dates are ISO for the same reason: it is the one order that cannot be
    read two ways.

    Free text goes through `escape_formula`, so opening the export in a
    spreadsheet cannot execute a description somebody typed.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(EXPORT_HEADERS)

    for row in rows:
        writer.writerow(
            [
                row.date.isoformat(),
                format(quantise(row.amount), "f"),
                str(row.transaction_type),
                escape_formula(row.category),
                escape_formula(row.description or ""),
                escape_formula(row.payment_method or ""),
            ]
        )

    return (BOM if include_bom else "") + buffer.getvalue()


# ─── Fingerprinting ───────────────────────────────────────────────────────


def content_digest(content: bytes, options: str) -> str:
    """A fingerprint of exactly what was previewed.

    The commit sends this back with the file. If either the bytes or the
    options have changed since the preview, the fingerprint will not match and
    the import is refused — which is what makes "you are importing what you
    were shown" a checkable claim rather than a hope. The options are in it
    because previewing with day-first dates and then importing with month-first
    would otherwise write a set of rows nobody ever looked at.
    """
    digest = hashlib.sha256()
    digest.update(content)
    digest.update(b"\x00")
    digest.update(options.encode("utf-8"))
    return digest.hexdigest()


__all__ = [
    "AMOUNT",
    "BOM",
    "CATEGORY",
    "DATE",
    "DESCRIPTION",
    "MAX_ROWS",
    "PAYMENT_METHOD",
    "TYPE",
    "CellError",
    "CsvFormatError",
    "DateOrder",
    "ExportRow",
    "ParsedRow",
    "ReadResult",
    "RowProblem",
    "content_digest",
    "detect_delimiter",
    "escape_formula",
    "map_columns",
    "parse_amount",
    "parse_date",
    "parse_type",
    "read_csv",
    "reads_both_ways",
    "resolve_direction",
    "unescape_formula",
    "write_csv",
]
