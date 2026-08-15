"""Tests for reading and writing the transaction CSV format.

Pure functions, so these are three-line tests with no database between them —
the same arrangement as `test_recurrence.py` and for the same reason. What is
covered exhaustively here is every way a spreadsheet can write a number or a
date, because each one of those is a way to import somebody's money wrongly and
none of them is visible in a functional test: the row lands, it is just wrong.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.enums import TransactionType
from app.services.transaction_csv import (
    BOM,
    MAX_ROWS,
    CellError,
    CsvFormatError,
    DateOrder,
    ExportRow,
    detect_delimiter,
    escape_formula,
    map_columns,
    parse_amount,
    parse_date,
    parse_type,
    read_csv,
    reads_both_ways,
    resolve_direction,
    unescape_formula,
    write_csv,
)

HEADER = "Date,Amount,Type,Category,Description,Payment method"


def csv_text(*rows: str, header: str = HEADER) -> str:
    return "\n".join((header, *rows)) + "\n"


def read(*rows: str, order: DateOrder = DateOrder.ISO, **kwargs: object):
    return read_csv(csv_text(*rows), date_order=order, **kwargs)  # type: ignore[arg-type]


# ─── Amounts ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500", "500.00"),
        ("500.00", "500.00"),
        ("1234.56", "1234.56"),
        # Thousands separators, both conventions.
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1 234.56", "1234.56"),
        ("1,234,567.89", "1234567.89"),
        ("1.234.567,89", "1234567.89"),
        # Currency, before and after, symbol and code.
        ("৳1,234.56", "1234.56"),
        ("$50.00", "50.00"),
        ("50.00 BDT", "50.00"),
        ("Tk 500", "500.00"),
    ],
)
def test_amounts_are_read_however_the_spreadsheet_wrote_them(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("-50.00", "-50.00"),
        ("(50.00)", "-50.00"),
        ("50.00-", "-50.00"),
        ("−50.00", "-50.00"),  # unicode minus, which spreadsheets emit
        ("–50.00", "-50.00"),  # en dash, which they also emit
        ("(1,234.56)", "-1234.56"),
        ("+50.00", "50.00"),
    ],
)
def test_every_way_of_writing_a_negative_is_negative(text: str, expected: str) -> None:
    """A minus that reads as noise turns an expense into income."""
    assert parse_amount(text) == Decimal(expected)


def test_a_lone_group_of_three_digits_is_thousands_not_decimals() -> None:
    """`1,234` cannot be one and a bit: money has two decimal places."""
    assert parse_amount("1,234") == Decimal("1234.00")
    assert parse_amount("1.234") == Decimal("1234.00")


def test_a_lone_group_of_two_digits_is_decimals() -> None:
    assert parse_amount("1,50") == Decimal("1.50")
    assert parse_amount("1.50") == Decimal("1.50")


def test_a_repeated_separator_can_only_be_grouping() -> None:
    assert parse_amount("1.234.567") == Decimal("1234567.00")


def test_a_third_decimal_place_is_refused_rather_than_rounded() -> None:
    """Rounding it would put the import out of step with the statement."""
    with pytest.raises(CellError, match="decimal places"):
        parse_amount("12.3456")


@pytest.mark.parametrize("text", ["", "   ", "abc", "-", "n/a"])
def test_what_is_not_an_amount_is_refused(text: str) -> None:
    with pytest.raises(CellError):
        parse_amount(text)


def test_zero_is_not_an_amount() -> None:
    with pytest.raises(CellError, match="more than zero"):
        parse_amount("0.00")


def test_an_amount_too_large_for_the_column_is_refused() -> None:
    with pytest.raises(CellError, match="too large"):
        parse_amount("9999999999999.00")


# ─── Dates ────────────────────────────────────────────────────────────────


def test_the_same_text_is_two_different_days_under_two_orders() -> None:
    """The reason the order is asked for and never guessed."""
    assert parse_date("03/04/2026", DateOrder.DAY_FIRST) == date(2026, 4, 3)
    assert parse_date("03/04/2026", DateOrder.MONTH_FIRST) == date(2026, 3, 4)


@pytest.mark.parametrize("text", ["2026-03-04", "2026/03/04", "2026.03.04"])
def test_iso_dates_are_read_whatever_separates_them(text: str) -> None:
    assert parse_date(text, DateOrder.ISO) == date(2026, 3, 4)


def test_iso_refuses_a_date_that_does_not_start_with_a_year() -> None:
    with pytest.raises(CellError, match="ISO"):
        parse_date("04/03/2026", DateOrder.ISO)


def test_a_two_digit_year_follows_the_usual_convention() -> None:
    """00–68 this century, 69–99 the last, as POSIX and `%y` read them."""
    assert parse_date("04/03/26", DateOrder.DAY_FIRST) == date(2026, 3, 4)
    assert parse_date("04/03/99", DateOrder.DAY_FIRST) == date(1999, 3, 4)


def test_a_day_that_does_not_exist_is_refused() -> None:
    with pytest.raises(CellError, match="not a real date"):
        parse_date("31/02/2026", DateOrder.DAY_FIRST)


def test_reading_a_day_first_file_as_month_first_is_caught_not_shrugged() -> None:
    """`20/06/2026` has no twentieth month, so the wrong order fails loudly."""
    with pytest.raises(CellError):
        parse_date("20/06/2026", DateOrder.MONTH_FIRST)


@pytest.mark.parametrize("text", ["", "yesterday", "4 Mar 2026", "2026-03"])
def test_what_is_not_a_date_is_refused(text: str) -> None:
    with pytest.raises(CellError):
        parse_date(text, DateOrder.ISO)


def test_a_date_that_reads_both_ways_is_recognised_as_such() -> None:
    assert reads_both_ways("03/04/2026", DateOrder.DAY_FIRST) is True


def test_a_date_that_cannot_read_the_other_way_is_not_ambiguous() -> None:
    assert reads_both_ways("20/06/2026", DateOrder.DAY_FIRST) is False


def test_the_same_number_twice_is_not_ambiguous() -> None:
    """`04/04/2026` is the fourth of April either way round."""
    assert reads_both_ways("04/04/2026", DateOrder.DAY_FIRST) is False


def test_iso_is_never_ambiguous() -> None:
    assert reads_both_ways("2026-03-04", DateOrder.ISO) is False


# ─── Direction ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("income", TransactionType.INCOME),
        ("Credit", TransactionType.INCOME),
        ("CR", TransactionType.INCOME),
        ("deposit", TransactionType.INCOME),
        ("expense", TransactionType.EXPENSE),
        ("debit", TransactionType.EXPENSE),
        ("withdrawal", TransactionType.EXPENSE),
    ],
)
def test_direction_words_are_understood(word: str, expected: TransactionType) -> None:
    assert parse_type(word) is expected


def test_an_unrecognised_direction_is_refused_rather_than_guessed() -> None:
    with pytest.raises(CellError, match="not a direction"):
        parse_type("misc")


def test_no_direction_column_and_no_sign_is_refused() -> None:
    """"Probably an expense" is a guess about which way money moved."""
    direction, complaint = resolve_direction(None, Decimal("500.00"))

    assert direction is None
    assert "does not say" in complaint


def test_a_negative_amount_carries_the_direction_on_its_own() -> None:
    direction, complaint = resolve_direction(None, Decimal("-500.00"))

    assert direction is TransactionType.EXPENSE
    assert complaint == ""


def test_a_stated_direction_wins_over_an_unsigned_amount() -> None:
    direction, _ = resolve_direction(TransactionType.INCOME, Decimal("500.00"))

    assert direction is TransactionType.INCOME


def test_a_row_that_contradicts_itself_picks_no_winner() -> None:
    direction, complaint = resolve_direction(TransactionType.INCOME, Decimal("-500.00"))

    assert direction is None
    assert "will not choose" in complaint


# ─── Headers ──────────────────────────────────────────────────────────────


def test_headers_are_matched_however_they_are_punctuated() -> None:
    columns = map_columns(["Transaction Date", "AMOUNT", "payment_method", "Memo"])

    assert columns == {"date": 0, "amount": 1, "payment_method": 2, "description": 3}


def test_an_unrecognised_header_is_simply_not_mapped() -> None:
    assert map_columns(["Balance", "Reference number"]) == {}


def test_the_first_matching_header_wins() -> None:
    """A file with both Description and Memo uses the one it wrote first."""
    columns = map_columns(["Description", "Memo"])

    assert columns["description"] == 0


def test_a_file_without_a_date_column_cannot_be_read_at_all() -> None:
    with pytest.raises(CsvFormatError, match="date"):
        read_csv("Amount,Category\n5,Food\n", date_order=DateOrder.ISO)


def test_the_complaint_names_what_the_file_actually_had() -> None:
    """So the fix is visible without opening the file again."""
    with pytest.raises(CsvFormatError, match="Reference"):
        read_csv("Reference,Balance\n1,2\n", date_order=DateOrder.ISO)


def test_a_category_column_is_not_needed_when_one_is_supplied() -> None:
    result = read_csv(
        "Date,Amount,Type\n2026-03-04,500,expense\n",
        date_order=DateOrder.ISO,
        category_required=False,
    )

    assert len(result.rows) == 1
    assert result.rows[0].category_name is None


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(CsvFormatError, match="empty"):
        read_csv("   \n", date_order=DateOrder.ISO)


# ─── Delimiters ───────────────────────────────────────────────────────────


def test_a_semicolon_file_is_read_as_one() -> None:
    """Every European spreadsheet writes these, because the comma is taken."""
    result = read_csv(
        "Date;Amount;Type;Category\n2026-03-04;1.234,56;expense;Food\n",
        date_order=DateOrder.ISO,
    )

    assert result.rows[0].amount == Decimal("1234.56")


def test_the_delimiter_is_decided_from_the_header_line() -> None:
    assert detect_delimiter("Date;Amount;Category") == ";"
    assert detect_delimiter("Date,Amount,Category") == ","
    assert detect_delimiter("Date\tAmount\tCategory") == "\t"


def test_a_single_column_file_falls_back_to_a_comma() -> None:
    assert detect_delimiter("Date") == ","


# ─── Reading whole files ──────────────────────────────────────────────────


def test_a_good_row_becomes_a_value() -> None:
    result = read("2026-03-04,499.00,expense,Subscriptions,NETFLIX,bKash")

    assert result.failed_rows == 0
    row = result.rows[0]
    assert (row.date, row.amount, row.transaction_type) == (
        date(2026, 3, 4),
        Decimal("499.00"),
        TransactionType.EXPENSE,
    )
    assert (row.category_name, row.description, row.payment_method) == (
        "Subscriptions",
        "NETFLIX",
        "bKash",
    )


def test_the_sign_is_dropped_once_the_direction_is_known() -> None:
    """Amounts are stored positive; direction lives in the type (ADR-003)."""
    row = read("2026-03-04,-499.00,,Food,Lunch").rows[0]

    assert row.amount == Decimal("499.00")
    assert row.transaction_type is TransactionType.EXPENSE


def test_a_line_number_points_at_the_line_in_the_file() -> None:
    """So "row 3" means the same thing here as in the user's spreadsheet."""
    result = read(
        "2026-03-04,10.00,expense,Food,One",
        "not-a-date,10.00,expense,Food,Two",
    )

    assert result.problems[0].line_number == 3


