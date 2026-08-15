"""The transactions screen: filters, a table, and a pager.

Everything the user changes here — a filter, a sort, a page — becomes a new
request. Nothing is filtered or sorted locally, because the view only ever holds
one page: sorting it would reorder 25 rows and then disagree with a pager
describing four thousand (ADR-021).

Requests are synchronous, as elsewhere in this client. The backend is on
localhost and a page comes back in single-digit milliseconds; a worker thread
would add real complexity for no perceptible gain. The place to revisit that is
if the backend ever moves off the machine.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import EXPENSE, INCOME, Category, Transaction, TransactionPage
from client.models.transaction_table import COLUMNS, DESCRIPTION, TransactionTableModel
from client.widgets.busy import working
from client.widgets.confirm import confirm
from client.widgets.forms import LabelledWidget, MessageBanner
from client.widgets.import_dialog import ImportDialog
from client.widgets.transaction_dialog import TransactionDialog

logger = logging.getLogger(__name__)

PAGE_SIZES = (25, 50, 100)

#: How long to wait after the last keystroke before searching. Long enough that
#: typing a word is one request rather than five, short enough to feel immediate.
SEARCH_DEBOUNCE_MS = 300

#: The sentinel date meaning "no bound". A QDateEdit cannot be empty, so its
#: minimum doubles as "any", shown as such by `setSpecialValueText`.
ANY_DATE = QDate(1900, 1, 1)

TABLE_PAGE = 0
EMPTY_PAGE = 1


class TransactionsView(QWidget):
    """The Transactions section of the application."""

    #: Emitted when an import creates categories, so the shell can refresh the
    #: pickers on the other screens. Settings has the same signal and for the
    #: same reason: every screen offering a category holds its own list,
    #: fetched once. Importing a CSV with `unknown_categories=CREATE` is the
    #: only other way to make one, and without this the new category was
    #: missing from the budget and subscription dialogs until a restart.
    categories_changed = Signal()

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TransactionsView")
        self._api = api_client

        self._categories: list[Category] = []
        self._page = TransactionPage.empty(PAGE_SIZES[0])
        self._current_page = 1
        self._sort_by = "date"
        self._order = "desc"
        self._currency = ""
        #: Set once the categories and the first page have been fetched, so
        #: navigating back to this section does not re-request everything.
        self._loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)

        layout.addLayout(self._build_header())

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        layout.addWidget(self._build_filter_bar())

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_table())
        self._pages.addWidget(self._build_empty_state())
        layout.addWidget(self._pages, stretch=1)

        layout.addLayout(self._build_pager())

        # One timer, restarted on each keystroke: typing "groceries" then issues
        # one request instead of nine.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.reload)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("Transactions")
        title.setObjectName("SectionTitle")
        row.addWidget(title)

        self.count_label = QLabel("")
        self.count_label.setObjectName("SectionSubtitle")
        row.addWidget(self.count_label)

        row.addStretch(1)

        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("SecondaryButton")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.setToolTip(
            "Read transactions from a CSV file. Nothing is written until you have "
            "seen what it would do."
        )
        self.import_button.clicked.connect(self.import_transactions)
        row.addWidget(self.import_button)

        self.export_button = QPushButton("Export")
        self.export_button.setObjectName("SecondaryButton")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.setToolTip("Save the transactions matching the current filters as CSV.")
        self.export_button.clicked.connect(self.export_transactions)
        row.addWidget(self.export_button)

        self.add_button = QPushButton("Add transaction")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_transaction)
        row.addWidget(self.add_button)

        return row

    def _build_filter_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("FilterBar")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)

        first = QHBoxLayout()
        first.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("FieldInput")
        self.search_input.setPlaceholderText("Search descriptions…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_typed)
        first.addWidget(LabelledWidget("Search", self.search_input), stretch=2)

        self.type_filter = self._select(
            [("All types", None), ("Income", INCOME), ("Expense", EXPENSE)]
        )
        first.addWidget(LabelledWidget("Type", self.type_filter), stretch=1)

        self.category_filter = self._select([("All categories", None)])
        first.addWidget(LabelledWidget("Category", self.category_filter), stretch=1)

        self.method_filter = self._select([("All methods", None)])
        first.addWidget(LabelledWidget("Method", self.method_filter), stretch=1)

        outer.addLayout(first)

        second = QHBoxLayout()
        second.setSpacing(12)

        self.date_from = self._date_edit()
        second.addWidget(LabelledWidget("From", self.date_from), stretch=1)

        self.date_to = self._date_edit()
        second.addWidget(LabelledWidget("To", self.date_to), stretch=1)

        self.amount_min = self._amount_input("0.00")
        second.addWidget(LabelledWidget("Amount from", self.amount_min), stretch=1)

        self.amount_max = self._amount_input("0.00")
        second.addWidget(LabelledWidget("Amount to", self.amount_max), stretch=1)

        self.clear_button = QPushButton("Clear filters")
        self.clear_button.setObjectName("SecondaryButton")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear_filters)
        second.addWidget(LabelledWidget(" ", self.clear_button), stretch=1)

        outer.addLayout(second)
        return bar

    def _select(self, entries: list[tuple[str, Any]]) -> QComboBox:
        box = QComboBox()
        box.setObjectName("FieldSelect")
        for label, value in entries:
            box.addItem(label, value)
        box.currentIndexChanged.connect(self.apply_filters)
        return box

    def _date_edit(self) -> QDateEdit:
        edit = QDateEdit()
        edit.setObjectName("FieldSelect")
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd MMM yyyy")
        edit.setMinimumDate(ANY_DATE)
        # A QDateEdit has no empty state, so its minimum stands in for one and
        # is displayed as "Any" rather than as the year 1900.
        edit.setSpecialValueText("Any")
        edit.setDate(ANY_DATE)
        edit.dateChanged.connect(self.apply_filters)
        return edit

    def _amount_input(self, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("FieldInput")
        edit.setPlaceholderText(placeholder)
        edit.setMaximumWidth(110)
        edit.editingFinished.connect(self.apply_filters)
        return edit

    def _build_table(self) -> QWidget:
        self.model = TransactionTableModel(self)

        self.table = QTableView()
        self.table.setObjectName("TransactionTable")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.doubleClicked.connect(lambda index: self.edit_transaction(index.row()))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # The description absorbs the leftover width; the other columns are as
        # wide as their contents need.
        header.setSectionResizeMode(DESCRIPTION, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        # Sorting is the server's job. The header still shows an indicator and
        # emits the change, which is what triggers a re-query.
        self.table.setSortingEnabled(True)
        header.setSortIndicator(0, Qt.SortOrder.DescendingOrder)
        header.sortIndicatorChanged.connect(self._on_sort_changed)

        container = QWidget()
        container.setObjectName("TableContainer")
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self.table)
        box.addLayout(self._build_row_actions())
        return container

    def _build_row_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("SecondaryButton")
        self.edit_button.clicked.connect(lambda: self.edit_transaction(self.selected_row()))
        row.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.clicked.connect(self.delete_selected)
        row.addWidget(self.delete_button)

        return row

    def _build_empty_state(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("EmptyState")
        box = QVBoxLayout(panel)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(8)

        self.empty_title = QLabel("No transactions yet")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel("Add your first one to see it here.")
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_message)

        return panel

    def _build_pager(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.page_label = QLabel("")
        self.page_label.setObjectName("PagerLabel")
        row.addWidget(self.page_label)

        row.addStretch(1)

        self.page_size_box = QComboBox()
        self.page_size_box.setObjectName("FieldSelect")
        self.page_size_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        for size in PAGE_SIZES:
            self.page_size_box.addItem(f"{size} per page", size)
        # Changing the page size changes what page 4 even means, so it starts
        # again from the first page.
        self.page_size_box.currentIndexChanged.connect(self.apply_filters)
        row.addWidget(self.page_size_box)

        self.previous_button = QPushButton("Previous")
        self.previous_button.setObjectName("SecondaryButton")
        self.previous_button.clicked.connect(lambda: self.go_to_page(self._current_page - 1))
        row.addWidget(self.previous_button)

        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("SecondaryButton")
        self.next_button.clicked.connect(lambda: self.go_to_page(self._current_page + 1))
        row.addWidget(self.next_button)

        return row

    # ─── Loading ──────────────────────────────────────────────────────────

    def load_once(self, currency: str = "") -> None:
        """The one-off lookups, the first time this section is opened.

        Deferred until then rather than done at construction: a user who never
        leaves the dashboard should not pay for a query they never look at, and
        the login screen should not stall behind one.

        The *rows* are not fetched here — the shell calls `reload` every time
        the section is shown, so what is on screen is never left over from an
        earlier visit. Only the category and payment-method lists are cached,
        because those change rarely and Settings announces it when they do
        (ADR-037).
        """
        self._currency = currency
        self.model.set_currency(currency)
        if self._loaded:
            return
        self._loaded = True
        self.refresh_categories()

    def reset(self) -> None:
        """Forget this session's data. See `DashboardView.reset`."""
        self._loaded = False
        self._currency = ""
        self._categories = []
        self._current_page = 1
        self._page = TransactionPage.empty(PAGE_SIZES[0])
        self.model.set_rows(())
        self.banner.clear_message()
        self.clear_filters_quietly()
        self._render_page_state()

    @property
    def is_loaded(self) -> bool:
        """Whether this section has fetched anything yet.

        Asked by the shell before refreshing category pickers: a section nobody
        has opened has no picker to refresh, and forcing one would make a
        request for a screen the user may never look at.
        """
        return self._loaded

    def refresh_categories(self) -> None:
        """Load the category list once, for the filter and both dialogs.

        Once per view, not once per row: the fifteen names are the same for
        every transaction on screen.
        """
        try:
            self._categories = self._api.categories()
            methods = self._api.payment_methods()
        except ApiError as exc:
            self._show_error(exc)
            return

        self._fill_filter(self.category_filter, [(c.name, c.id) for c in self._categories])
        self._fill_filter(self.method_filter, [(m, m) for m in methods])

    @staticmethod
    def _fill_filter(box: QComboBox, entries: list[tuple[str, Any]]) -> None:
        """Refill a filter combo, keeping the current selection if it survives."""
        previous = box.currentData()
        placeholder = box.itemText(0)

        box.blockSignals(True)
        box.clear()
        box.addItem(placeholder, None)
        for label, value in entries:
            box.addItem(label, value)
        if previous is not None:
            index = box.findData(previous)
            if index >= 0:
                box.setCurrentIndex(index)
        box.blockSignals(False)

    def apply_filters(self) -> None:
        """A filter changed: return to the first page, then re-query.

        The page reset is the point. Narrowing a filter while on page 4 of a
        result set that now has two pages would show an empty table with a pager
        insisting there are results — so every filter change goes through here,
        and only the pager's own buttons call `reload` with the page intact.
        """
        self._current_page = 1
        self.reload()

    def reload(self) -> None:
        """Fetch the current page with the current filters."""
        self._search_timer.stop()

        try:
            page = self._api.transactions(
                page=self._current_page,
                page_size=self.page_size(),
                sort_by=self._sort_by,
                order=self._order,
                **self.filter_arguments(),
            )
        except ApiError as exc:
            self._show_error(exc)
            return

        self.banner.clear_message()
        self._page = page
        self.model.set_rows(page.items)
        self._render_page_state()

    def go_to_page(self, page: int) -> None:
        """Move to a page, ignoring a request for one that does not exist."""
        if page < 1 or (self._page.pages and page > self._page.pages):
            return
        self._current_page = page
        self.reload()

    # ─── Filters ──────────────────────────────────────────────────────────

    def page_size(self) -> int:
        return int(self.page_size_box.currentData())

    def filter_arguments(self) -> dict[str, Any]:
        """The active filters, as keyword arguments for the API client.

        Only what is set: an unfiltered field must be absent from the query
        string rather than sent empty, since `?search=` is a search for the
        empty string.
        """
        return {
            "search": self.search_input.text().strip() or None,
            "transaction_type": self.type_filter.currentData(),
            "category_id": self.category_filter.currentData(),
            "payment_method": self.method_filter.currentData(),
            "date_from": self._date_value(self.date_from),
            "date_to": self._date_value(self.date_to),
            "amount_min": self._amount_value(self.amount_min),
            "amount_max": self._amount_value(self.amount_max),
        }

    @staticmethod
    def _date_value(edit: QDateEdit) -> str | None:
        """A date filter as ISO text, or None when left at "Any"."""
        if edit.date() == ANY_DATE:
            return None
        return edit.date().toString(Qt.DateFormat.ISODate)

    @staticmethod
    def _amount_value(edit: QLineEdit) -> str | None:
        """An amount bound as a string, or None if blank or not a number.

        Passed on as text, never as a float: the server compares it against a
        DECIMAL column, and a float would arrive already rounded (ADR-003).
        """
        text = edit.text().strip().replace(",", "")
        if not text:
            return None
        try:
            # Parsed only to check it is a number, and through Decimal rather
            # than float so nothing in this client ever touches binary floating
            # point for money. The original text is what gets sent.
            Decimal(text)
        except InvalidOperation:
            return None
        return text

    def clear_filters(self) -> None:
        """Reset every filter and go back to the first page."""
        self.clear_filters_quietly()
        self.reload()

    def clear_filters_quietly(self) -> None:
        """Reset the controls without asking the server for anything.

        Separate from `clear_filters` because `reset` needs it after sign-out,
        when there is no token to make a request with — and a request that
        fails because the session just ended would put an error banner on the
        screen the next user is about to see.
        """
        widgets: tuple[QWidget, ...] = (
            self.search_input,
            self.type_filter,
            self.category_filter,
            self.method_filter,
            self.date_from,
            self.date_to,
            self.amount_min,
            self.amount_max,
        )
        # Signals are blocked so that clearing eight controls causes one
        # request at the end rather than eight along the way.
        for widget in widgets:
            widget.blockSignals(True)

        self.search_input.clear()
        self.type_filter.setCurrentIndex(0)
        self.category_filter.setCurrentIndex(0)
        self.method_filter.setCurrentIndex(0)
        self.date_from.setDate(ANY_DATE)
        self.date_to.setDate(ANY_DATE)
        self.amount_min.clear()
        self.amount_max.clear()

        for widget in widgets:
            widget.blockSignals(False)

        self._current_page = 1

    def _on_search_typed(self) -> None:
        self._current_page = 1
        self._search_timer.start()

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        """Ask the server for a different order.

        The column may not be sortable — the API has no sort field for payment
        method — in which case the click is ignored and the previous order
        stands, rather than appearing to work and changing nothing.
        """
        sort_field = COLUMNS[column].sort_field
        if sort_field is None:
            return

        self._sort_by = sort_field
        self._order = "asc" if order is Qt.SortOrder.AscendingOrder else "desc"
        self._current_page = 1
        self.reload()

    # ─── Adding, editing, deleting ────────────────────────────────────────

    def selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def selected_transaction(self) -> Transaction | None:
        return self.model.transaction_at(self.selected_row())

    def add_transaction(self) -> None:
        """Open an empty dialog and reload if something was added."""
        if not self._categories:
            self.banner.show_error("No categories are available. Add one in Settings first.")
            return

        dialog = TransactionDialog(
            self._categories,
            save=lambda payload: self._api.create_transaction(**payload),
            payment_methods=self._payment_method_values(),
            currency=self._currency,
            parent=self,
        )
        if dialog.exec():
            # A new row may not belong on the current page under the current
            # sort, so go back to the first page where it will be visible.
            self._current_page = 1
            self.refresh_categories()
            self.reload()

    def edit_transaction(self, row: int) -> None:
        """Open the dialog for one row. Ignored if nothing is selected."""
        transaction = self.model.transaction_at(row)
        if transaction is None:
            self.banner.show_error("Select a transaction to edit.")
            return

        dialog = TransactionDialog(
            self._categories,
            save=lambda payload: self._api.update_transaction(transaction.id, **payload),
            payment_methods=self._payment_method_values(),
            transaction=transaction,
            currency=self._currency,
            parent=self,
        )
        if dialog.exec():
            self.refresh_categories()
            self.reload()

    def delete_selected(self) -> None:
        """Delete the selected transaction, after confirming.

        Deleting cannot be undone, so it asks first — and names the amount and
        date in the question, because "are you sure?" on its own does not let
        anyone check they picked the right row.
        """
        transaction = self.selected_transaction()
        if transaction is None:
            self.banner.show_error("Select a transaction to delete.")
            return

        if not confirm(
            self,
            "Delete transaction",
            f"Delete {transaction.amount:,.2f} {self._currency} "
            f"on {transaction.date:%d %b %Y}?\n\nThis cannot be undone.",
        ):
            return

        try:
            self._api.delete_transaction(transaction.id)
        except ApiError as exc:
            self._show_error(exc)
            return

        # Deleting the last row on a page would otherwise leave the user
        # looking at an empty page that still exists in the pager.
        if len(self._page.items) == 1 and self._current_page > 1:
            self._current_page -= 1
        self.reload()

    # ─── Importing and exporting ──────────────────────────────────────────

    def export_transactions(self) -> None:
        """Save the transactions matching the current filters as a CSV file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export transactions",
            self.suggested_export_name(),
            "CSV files (*.csv)",
        )
        if path:
            self.save_export(path)

    def suggested_export_name(self) -> str:
        """A filename that says what the file is and when it was taken.

        Dated, because an export is a snapshot: two files called
        `transactions.csv` in a downloads folder are indistinguishable, and the
        one thing anybody wants to know is which is newer.
        """
        return f"finsight-transactions-{date.today():%Y-%m-%d}.csv"

    def save_export(self, path: str) -> None:
        """Fetch the filtered transactions and write them to `path`.

        Separate from the file chooser so the whole thing can be exercised
        without a native dialog — the part worth testing is that the export
        carries the filters and reaches disk, not that Qt can pick a folder.

        Written as bytes exactly as they arrived: decoding and re-encoding here
        would be a chance to lose the byte-order mark that lets Excel open the
        file as UTF-8.
        """
        try:
            with working(
                banner=self.banner,
                message="Building the file…",
                disable=(self.export_button, self.import_button),
            ):
                document = self._api.export_transactions(**self.filter_arguments())
        except ApiError as exc:
            self._show_error(exc)
            return

        try:
            Path(path).write_bytes(document)
        except OSError as exc:
            logger.warning("Could not write export to %s: %s", path, exc)
            self.banner.show_error(f"Could not write that file: {exc.strerror or exc}.")
            return

        rows = self._page.total
        self.banner.show_info(
            f"Exported {rows} transaction{'s' if rows != 1 else ''} to {Path(path).name}."
        )

    def import_transactions(self) -> None:
        """Choose a CSV file and review what importing it would do."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import transactions", "", "CSV files (*.csv);;All files (*)"
        )
        if path:
            self.open_import(path)

    def open_import(self, path: str) -> None:
        """Read a file from disk and hand it to the import dialog.

        The file is read here rather than inside the dialog so that a file that
        cannot be opened at all reports itself on this screen, instead of
        opening a dialog whose only content is an error.
        """
        try:
            content = Path(path).read_bytes()
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            self.banner.show_error(f"Could not read that file: {exc.strerror or exc}.")
            return

        dialog = ImportDialog(
            content,
            api_client=self._api,
            filename=Path(path).name,
            categories=self._categories,
            currency=self._currency,
            parent=self,
        )
        dialog.exec()

        if dialog.result is None:
            return

        # An import can create categories, so the filter list is refreshed as
        # well as the page — otherwise a newly imported category would be
        # filterable only after navigating away and back.
        self._current_page = 1
        self.refresh_categories()
        self.reload()
        if dialog.result.created_categories:
            # And the other screens' pickers hold their own lists, which this
            # screen cannot reach. Announced only when something was actually
            # created, so an ordinary import costs no extra requests.
            self.categories_changed.emit()
        # After the reload, not before: `reload` clears the banner on success,
        # which would wipe the one message the user actually wants to read.
        self.banner.show_info(dialog.result.summary)

    def _payment_method_values(self) -> list[str]:
        return [
            self.method_filter.itemData(index)
            for index in range(1, self.method_filter.count())
            if self.method_filter.itemData(index)
        ]

    # ─── Rendering state ──────────────────────────────────────────────────

    def _render_page_state(self) -> None:
        """Update the pager, the counts, and which of table/empty state shows."""
        page = self._page
        has_rows = bool(page.items)

        self._pages.setCurrentIndex(TABLE_PAGE if has_rows else EMPTY_PAGE)
        if not has_rows:
            self._describe_empty_state()

        self.count_label.setText(
            f"{page.total} transaction{'s' if page.total != 1 else ''}" if page.total else ""
        )
        self.page_label.setText(
            f"Page {page.page} of {page.pages}" if page.pages else "Nothing to show"
        )

        self.previous_button.setEnabled(page.page > 1)
        self.next_button.setEnabled(page.page < page.pages)
        self.edit_button.setEnabled(has_rows)
        self.delete_button.setEnabled(has_rows)

    def _describe_empty_state(self) -> None:
        """Say why the table is empty.

        "No transactions yet" and "nothing matches these filters" call for
        different actions from the user, so they are not the same message.
        """
        if self._is_filtered():
            self.empty_title.setText("No matching transactions")
            self.empty_message.setText("Try widening or clearing the filters.")
        else:
            self.empty_title.setText("No transactions yet")
            self.empty_message.setText("Add your first one to see it here.")

    def _is_filtered(self) -> bool:
        return any(value is not None for value in self.filter_arguments().values())

    def _show_error(self, exc: ApiError) -> None:
        logger.warning("Transactions request failed: %s", exc.message)
        self.banner.show_error(exc.message)
        self.model.set_rows(())
        self._page = TransactionPage.empty(self.page_size())
        self._pages.setCurrentIndex(EMPTY_PAGE)
        self.empty_title.setText("Could not load transactions")
        self.empty_message.setText(exc.message)
        self.page_label.setText("")
        self.count_label.setText("")
        for button in (
            self.previous_button,
            self.next_button,
            self.edit_button,
            self.delete_button,
        ):
            button.setEnabled(False)
