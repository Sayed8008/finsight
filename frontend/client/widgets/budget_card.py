"""One budget, rendered as a card with a progress bar.

A card rather than a table row because a budget is read at a glance — how much
is left, and is it in trouble — rather than scanned in bulk. That comparison is
easier against a bar than against a column of numbers.

The card displays; it decides nothing. `status` arrives from the server and is
used as-is, so the thresholds exist in exactly one place. A client that worked
out "is this over 80%?" for itself would be a second implementation, free to
drift from the first.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api.dto import Budget

#: A progress bar cannot show 150%. The bar is capped and the real figure is
#: printed beside it, so an overspend is visible as a full red bar *and* as a
#: number that says how far past.
BAR_MAXIMUM = 100


class BudgetCard(QFrame):
    """A single budget: category, period, progress, and the figures."""

    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, budget: Budget, currency: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.budget = budget
        self._currency = currency

        self.setObjectName("BudgetCard")
        self.setProperty("status", budget.status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_bar())
        layout.addLayout(self._build_figures())

    # ─── Header ───────────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        swatch = QLabel()
        swatch.setObjectName("CategorySwatch")
        swatch.setFixedSize(10, 10)
        if self.budget.category.color:
            # Set inline: the colour is per category and comes from the data,
            # so it cannot live in the stylesheet.
            swatch.setStyleSheet(
                f"background-color: {self.budget.category.color}; border-radius: 5px;"
            )
        row.addWidget(swatch)

        name = QLabel(self.budget.category.name)
        name.setObjectName("BudgetCategory")
        row.addWidget(name)

        row.addStretch(1)

        period = QLabel(self._period_text())
        period.setObjectName("BudgetPeriod")
        row.addWidget(period)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("SecondaryButton")
        self.edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self.budget.id))
        row.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.budget.id))
        row.addWidget(self.delete_button)

        return row

    def _period_text(self) -> str:
        start = f"{self.budget.period_start:%d %b}"
        end = f"{self.budget.period_end:%d %b %Y}"
        period = f"{start} – {end}"

        if self.budget.days_remaining is None:
            # Says which side of the period we are on, rather than leaving a
            # finished budget looking like a running one.
            return f"{period} · ended" if not self.budget.is_current else period

        days = self.budget.days_remaining
        return f"{period} · {days} day{'s' if days != 1 else ''} left"

    # ─── Progress ─────────────────────────────────────────────────────────

    def _build_bar(self) -> QProgressBar:
        self.bar = QProgressBar()
        self.bar.setObjectName("BudgetBar")
        self.bar.setRange(0, BAR_MAXIMUM)
        self.bar.setValue(min(BAR_MAXIMUM, int(self.budget.percentage_used)))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        # Read by the stylesheet to colour the chunk green, amber or red.
        self.bar.setProperty("status", self.budget.status)
        return self.bar

    # ─── Figures ──────────────────────────────────────────────────────────

    def _build_figures(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        spent = QLabel(
            f"{self._money(self.budget.spent)} of {self._money(self.budget.amount)} spent"
        )
        spent.setObjectName("BudgetSpent")
        row.addWidget(spent)

        row.addStretch(1)

        self.remaining_label = QLabel(self._remaining_text())
        self.remaining_label.setObjectName("BudgetRemaining")
        self.remaining_label.setProperty("status", self.budget.status)
        row.addWidget(self.remaining_label)

        percentage = QLabel(f"{self.budget.percentage_used:.2f}%")
        percentage.setObjectName("BudgetPercentage")
        percentage.setProperty("status", self.budget.status)
        row.addWidget(percentage)

        return row

    def _remaining_text(self) -> str:
        """ "X left", or "over by X" — never a minus sign in front of "left"."""
        if self.budget.is_overspent:
            return f"over by {self._money(self.budget.overspend)}"
        return f"{self._money(self.budget.remaining)} left"

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()