def test_every_reason_a_row_failed_is_reported_at_once() -> None:
    """Reporting one at a time would mean a round trip per mistake."""
    result = read("not-a-date,not-an-amount,expense,Food,Bad")

    assert result.failed_rows == 1
    assert {problem.column for problem in result.problems} == {"date", "amount"}


def test_one_bad_row_does_not_lose_the_good_ones() -> None:
    result = read(
        "2026-03-04,10.00,expense,Food,One",
        "not-a-date,10.00,expense,Food,Two",
        "2026-03-06,30.00,expense,Food,Three",
    )

    assert [row.description for row in result.rows] == ["One", "Three"]
    assert result.failed_rows == 1
    assert result.total_rows == 3


def test_blank_lines_are_not_rows() -> None:
    body = csv_text("2026-03-04,10.00,expense,Food,One") + "\n\n"
    result = read_csv(body, date_order=DateOrder.ISO)

    assert result.total_rows == 1


def test_a_row_missing_a_category_is_reported_by_name() -> None:
    result = read("2026-03-04,10.00,expense,,One")

    assert result.problems[0].column == "category"


def test_ambiguous_dates_are_counted_not_refused() -> None:
    """A warning, not an error: a choice was made on the user's behalf."""
    result = read(
        "03/04/2026,10.00,expense,Food,One",
        "20/06/2026,10.00,expense,Food,Two",
        order=DateOrder.DAY_FIRST,
    )

    assert result.ambiguous_dates == 1
    assert result.failed_rows == 0


