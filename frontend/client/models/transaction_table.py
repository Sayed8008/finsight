"""The table model behind the transactions list.

A `QAbstractTableModel` answers questions from a `QTableView`: how many rows and
columns there are, and what belongs in a given cell for a given *role* —
`DisplayRole` for text, `TextAlignmentRole` for alignment, `ForegroundRole` for
colour. The view does the drawing and the scrolling, and asks only about the
cells it is about to paint.

The alternative, `QTableWidget`, stores the text inside the widget: every
refresh means constructing a `QTableWidgetItem` per cell and the data lives in
the interface. Here the model holds `Transaction` objects, so the rest of the
application keeps talking about transactions rather than about cell text, and
the same model can back a second view later without being rewritten.

Sorting is *not* implemented here, deliberately. `sort()` is overridden to do
nothing, because sorting a page in memory would only reorder the 25 rows on
screen rather than the whole filtered set. The view reports the header click and
the server sorts (ADR-021).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt
from PySide6.QtGui import QColor

from client.api.dto import Transaction

#: Green for income, red for expense. The same pair as the status colours in
#: the stylesheet, so the interface has one meaning for each.
INCOME_COLOUR = QColor("#1a7f4b")
EXPENSE_COLOUR = QColor("#b4232c")
MUTED_COLOUR = QColor("#8b939c")

#: How a date is shown. ISO order is unambiguous but reads poorly in a list, so
#: dates are displayed as "15 Mar 2026" and sorted by the server.
DATE_FORMAT = "%d %b %Y"


@dataclass(frozen=True)
class Column:
    """One column: its heading, and the sort field the server knows it by."""

    heading: str
    #: The `sort_by` value to send, or None if the server cannot sort by this.
    sort_field: str | None
    numeric: bool = False


COLUMNS: tuple[Column, ...] = (
    Column("Date", "date"),
    Column("Description", "description"),
    Column("Category", "category"),
    # The API's sort fields do not include payment method; the header is
    # therefore not clickable rather than silently doing nothing.
    Column("Method", None),
    Column("Amount", "amount", numeric=True),
)

DATE, DESCRIPTION, CATEGORY, METHOD, AMOUNT = range(len(COLUMNS))


class TransactionTableModel(QAbstractTableModel):
    """Presents a page of transactions to a `QTableView`."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: tuple[Transaction, ...] = ()
        self._currency = ""

    # ─── Contents ─────────────────────────────────────────────────────────

    def set_rows(self, rows: tuple[Transaction, ...]) -> None:
        """Replace every row.

        `beginResetModel`/`endResetModel` tell any attached view that
        everything it knows is now stale. Without them the view would keep
        painting from its own cached row count and either show old rows or
        index past the end of the new ones.
        """
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def set_currency(self, code: str) -> None:
        """The currency code to show beside each amount, e.g. "BDT"."""
        self._currency = code
        if self._rows:
            top_left = self.index(0, AMOUNT)
            bottom_right = self.index(len(self._rows) - 1, AMOUNT)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])

    def transaction_at(self, row: int) -> Transaction | None:
        """The transaction on a given row, or None if the row is out of range.

        Returns None rather than raising: a selected row can go out of range
        between a click and the handler running, if a refresh lands in between.
        """
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    # ─── The QAbstractTableModel interface ────────────────────────────────

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        # A table model has no hierarchy: only the invisible root has children,
        # so a valid parent must report zero rows or the view recurses.
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if orientation is not Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section].heading
        if role == Qt.ItemDataRole.TextAlignmentRole:
            # Left alignment has to be stated, not left to the default: Qt
            # centres header text, so a heading over left-aligned cells sits
            # in the middle of its column and reads as belonging to neither
            # the column beside it nor the one below.
            return self._alignment(section)
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None

        transaction = self.transaction_at(index.row())
        if transaction is None:
            return None

        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(transaction, column)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(column)

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._colour(transaction, column)

        if role == Qt.ItemDataRole.ToolTipRole:
            # The description column is the one that gets truncated, so the
            # full text is available on hover rather than lost.
            if column == DESCRIPTION and transaction.description:
                return transaction.description

        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Deliberately does nothing.

        `QTableView.setSortingEnabled(True)` calls this on a header click. If it
        reordered `self._rows`, it would sort the current page only — 25 rows out
        of however many match — and the result would silently disagree with the
        pager. The view listens for the header click instead and asks the server
        to sort, which is where the whole filtered set lives.
        """
        return None

    # ─── Cell rendering ───────────────────────────────────────────────────

    @staticmethod
    def _alignment(column: int) -> int:
        """Numbers right, everything else left — for headings and cells alike.

        One method for both so a heading cannot drift out of line with the
        column beneath it.
        """
        horizontal = (
            Qt.AlignmentFlag.AlignRight if COLUMNS[column].numeric else Qt.AlignmentFlag.AlignLeft
        )
        return int(horizontal | Qt.AlignmentFlag.AlignVCenter)

    def _text(self, transaction: Transaction, column: int) -> str:
        if column == DATE:
            return transaction.date.strftime(DATE_FORMAT)
        if column == DESCRIPTION:
            # An em dash rather than an empty cell, so a missing description
            # reads as "nothing recorded" instead of a rendering fault.
            return transaction.description or "—"
        if column == CATEGORY:
            return transaction.category.name
        if column == METHOD:
            return transaction.payment_method or "—"
        if column == AMOUNT:
            return self._amount(transaction)
        return ""

    def _amount(self, transaction: Transaction) -> str:
        """The amount, signed for display only.

        The stored amount is always positive and the direction lives in
        `transaction_type` — but a column of unsigned numbers with the direction
        implied by colour alone would be unreadable to anyone who cannot
        distinguish the two colours. The sign is presentation, applied here, and
        never sent back to the server.
        """
        sign = "+" if transaction.is_income else "−"
        amount = f"{transaction.amount:,.2f}"
        return f"{sign}{amount} {self._currency}".strip()

    @staticmethod
    def _colour(transaction: Transaction, column: int) -> QColor | None:
        if column == AMOUNT:
            return INCOME_COLOUR if transaction.is_income else EXPENSE_COLOUR
        if column in (DESCRIPTION, METHOD):
            # Grey out the placeholder dash, so it reads as absence rather than
            # as content.
            value = transaction.description if column == DESCRIPTION else transaction.payment_method
            return MUTED_COLOUR if not value else None
        return None
