"""Tests for reviewing a CSV file before importing it.

The rule the service enforces has an interface half, and it is what most of
these check: **nothing can be imported that has not been read back to the user
first**. The import needs the fingerprint the preview returned, so there is no
sequence of clicks that writes an unexamined file — and changing any option
throws the fingerprint away, because a preview describes a file read a
particular way.

The API client is a stub. No backend runs here, and no file is read from disk.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from client.api.client import ApiError
from client.api.dto import (
    Category,
    CategoryPlan,
    DuplicateRow,
    ImportPreview,
    ImportResult,
    PreviewRow,
    RowProblem,
)
from client.widgets.import_dialog import ImportDialog

pytestmark = pytest.mark.gui

CATEGORIES = [
    Category(id=1, name="Food", category_type="expense", color="#c4472f"),
    Category(id=2, name="Salary", category_type="income", color="#1a7f4b"),
]

CONTENT = b"Date,Amount,Type,Category\n2026-03-04,499.00,expense,Food\n"


def sample_row(line: int = 2, day: date = date(2026, 3, 4)) -> PreviewRow:
    return PreviewRow(
        line_number=line,
        date=day,
        amount=Decimal("499.00"),
        transaction_type="expense",
        category_name="Food",
        description="NETFLIX",
        payment_method="bKash",
    )


def preview(
    *,
    would_import: int = 1,
    total_rows: int = 1,
    failed_rows: int = 0,
    duplicate_rows: int = 0,
    blockers: tuple[str, ...] = (),
    ambiguous_dates: int = 0,
    encoding: str = "utf-8-sig",
    sample: tuple[PreviewRow, ...] | None = None,
    problems: tuple[RowProblem, ...] = (),
    duplicates: tuple[DuplicateRow, ...] = (),
    categories: tuple[CategoryPlan, ...] = (),
    digest: str = "a" * 64,
) -> ImportPreview:
    return ImportPreview(
        total_rows=total_rows,
        would_import=would_import,
        failed_rows=failed_rows,
        duplicate_rows=duplicate_rows,
        blockers=blockers,
        ambiguous_dates=ambiguous_dates,
        encoding=encoding,
        columns=("amount", "category", "date", "type"),
        sample=(sample_row(),) if sample is None else sample,
        problems=problems,
        duplicates=duplicates,
        categories=categories,
        digest=digest,
    )


def result(imported: int = 1) -> ImportResult:
    return ImportResult(
        imported=imported,
        skipped_duplicates=0,
        skipped_invalid=0,
        created_categories=(),
        first_date=date(2026, 3, 4),
        last_date=date(2026, 3, 4),
    )


class StubApi:
    """Records what it was asked, and answers with whatever it was given."""

    def __init__(
        self,
        answer: ImportPreview | None = None,
        *,
        preview_error: ApiError | None = None,
        import_error: ApiError | None = None,
    ) -> None:
        self.answer = answer if answer is not None else preview()
        self.preview_error = preview_error
        self.import_error = import_error
        self.previews: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []

    def preview_import(self, content: bytes, **options: Any) -> ImportPreview:
        if self.preview_error is not None:
            raise self.preview_error
        self.previews.append({"content": content, **options})
        return self.answer

    def import_transactions(self, content: bytes, **options: Any) -> ImportResult:
        if self.import_error is not None:
            raise self.import_error
        self.imports.append({"content": content, **options})
        return result()


def make(qtbot, api: StubApi | None = None) -> tuple[ImportDialog, StubApi]:
    stub = api or StubApi()
    dialog = ImportDialog(
        CONTENT,
        api_client=stub,
        filename="statement.csv",
        categories=CATEGORIES,
        currency="BDT",
    )
    qtbot.addWidget(dialog)
    return dialog, stub


def texts(dialog: ImportDialog, name: str) -> list[str]:
    return [label.text() for label in dialog.findChildren(QLabel, name)]


def report_text(dialog: ImportDialog) -> str:
    return " ".join(label.text() for label in dialog.findChildren(QLabel))


# ─── Nothing is imported unchecked ────────────────────────────────────────


def test_opening_the_dialog_reads_nothing(qtbot) -> None:
    """Opening a file chooser must not be the same act as importing."""
    dialog, api = make(qtbot)

    assert api.previews == []
    assert api.imports == []
    assert dialog.preview is None


def test_the_import_button_starts_disabled(qtbot) -> None:
    dialog, _ = make(qtbot)

    assert dialog.import_button.isEnabled() is False
    assert dialog.import_button.text() == "Import"


def test_pressing_import_without_checking_does_nothing(qtbot) -> None:
    """Guarded in the method, not only by the disabled button: the button is an
    interface detail and this is the rule."""
    dialog, api = make(qtbot)

    dialog.run_import()

    assert api.imports == []
    assert dialog.result is None
    assert "Check the file first" in dialog.banner.text()


def test_checking_the_file_creates_nothing(qtbot) -> None:
    dialog, api = make(qtbot)

    dialog.check_file()

    assert len(api.previews) == 1
    assert api.imports == []


def test_a_checked_file_can_then_be_imported(qtbot) -> None:
    dialog, api = make(qtbot, StubApi(preview(would_import=12, total_rows=12)))

    dialog.check_file()

    assert dialog.import_button.isEnabled() is True
    assert dialog.import_button.text() == "Import 12 transactions"


def test_the_button_is_singular_for_one_row(qtbot) -> None:
    dialog, _ = make(qtbot, StubApi(preview(would_import=1)))

    dialog.check_file()

    assert dialog.import_button.text() == "Import 1 transaction"


def test_importing_sends_the_fingerprint_the_preview_returned(qtbot) -> None:
    """The mechanism that makes "you are importing what you were shown"
    something the server can enforce."""
    dialog, api = make(qtbot, StubApi(preview(digest="c" * 64)))

    dialog.check_file()
    dialog.run_import()

    assert api.imports[0]["digest"] == "c" * 64
    assert api.imports[0]["content"] == CONTENT


def test_a_successful_import_closes_the_dialog_with_its_outcome(qtbot) -> None:
    dialog, _ = make(qtbot)

    dialog.check_file()
    dialog.run_import()

    assert dialog.result is not None
    assert dialog.result.imported == 1
    assert dialog.isVisible() is False


# ─── Changing an option invalidates the preview ───────────────────────────


def test_changing_the_date_order_disables_the_import_again(qtbot) -> None:
    """A preview describes a file read a particular way. Once the order
    changes it describes nothing."""
    dialog, _ = make(qtbot)
    dialog.check_file()
    assert dialog.import_button.isEnabled() is True

    dialog.date_order.setCurrentIndex(1)

    assert dialog.import_button.isEnabled() is False
    assert "check the file again" in dialog.banner.text().lower()


def test_changing_a_checkbox_disables_the_import_again(qtbot) -> None:
    dialog, _ = make(qtbot)
    dialog.check_file()

    dialog.skip_invalid.setChecked(True)

    assert dialog.import_button.isEnabled() is False


def test_a_stale_report_says_so_rather_than_looking_current(qtbot) -> None:
    """Found by rendering it (ADR-012): the banner said the options had
    changed while the largest figure on the page went on claiming 412 rows
    would be imported."""
    dialog, _ = make(qtbot, StubApi(preview(would_import=412, total_rows=418)))
    dialog.check_file()

    dialog.date_order.setCurrentIndex(1)

    assert texts(dialog, "StaleTitle") == ["This report is out of date"]


def test_a_fresh_check_clears_the_stale_warning(qtbot) -> None:
    dialog, _ = make(qtbot)
    dialog.check_file()
    dialog.date_order.setCurrentIndex(1)

    dialog.check_file()

    assert texts(dialog, "StaleTitle") == []
    assert dialog.import_button.isEnabled() is True


def test_importing_a_stale_preview_is_refused_before_it_leaves(qtbot) -> None:
    """The server would refuse it too — the fingerprint covers the options —
    but being refused after pressing Import is a worse way to learn it."""
    dialog, api = make(qtbot)
    dialog.check_file()
    dialog.skip_duplicates.setChecked(False)

    dialog.run_import()

    assert api.imports == []


def test_the_options_are_sent_as_chosen(qtbot) -> None:
    dialog, api = make(qtbot)

    dialog.date_order.setCurrentIndex(2)
    dialog.unknown_categories.setCurrentIndex(1)
    dialog.default_category.setCurrentIndex(1)
    dialog.skip_invalid.setChecked(True)
    dialog.check_file()

    sent = api.previews[0]
    assert sent["date_order"] == "month_first"
    assert sent["unknown_categories"] == "create"
    assert sent["default_category_id"] == 1
    assert sent["skip_invalid"] is True
    assert sent["skip_duplicates"] is True


# ─── A file that will not import ──────────────────────────────────────────


def test_a_blocked_file_cannot_be_imported(qtbot) -> None:
    dialog, api = make(
        qtbot,
        StubApi(preview(would_import=0, blockers=("3 row(s) could not be read.",))),
    )

    dialog.check_file()
    dialog.run_import()

    assert dialog.import_button.isEnabled() is False
    assert api.imports == []


def test_a_blocked_file_still_shows_its_whole_report(qtbot) -> None:
    """The blockers are the reason the user is here; hiding the rest would
    leave them with a refusal and no way to act on it."""
    dialog, _ = make(
        qtbot,
        StubApi(
            preview(
                would_import=0,
                total_rows=4,
                failed_rows=1,
                blockers=("1 row(s) could not be read.",),
                problems=(
                    RowProblem(
                        line_number=12,
                        column="date",
                        value="04-13-2026",
                        message="'04-13-2026' is not a real date.",
                    ),
                ),
                categories=(
                    CategoryPlan(
                        name="Skydiving",
                        category_type="expense",
                        action="unknown",
                        rows=2,
                        category_id=None,
                    ),
                ),
            )
        ),
    )

    dialog.check_file()
    report = report_text(dialog)

    assert "1 row(s) could not be read." in report
    assert "Line 12" in report
    assert "Skydiving" in report
    assert "not in this account" in report


def test_a_file_that_cannot_be_read_at_all_says_why(qtbot) -> None:
    dialog, _ = make(
        qtbot, StubApi(preview_error=ApiError("The file needs a date column.", status_code=422))
    )

    dialog.check_file()

    assert "needs a date column" in dialog.banner.text()
    assert dialog.preview is None
    assert dialog.import_button.isEnabled() is False


def test_a_refused_import_keeps_the_dialog_open(qtbot) -> None:
    """Losing the report because the server refused would mean starting over."""
    dialog, _ = make(
        qtbot,
        StubApi(
            import_error=ApiError(
                "This file is not the one that was previewed.", status_code=409
            )
        ),
    )

    dialog.check_file()
    dialog.run_import()

    assert dialog.result is None
    assert dialog.isVisible() is False or dialog.result is None
    assert "not the one that was previewed" in dialog.banner.text()
    assert dialog.import_button.isEnabled() is False


# ─── Showing its work ─────────────────────────────────────────────────────


def test_the_sample_shows_the_dates_as_they_were_read(qtbot) -> None:
    """Seeing `04 Mar 2026` come back out of `04/03/2026` is how somebody
    catches the wrong date order in two seconds rather than six months."""
    dialog, _ = make(qtbot, StubApi(preview(sample=(sample_row(day=date(2026, 3, 4)),))))

    dialog.check_file()

    assert "04 Mar 2026" in texts(dialog, "SampleCell")
    assert "499.00 BDT" in texts(dialog, "SampleCell")


def test_the_summary_counts_what_would_and_would_not_land(qtbot) -> None:
    dialog, _ = make(
        qtbot,
        StubApi(preview(total_rows=418, would_import=412, failed_rows=0, duplicate_rows=6)),
    )

    dialog.check_file()

    assert "412 of 418 rows would be imported" in texts(dialog, "ReportTitle")
    assert "6 already recorded" in report_text(dialog)


def test_ambiguous_dates_are_reported_without_blocking(qtbot) -> None:
    dialog, _ = make(qtbot, StubApi(preview(ambiguous_dates=14)))

    dialog.check_file()

    assert "14 date(s) would read as a different day" in report_text(dialog)
    assert dialog.import_button.isEnabled() is True


def test_an_unusual_encoding_is_named(qtbot) -> None:
    """So a mangled description in the sample has a visible cause."""
    dialog, _ = make(qtbot, StubApi(preview(encoding="cp1252")))

    dialog.check_file()

    assert "Read as cp1252" in report_text(dialog)


def test_a_settled_category_is_marked_differently_from_a_decision(qtbot) -> None:
    """Colour repeats what the words already say — never colour alone."""
    dialog, _ = make(
        qtbot,
        StubApi(
            preview(
                categories=(
                    CategoryPlan("Food", "expense", "matched", 3, 1),
                    CategoryPlan("Skydiving", "expense", "unknown", 2, None),
                )
            )
        ),
    )

    dialog.check_file()
    badges = dialog.findChildren(QLabel, "ReportBadge")

    assert [badge.text() for badge in badges] == ["already yours", "not in this account"]
    assert [badge.property("settled") for badge in badges] == ["true", "false"]


def test_duplicates_say_where_they_already_exist(qtbot) -> None:
    """Repeated in this file and already recorded are different problems."""
    dialog, _ = make(
        qtbot,
        StubApi(
            preview(
                duplicate_rows=1,
                duplicates=(
                    DuplicateRow(
                        line_number=44,
                        date=date(2026, 3, 4),
                        amount=Decimal("499.00"),
                        description="NETFLIX",
                        source="history",
                    ),
                ),
            )
        ),
    )

    dialog.check_file()

    assert "already recorded" in report_text(dialog)


def test_before_anything_is_checked_the_report_says_so(qtbot) -> None:
    dialog, _ = make(qtbot)

    assert "Nothing has been read yet" in texts(dialog, "ReportTitle")


# ─── Painted, not merely present ──────────────────────────────────────────


def stylesheet() -> str:
    return (
        Path(__file__).resolve().parents[1] / "client" / "resources" / "style.qss"
    ).read_text()


def test_the_import_button_is_actually_painted(qtbot) -> None:
    """ADR-022: a dialog-wide `QWidget` rule outranks `#PrimaryButton` and
    paints it in nothing. It stays visible, enabled and clickable throughout,
    so only the pixels tell the difference."""
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(stylesheet())
    try:
        dialog, _ = make(qtbot)
        dialog.check_file()
        dialog.show()
        image = dialog.import_button.grab().toImage()
        # Inside the left padding, clear of the white label text in the middle.
        fill = image.pixelColor(4, image.height() // 2)
    finally:
        app.setStyleSheet(previous)

    assert dialog.import_button.isEnabled() is True
    assert fill == QColor("#1a56c4"), "the primary button is painted in nothing"


def test_a_blocker_is_visible_as_well_as_present(qtbot) -> None:
    """The one thing on this screen that must not be missed."""
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(stylesheet())
    try:
        dialog, _ = make(qtbot, StubApi(preview(would_import=0, blockers=("Nope.",))))
        dialog.check_file()
        dialog.show()
        card = dialog.findChildren(QFrame, "BlockerCard")[0]
        image = card.grab().toImage()
        edge = image.pixelColor(1, image.height() // 2)
    finally:
        app.setStyleSheet(previous)

    assert edge == QColor("#b4232c"), "the blocker lost the edge that makes it a blocker"