def test_a_description_too_long_for_the_column_is_reported() -> None:
    result = read(f"2026-03-04,10.00,expense,Food,{'x' * 300}")

    assert result.problems[0].column == "description"


def test_whitespace_around_values_is_not_data() -> None:
    row = read("  2026-03-04 ,  10.00 , expense , Food ,  Lunch   out  ").rows[0]

    assert row.category_name == "Food"
    assert row.description == "Lunch out"


def test_a_byte_order_mark_does_not_become_part_of_the_first_header() -> None:
    """Files that have been through Excel carry one whether we wrote it or not."""
    body = BOM + csv_text("2026-03-04,10.00,expense,Food,One")
    result = read_csv(body, date_order=DateOrder.ISO)

    assert len(result.rows) == 1


def test_a_file_past_the_row_limit_is_refused() -> None:
    rows = [f"2026-03-04,10.00,expense,Food,Row {index}" for index in range(MAX_ROWS + 1)]

    with pytest.raises(CsvFormatError, match="rows"):
        read(*rows)


# ─── Duplicate keys ───────────────────────────────────────────────────────


def test_two_identical_rows_share_a_key() -> None:
    first, second = read(
        "2026-03-04,10.00,expense,Food,Coffee",
        "2026-03-04,10.00,expense,Food,  COFFEE  ",
    ).rows

    assert first.duplicate_key == second.duplicate_key


