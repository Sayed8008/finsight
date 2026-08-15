"""Tests for the transactions screen and its table model.

The API client is a stub that records the requests it was given, so these tests
assert the thing that actually matters about this view: that every filter, sort
and page change becomes a *server* request with the right parameters. A view
that filtered locally would pass a naive "the right rows are shown" test while
being wrong about everything beyond the first page.

No backend runs here, and no database is touched.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from client.api.client import ApiError
from client.api.dto import Category, ImportPreview, ImportResult, Transaction, TransactionPage
from client.models.transaction_table import (
    AMOUNT,
    CATEGORY,
    DATE,
    DESCRIPTION,
    EXPENSE_COLOUR,
    INCOME_COLOUR,
    METHOD,
    TransactionTableModel,
)
from client.views.transactions_view import ANY_DATE, EMPTY_PAGE, TABLE_PAGE, TransactionsView
from client.widgets.import_dialog import ImportDialog
from client.widgets.transaction_dialog import TransactionDialog

pytestmark = pytest.mark.gui

CATEGORIES = [
    Category(id=1, name="Salary", category_type="income", color="#1a7f4b"),
    Category(id=2, name="Food", category_type="expense", color="#c4472f"),
    Category(id=3, name="Transport", category_type="expense", color="#d9782e"),
]

FOOD = CATEGORIES[1]
SALARY = CATEGORIES[0]


def transaction(
    id: int = 1,
    amount: str = "250.00",
    kind: str = "expense",
    category: Category = FOOD,
    day: str = "2026-03-15",
    description: str | None = "Lunch at campus",
    method: str | None = "cash",
) -> Transaction:
    return Transaction(
        id=id,
        amount=Decimal(amount),
        transaction_type=kind,
        date=date.fromisoformat(day),
        category=category,
        description=description,
        payment_method=method,
    )


class StubApi:
    """Records every request, and returns whatever it has been told to."""

    def __init__(self, rows: list[Transaction] | None = None, total: int | None = None) -> None:
        self.rows = rows if rows is not None else [transaction()]
        self.total = total if total is not None else len(self.rows)
        self.calls: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[int, dict[str, Any]]] = []
        self.deleted: list[int] = []
        self.exports: list[dict[str, Any]] = []
        self.previews: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []

    # The two calls made when the view first opens.
    def categories(self, **_: Any) -> list[Category]:
        return list(CATEGORIES)

    def payment_methods(self) -> list[str]:
        return ["bKash", "cash"]

    def transactions(self, **kwargs: Any) -> TransactionPage:
        self.calls.append(kwargs)
        page_size = kwargs.get("page_size", 25)
        pages = -(-self.total // page_size) if page_size else 0
        return TransactionPage(
            items=tuple(self.rows),
            total=self.total,
            page=kwargs.get("page", 1),
            page_size=page_size,
            pages=pages,
        )

    def create_transaction(self, **fields: Any) -> Transaction:
        self.created.append(fields)
        return transaction()

    def update_transaction(self, transaction_id: int, **changes: Any) -> Transaction:
        self.updated.append((transaction_id, changes))
        return transaction()

    def delete_transaction(self, transaction_id: int) -> None:
        self.deleted.append(transaction_id)

    # ─── CSV ──────────────────────────────────────────────────────────────

    def export_transactions(self, **filters: Any) -> bytes:
        self.exports.append(filters)
        return "﻿Date,Amount\r\n2026-03-15,250.00\r\n".encode()

    def preview_import(self, content: bytes, **options: Any) -> ImportPreview:
        self.previews.append({"content": content, **options})
        return ImportPreview(
            total_rows=1,
            would_import=1,
            failed_rows=0,
            duplicate_rows=0,
            blockers=(),
            ambiguous_dates=0,
            encoding="utf-8-sig",
            columns=("amount", "date"),
            sample=(),
            problems=(),
            duplicates=(),
            categories=(),
            digest="a" * 64,
        )

    def import_transactions(self, content: bytes, **options: Any) -> ImportResult:
        self.imports.append({"content": content, **options})
        return ImportResult(
            imported=3,
            skipped_duplicates=1,
            skipped_invalid=0,
            created_categories=("Skydiving",),
            first_date=date(2026, 3, 1),
            last_date=date(2026, 3, 31),
        )

    # ─── Helpers for assertions ───────────────────────────────────────────

    @property
    def last_call(self) -> dict[str, Any]:
        return self.calls[-1]

    def reset(self) -> None:
        self.calls.clear()


class FailingApi(StubApi):
    def transactions(self, **kwargs: Any) -> TransactionPage:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")


@pytest.fixture
def view(qtbot) -> TransactionsView:
    """A loaded transactions view backed by a stub."""
    widget = TransactionsView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    return widget


def api_of(view: TransactionsView) -> StubApi:
    return view._api


# ─── The table model ──────────────────────────────────────────────────────


def test_the_model_reports_its_shape(qtbot) -> None:
    model = TransactionTableModel()
    model.set_rows((transaction(), transaction(id=2)))

    assert model.rowCount() == 2
    assert model.columnCount() == 5


def test_a_child_index_has_no_rows(qtbot) -> None:
    """A table is flat. A valid parent reporting rows would make the view recurse."""
    model = TransactionTableModel()
    model.set_rows((transaction(),))

    assert model.rowCount(model.index(0, 0)) == 0


def cell(model: TransactionTableModel, row: int, column: int) -> str:
    return model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole)


def test_cells_render_the_transaction(qtbot) -> None:
    model = TransactionTableModel()
    model.set_currency("BDT")
    model.set_rows((transaction(),))

    assert cell(model, 0, DATE) == "15 Mar 2026"
    assert cell(model, 0, DESCRIPTION) == "Lunch at campus"
    assert cell(model, 0, CATEGORY) == "Food"
    assert cell(model, 0, METHOD) == "cash"
    assert cell(model, 0, AMOUNT) == "−250.00 BDT"


def test_income_is_shown_with_a_plus_and_expenses_with_a_minus(qtbot) -> None:
    """The stored amount is unsigned; the sign is presentation only."""
    model = TransactionTableModel()
    model.set_rows(
        (
            transaction(kind="income", category=SALARY, amount="45000.00"),
            transaction(id=2, kind="expense", amount="250.00"),
        )
    )

    assert cell(model, 0, AMOUNT).startswith("+")
    assert cell(model, 1, AMOUNT).startswith("−")


def test_amounts_are_grouped_and_keep_two_decimals(qtbot) -> None:
    model = TransactionTableModel()
    model.set_rows((transaction(kind="income", category=SALARY, amount="45000.5"),))

    assert cell(model, 0, AMOUNT) == "+45,000.50"


def test_direction_is_carried_by_colour_as_well_as_sign(qtbot) -> None:
    """Colour alone would exclude anyone who cannot distinguish the two."""
    model = TransactionTableModel()
    model.set_rows(
        (
            transaction(kind="income", category=SALARY),
            transaction(id=2, kind="expense"),
        )
    )

    def colour(row: int):
        return model.data(model.index(row, AMOUNT), Qt.ItemDataRole.ForegroundRole)

    assert colour(0) == INCOME_COLOUR
    assert colour(1) == EXPENSE_COLOUR


def test_a_missing_description_reads_as_absence(qtbot) -> None:
    model = TransactionTableModel()
    model.set_rows((transaction(description=None, method=None),))

    assert cell(model, 0, DESCRIPTION) == "—"
    assert cell(model, 0, METHOD) == "—"


def test_sorting_the_model_does_nothing(qtbot) -> None:
    """Sorting a page locally would reorder 25 rows and disagree with the pager."""
    model = TransactionTableModel()
    rows = (transaction(id=1, amount="900.00"), transaction(id=2, amount="100.00"))
    model.set_rows(rows)

    model.sort(AMOUNT, Qt.SortOrder.AscendingOrder)

    assert [model.transaction_at(row).id for row in range(2)] == [1, 2]


def test_headings_line_up_with_the_cells_beneath_them(qtbot) -> None:
    """Found by rendering, not by reading (ADR-012).

    Qt centres header text by default, so "Description" sat in the middle of a
    wide column above left-aligned values. Alignment is now stated for headings
    as well as cells, from one method, so the two cannot drift apart.
    """
    model = TransactionTableModel()
    model.set_rows((transaction(),))

    def heading_alignment(column: int) -> int:
        return model.headerData(
            column, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole
        )

    def cell_alignment(column: int) -> int:
        return model.data(model.index(0, column), Qt.ItemDataRole.TextAlignmentRole)

    for column in (DATE, DESCRIPTION, CATEGORY, METHOD, AMOUNT):
        assert heading_alignment(column) == cell_alignment(column)

    assert heading_alignment(DESCRIPTION) & Qt.AlignmentFlag.AlignLeft
    assert heading_alignment(AMOUNT) & Qt.AlignmentFlag.AlignRight


def test_a_row_out_of_range_is_none_rather_than_an_error(qtbot) -> None:
    """A selected row can fall out of range if a refresh lands between click and handler."""
    model = TransactionTableModel()
    model.set_rows((transaction(),))

    assert model.transaction_at(5) is None
    assert model.transaction_at(-1) is None


# ─── First load ───────────────────────────────────────────────────────────


def test_opening_the_view_requests_the_first_page(view: TransactionsView) -> None:
    call = api_of(view).last_call

    assert call["page"] == 1
    assert call["sort_by"] == "date"
    assert call["order"] == "desc"


def test_opening_the_view_twice_does_not_refetch(view: TransactionsView) -> None:
    """Navigating away and back should not re-run the query."""
    before = len(api_of(view).calls)

    view.load_once("BDT")

    assert len(api_of(view).calls) == before


def test_the_rows_reach_the_table(view: TransactionsView) -> None:
    assert view.model.rowCount() == 1
    assert view.model.transaction_at(0).description == "Lunch at campus"


def test_the_currency_reaches_the_amount_column(view: TransactionsView) -> None:
    assert "BDT" in view.model.data(view.model.index(0, AMOUNT), Qt.ItemDataRole.DisplayRole)


def test_no_filters_are_sent_when_none_are_set(view: TransactionsView) -> None:
    """`?search=` is a search for the empty string, which is a different request."""
    call = api_of(view).last_call

    assert call["search"] is None
    assert call["date_from"] is None
    assert call["amount_min"] is None
    assert call["category_id"] is None


# ─── Filters become requests ──────────────────────────────────────────────


def test_choosing_a_type_filters_on_the_server(view: TransactionsView) -> None:
    api_of(view).reset()

    view.type_filter.setCurrentIndex(view.type_filter.findData("expense"))

    assert api_of(view).last_call["transaction_type"] == "expense"


def test_choosing_a_category_sends_its_id(view: TransactionsView) -> None:
    api_of(view).reset()

    view.category_filter.setCurrentIndex(view.category_filter.findData(FOOD.id))

    assert api_of(view).last_call["category_id"] == FOOD.id


def test_the_category_filter_is_populated_from_the_api(view: TransactionsView) -> None:
    labels = [view.category_filter.itemText(i) for i in range(view.category_filter.count())]

    assert labels == ["All categories", "Salary", "Food", "Transport"]


def test_the_method_filter_offers_only_methods_in_use(view: TransactionsView) -> None:
    labels = [view.method_filter.itemText(i) for i in range(view.method_filter.count())]

    assert labels == ["All methods", "bKash", "cash"]


def test_a_date_bound_is_sent_as_iso_text(view: TransactionsView) -> None:
    api_of(view).reset()

    view.date_from.setDate(QDate(2026, 3, 1))

    assert api_of(view).last_call["date_from"] == "2026-03-01"


def test_an_untouched_date_means_no_bound(view: TransactionsView) -> None:
    """A QDateEdit cannot be empty, so its minimum stands in for "any"."""
    assert view.date_from.date() == ANY_DATE
    assert api_of(view).last_call["date_from"] is None


def test_an_amount_bound_is_sent_as_a_string(view: TransactionsView) -> None:
    """Never as a float — the server compares it against a DECIMAL column."""
    view.amount_min.setText("100.50")
    view.amount_min.editingFinished.emit()

    sent = api_of(view).last_call["amount_min"]
    assert sent == "100.50"
    assert isinstance(sent, str)


def test_an_unparseable_amount_bound_is_not_sent(view: TransactionsView) -> None:
    view.amount_min.setText("lots")
    view.amount_min.editingFinished.emit()

    assert api_of(view).last_call["amount_min"] is None


def test_searching_is_debounced_into_one_request(view: TransactionsView) -> None:
    """Typing a word should be one request, not one per keystroke."""
    api_of(view).reset()

    for text in ("l", "lu", "lun", "lunc", "lunch"):
        view.search_input.setText(text)

    assert api_of(view).calls == []

    view._search_timer.timeout.emit()

    assert len(api_of(view).calls) == 1
    assert api_of(view).last_call["search"] == "lunch"


def test_clearing_filters_resets_everything_in_one_request(view: TransactionsView) -> None:
    view.type_filter.setCurrentIndex(view.type_filter.findData("expense"))
    view.date_from.setDate(QDate(2026, 3, 1))
    view.amount_min.setText("100.00")
    api_of(view).reset()

    view.clear_filters()

    assert len(api_of(view).calls) == 1
    call = api_of(view).last_call
    assert call["transaction_type"] is None
    assert call["date_from"] is None
    assert call["amount_min"] is None


# ─── Sorting is the server's job ──────────────────────────────────────────


def test_clicking_a_header_asks_the_server_to_sort(view: TransactionsView) -> None:
    api_of(view).reset()

    view.table.horizontalHeader().setSortIndicator(AMOUNT, Qt.SortOrder.AscendingOrder)

    call = api_of(view).last_call
    assert call["sort_by"] == "amount"
    assert call["order"] == "asc"


def test_sorting_by_category_sorts_by_name_on_the_server(view: TransactionsView) -> None:
    api_of(view).reset()

    view.table.horizontalHeader().setSortIndicator(CATEGORY, Qt.SortOrder.AscendingOrder)

    assert api_of(view).last_call["sort_by"] == "category"


def test_the_method_column_cannot_be_sorted(view: TransactionsView) -> None:
    """The API has no sort field for it, so the click is ignored rather than faked."""
    api_of(view).reset()

    view.table.horizontalHeader().setSortIndicator(METHOD, Qt.SortOrder.AscendingOrder)

    assert api_of(view).calls == []


def test_sorting_returns_to_the_first_page(qtbot) -> None:
    api = StubApi(rows=[transaction()], total=60)
    view = TransactionsView(api)
    qtbot.addWidget(view)
    view.load_once("BDT")
    view.go_to_page(3)

    view.table.horizontalHeader().setSortIndicator(AMOUNT, Qt.SortOrder.AscendingOrder)

    assert api.last_call["page"] == 1


# ─── Paging ───────────────────────────────────────────────────────────────


def test_the_pager_describes_the_whole_filtered_set(qtbot) -> None:
    view = TransactionsView(StubApi(rows=[transaction()], total=60))
    qtbot.addWidget(view)
    view.load_once("BDT")

    assert view.page_label.text() == "Page 1 of 3"
    assert view.count_label.text() == "60 transactions"


def test_next_and_previous_move_between_pages(qtbot) -> None:
    api = StubApi(rows=[transaction()], total=60)
    view = TransactionsView(api)
    qtbot.addWidget(view)
    view.load_once("BDT")

    view.next_button.click()
    assert api.last_call["page"] == 2

    view.previous_button.click()
    assert api.last_call["page"] == 1


def test_previous_is_disabled_on_the_first_page(qtbot) -> None:
    view = TransactionsView(StubApi(rows=[transaction()], total=60))
    qtbot.addWidget(view)
    view.load_once("BDT")

    assert not view.previous_button.isEnabled()
    assert view.next_button.isEnabled()


def test_paging_past_the_end_is_ignored(qtbot) -> None:
    api = StubApi(rows=[transaction()], total=60)
    view = TransactionsView(api)
    qtbot.addWidget(view)
    view.load_once("BDT")
    api.reset()

    view.go_to_page(99)

    assert api.calls == []


def test_a_filter_change_returns_to_page_one(qtbot) -> None:
    """Page 4 of a set that now has two pages would be an unexplained empty table."""
    api = StubApi(rows=[transaction()], total=60)
    view = TransactionsView(api)
    qtbot.addWidget(view)
    view.load_once("BDT")
    view.go_to_page(3)
    assert api.last_call["page"] == 3

    view.type_filter.setCurrentIndex(view.type_filter.findData("expense"))

    assert api.last_call["page"] == 1


def test_changing_the_page_size_is_sent_and_resets_the_page(qtbot) -> None:
    api = StubApi(rows=[transaction()], total=60)
    view = TransactionsView(api)
    qtbot.addWidget(view)
    view.load_once("BDT")
    view.go_to_page(3)

    view.page_size_box.setCurrentIndex(view.page_size_box.findData(50))

    assert api.last_call["page_size"] == 50
    assert api.last_call["page"] == 1


# ─── Empty and error states ───────────────────────────────────────────────


def test_an_empty_ledger_says_so(qtbot) -> None:
    view = TransactionsView(StubApi(rows=[], total=0))
    qtbot.addWidget(view)
    view.load_once("BDT")

    assert view._pages.currentIndex() == EMPTY_PAGE
    assert view.empty_title.text() == "No transactions yet"


def test_no_matches_is_a_different_message_from_no_data(qtbot) -> None:
    """The two call for different actions, so they must not read the same."""
    view = TransactionsView(StubApi(rows=[], total=0))
    qtbot.addWidget(view)
    view.load_once("BDT")

    view.type_filter.setCurrentIndex(view.type_filter.findData("income"))

    assert view.empty_title.text() == "No matching transactions"
    assert "filters" in view.empty_message.text()


def test_rows_show_the_table_rather_than_the_empty_state(view: TransactionsView) -> None:
    assert view._pages.currentIndex() == TABLE_PAGE


def test_an_unreachable_backend_is_reported_not_crashed(qtbot) -> None:
    view = TransactionsView(FailingApi())
    qtbot.addWidget(view)

    view.load_once("BDT")

    assert "Cannot reach" in view.banner.text()
    assert view.model.rowCount() == 0
    assert not view.next_button.isEnabled()


def test_edit_and_delete_are_disabled_with_nothing_to_act_on(qtbot) -> None:
    view = TransactionsView(StubApi(rows=[], total=0))
    qtbot.addWidget(view)
    view.load_once("BDT")

    assert not view.edit_button.isEnabled()
    assert not view.delete_button.isEnabled()


# ─── Deleting ─────────────────────────────────────────────────────────────


def test_deleting_without_a_selection_is_reported(view: TransactionsView) -> None:
    view.delete_selected()

    assert "Select a transaction" in view.banner.text()
    assert api_of(view).deleted == []


def test_deleting_asks_first_and_does_nothing_if_declined(
    view: TransactionsView, monkeypatch
) -> None:
    """Deleting cannot be undone, so a mis-click must not be enough to do it."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel
    )
    view.table.selectRow(0)

    view.delete_selected()

    assert api_of(view).deleted == []