def test_a_row_with_no_description_has_no_key() -> None:
    """Never called a duplicate: two undescribed 250.00 expenses on one day are
    indistinguishable from the same charge twice, and a row wrongly skipped is
    data silently lost."""
    row = read("2026-03-04,10.00,expense,Food,").rows[0]

    assert row.duplicate_key is None


def test_a_different_amount_is_a_different_row() -> None:
    first, second = read(
        "2026-03-04,10.00,expense,Food,Coffee",
        "2026-03-04,11.00,expense,Food,Coffee",
    ).rows

    assert first.duplicate_key != second.duplicate_key


# ─── Formula injection ────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["=1+1", "+SUM(A1)", "-2+3", "@SUM(A1)"])
def test_a_description_a_spreadsheet_would_execute_is_defused(text: str) -> None:
    """An exported description is text here and a formula in Excel."""
    assert escape_formula(text).startswith("'")


def test_ordinary_text_is_left_alone() -> None:
    assert escape_formula("Netflix") == "Netflix"


def test_defusing_is_undone_on_the_way_back_in() -> None:
    assert unescape_formula(escape_formula("=1+1")) == "=1+1"


def test_a_quote_that_is_part_of_the_text_survives() -> None:
    assert unescape_formula("'twas the season") == "'twas the season"


# ─── Writing ──────────────────────────────────────────────────────────────


def export_row(**overrides: object) -> ExportRow:
    fields: dict[str, object] = {
        "date": date(2026, 3, 4),
        "amount": Decimal("1234.50"),
        "transaction_type": TransactionType.EXPENSE,
        "category": "Food",
        "description": "Lunch",
        "payment_method": "Cash",
    }
    fields.update(overrides)
    return ExportRow(**fields)  # type: ignore[arg-type]


def test_the_export_names_its_columns() -> None:
    document = write_csv([export_row()])

    assert document.removeprefix(BOM).splitlines()[0].startswith("Date,Amount,Type")


def test_amounts_are_written_as_plain_decimal_text() -> None:
    """No thousands separator and no currency symbol: it is data, not a report."""
    document = write_csv([export_row()])

    assert "1234.50" in document
    assert "1,234.50" not in document


def test_dates_are_written_in_the_one_order_that_reads_only_one_way() -> None:
    assert "2026-03-04" in write_csv([export_row()])


def test_the_export_starts_with_a_byte_order_mark() -> None:
    """Without it Excel opens the file as the local codepage and mangles it."""
    assert write_csv([export_row()]).startswith(BOM)


def test_a_missing_description_is_an_empty_cell_not_the_word_none() -> None:
    document = write_csv([export_row(description=None, payment_method=None)])

    assert "None" not in document


def test_what_was_written_can_be_read_straight_back() -> None:
    """The one test that covers both halves at once."""
    written = [
        export_row(),
        export_row(
            date=date(2026, 1, 31),
            amount=Decimal("45000.00"),
            transaction_type=TransactionType.INCOME,
            category="Salary",
            description="Monthly salary",
            payment_method=None,
        ),
    ]

    read_back = read_csv(write_csv(written), date_order=DateOrder.ISO).rows

    assert len(read_back) == 2
    for original, parsed in zip(written, read_back, strict=True):
        assert parsed.date == original.date
        assert parsed.amount == original.amount
        assert parsed.transaction_type is original.transaction_type
        assert parsed.category_name == original.category
        assert parsed.description == original.description
        assert parsed.payment_method == original.payment_method


def test_a_defused_description_round_trips_unchanged() -> None:
    written = export_row(description="=HYPERLINK(\"http://example.com\")")

    read_back = read_csv(write_csv([written]), date_order=DateOrder.ISO).rows[0]

    assert read_back.description == written.description