def test_confirming_deletes_the_selected_transaction(view: TransactionsView, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    view.table.selectRow(0)

    view.delete_selected()

    assert api_of(view).deleted == [1]


# ─── The dialog ───────────────────────────────────────────────────────────


def make_dialog(qtbot, **kwargs) -> tuple[TransactionDialog, list]:
    saved: list = []

    def save(payload):
        saved.append(payload)

    dialog = TransactionDialog(list(CATEGORIES), save=kwargs.pop("save", save), **kwargs)
    qtbot.addWidget(dialog)
    return dialog, saved


def test_the_dialog_offers_only_categories_of_the_chosen_type(qtbot) -> None:
    """The server refuses a mismatched pair; the form never allows one to be built."""
    dialog, _ = make_dialog(qtbot)

    dialog.type_box.setCurrentIndex(dialog.type_box.findData("expense"))
    expense_names = [dialog.category_box.itemText(i) for i in range(dialog.category_box.count())]

    dialog.type_box.setCurrentIndex(dialog.type_box.findData("income"))
    income_names = [dialog.category_box.itemText(i) for i in range(dialog.category_box.count())]

    assert expense_names == ["Food", "Transport"]
    assert income_names == ["Salary"]


def test_the_dialog_sends_the_amount_as_a_string(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText("1234.5")
    dialog.date_edit.setDate(QDate(2026, 3, 15))

    dialog.submit()

    assert saved[0]["amount"] == "1234.50"
    assert isinstance(saved[0]["amount"], str)


def test_the_dialog_sends_an_iso_date(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText("10.00")
    dialog.date_edit.setDate(QDate(2026, 3, 15))

    dialog.submit()

    assert saved[0]["date"] == "2026-03-15"


@pytest.mark.parametrize("text", ["", "0", "-5", "abc", "10.005", "1000000000000.00"])
def test_an_unusable_amount_is_refused_before_any_request(qtbot, text: str) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText(text)

    dialog.submit()

    assert saved == []
    assert "amount" in dialog.banner.text().lower()


def test_a_blank_description_is_sent_as_null_not_an_empty_string(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText("10.00")
    dialog.description_field.input.setText("   ")

    dialog.submit()

    assert saved[0]["description"] is None


def test_the_dialog_stays_open_when_the_server_refuses(qtbot) -> None:
    """Whatever the user typed must survive a rejection."""

    def refuse(payload):
        raise ApiError("That category has been deactivated.")

    dialog, _ = make_dialog(qtbot, save=refuse)
    dialog.amount_field.input.setText("10.00")

    dialog.submit()

    assert dialog.result() != TransactionDialog.DialogCode.Accepted
    assert "deactivated" in dialog.banner.text()
    # And the typed amount is still there to correct, rather than lost.
    assert dialog.amount_field.text() == "10.00"


def test_editing_fills_the_form_from_the_transaction(qtbot) -> None:
    existing = transaction(amount="750.25", day="2026-02-14", description="Groceries")

    dialog, _ = make_dialog(qtbot, transaction=existing)

    assert dialog.amount_field.text() == "750.25"
    assert dialog.date_edit.date() == QDate(2026, 2, 14)
    assert dialog.description_field.text() == "Groceries"
    assert dialog.category_box.currentData() == FOOD.id
    assert dialog.transaction_id == existing.id


def test_editing_keeps_a_retired_category_available(qtbot) -> None:
    """Otherwise editing the amount would silently move it to another category."""
    retired = Category(id=9, name="Old Category", category_type="expense", is_active=False)
    existing = transaction(category=retired)

    dialog, _ = make_dialog(qtbot, transaction=existing)

    assert dialog.category_box.currentData() == retired.id
    assert "retired" in dialog.category_box.currentText()


def test_adding_a_transaction_reloads_the_list(view: TransactionsView, monkeypatch) -> None:
    """A new row may not belong on the current page, so the view goes back to page 1."""
    monkeypatch.setattr(TransactionDialog, "exec", lambda self: 1)
    view.go_to_page(1)
    api_of(view).reset()

    view.add_transaction()

    assert len(api_of(view).calls) == 1
    assert api_of(view).last_call["page"] == 1


def test_editing_without_a_selection_is_reported(view: TransactionsView) -> None:
    view.edit_transaction(-1)

    assert "Select a transaction" in view.banner.text()


# ─── Rendering ────────────────────────────────────────────────────────────


def test_the_primary_button_is_actually_painted(qtbot) -> None:
    """A regression test with teeth: the button was invisible, not absent.

    `#TransactionDialog QWidget { background: transparent }` matches every
    QPushButton inside the dialog, and being more specific than `#PrimaryButton`
    it won — so "Add transaction" was laid out, sized, enabled and clickable,
    while painted in nothing on a white dialog. Geometry and visibility tests
    all passed. Only the pixels showed it (ADR-022).
    """
    stylesheet = (
        Path(__file__).resolve().parents[1] / "client" / "resources" / "style.qss"
    ).read_text()
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(stylesheet)
    try:
        dialog, _ = make_dialog(qtbot)
        dialog.show()
        qtbot.waitExposed(dialog) if dialog.isVisible() else None

        image = dialog.save_button.grab().toImage()
        # Sampled near the left edge rather than dead centre: the centre pixel
        # sits on the antialiased white label text, which is not the background
        # this test is about.
        background = image.pixelColor(8, image.height() // 2)
    finally:
        app.setStyleSheet(previous)

    assert image.width() > 0 and image.height() > 0
    assert background != QColor("#ffffff"), "the primary button is painted white on white"
    assert background == QColor("#1a56c4")


# ─── Importing and exporting ──────────────────────────────────────────────


def test_the_export_carries_the_filters_on_screen(view: TransactionsView, tmp_path) -> None:
    """"Export what I am looking at" has to mean what it says, or the file is
    a different set of rows from the table above it."""
    view.search_input.setText("netflix")
    view.type_filter.setCurrentIndex(2)
    api_of(view).exports.clear()

    view.save_export(str(tmp_path / "out.csv"))

    assert api_of(view).exports[-1]["search"] == "netflix"
    assert api_of(view).exports[-1]["transaction_type"] == "expense"


def test_the_export_reaches_disk_byte_for_byte(view: TransactionsView, tmp_path) -> None:
    """Written as bytes: decoding and re-encoding would be a chance to lose
    the byte-order mark that lets Excel open the file as UTF-8."""
    path = tmp_path / "out.csv"

    view.save_export(str(path))

    assert path.read_bytes().startswith("﻿".encode())
    assert "2026-03-15,250.00" in path.read_text(encoding="utf-8-sig")


def test_the_export_says_what_it_wrote(view: TransactionsView, tmp_path) -> None:
    view.save_export(str(tmp_path / "out.csv"))

    assert "Exported 1 transaction to out.csv" in view.banner.text()


def test_a_file_that_cannot_be_written_is_reported(view: TransactionsView, tmp_path) -> None:
    """A silent failure here means the user believes they have a backup."""
    view.save_export(str(tmp_path / "no-such-folder" / "out.csv"))

    assert "Could not write that file" in view.banner.text()


def test_the_suggested_filename_is_dated(view: TransactionsView) -> None:
    """Two files called transactions.csv in a downloads folder are
    indistinguishable, and the one thing anybody wants is which is newer."""
    assert view.suggested_export_name().startswith("finsight-transactions-")
    assert view.suggested_export_name().endswith(".csv")


def test_a_file_that_cannot_be_read_is_reported_without_opening_a_dialog(
    view: TransactionsView, tmp_path
) -> None:
    view.open_import(str(tmp_path / "missing.csv"))

    assert "Could not read that file" in view.banner.text()
    assert api_of(view).previews == []


def test_opening_a_file_for_import_reads_nothing_until_asked(
    view: TransactionsView, tmp_path, monkeypatch
) -> None:
    """Choosing a file is not the same act as importing it (ADR-007's rule,
    applied to a second feature that can change somebody's data)."""
    path = tmp_path / "statement.csv"
    path.write_bytes(b"Date,Amount,Type,Category\n2026-03-04,10.00,expense,Food\n")
    monkeypatch.setattr(ImportDialog, "exec", lambda self: 0)

    view.open_import(str(path))

    assert api_of(view).previews == []
    assert api_of(view).imports == []


def test_a_successful_import_refreshes_the_screen_and_says_what_happened(
    view: TransactionsView, tmp_path, monkeypatch
) -> None:
    """Including what it left out — a message naming only what was imported
    leaves the user wondering what became of the rest."""
    path = tmp_path / "statement.csv"
    path.write_bytes(b"Date,Amount,Type,Category\n2026-03-04,10.00,expense,Food\n")

    def check_and_import(dialog: ImportDialog) -> int:
        dialog.check_file()
        dialog.run_import()
        return 1

    monkeypatch.setattr(ImportDialog, "exec", check_and_import)
    api_of(view).reset()

    view.open_import(str(path))

    assert api_of(view).imports
    assert api_of(view).calls, "the table was not reloaded after the import"
    assert "Imported 3 transactions" in view.banner.text()
    assert "1 already recorded and left out" in view.banner.text()
    assert "Created: Skydiving" in view.banner.text()


def test_a_cancelled_import_leaves_the_screen_alone(
    view: TransactionsView, tmp_path, monkeypatch
) -> None:
    path = tmp_path / "statement.csv"
    path.write_bytes(b"Date,Amount,Type,Category\n2026-03-04,10.00,expense,Food\n")
    monkeypatch.setattr(ImportDialog, "exec", lambda self: 0)
    api_of(view).reset()

    view.open_import(str(path))

    assert api_of(view).calls == []
