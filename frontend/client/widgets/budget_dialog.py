"""The set/edit budget form.

Same shape as the transaction dialog: it is handed a `save` callable and knows
nothing about HTTP, so a server refusal — an overlapping period, most likely —
can be shown in place without losing what was typed.

Only expense categories are offered, mirroring the server rule. The user is not
able to build the request the server would reject (ADR-019).
"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiError
from client.api.dto import EXPENSE, Budget, Category
from client.widgets.forms import FormField, LabelledWidget, MessageBanner

logger = logging.getLogger(__name__)

#: DECIMAL(14,2) holds twelve digits before the point, so this is the first
#: value the column cannot store.
LARGEST_AMOUNT = Decimal("1000000000000.00")


def month_bounds(today: date) -> tuple[date, date]:
    """First and last day of the month containing `today`.

    `calendar.monthrange` rather than arithmetic on day 28/30/31, so February
    and leap years are right without a special case.
    """
    last_day = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, last_day)


class BudgetDialog(QDialog):
    """Collect a category, an amount and a period, then hand them to `save`."""

    def __init__(
        self,
        categories: list[Category],
        *,
        save: Callable[[dict[str, Any]], object],
        budget: Budget | None = None,
        currency: str = "",
        today: date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._save = save
        self._existing = budget
        self._today = today or date.today()
        # Only expense categories can carry a budget, so the rest are never
        # offered rather than being offered and refused.
        self._categories = [c for c in categories if c.category_type == EXPENSE]

        editing = budget is not None
        self.setWindowTitle("Edit budget" if editing else "Set a budget")
        self.setObjectName("BudgetDialog")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        # ─── Category and amount ──────────────────────────────────────────
        self.category_box = QComboBox()
        self.category_box.setObjectName("FieldSelect")
        for category in self._categories:
            self.category_box.addItem(category.name, category.id)

        self.amount_field = FormField(
            f"Limit{f' ({currency})' if currency else ''}", placeholder="0.00"
        )

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(LabelledWidget("Category", self.category_box), stretch=1)
        row.addWidget(self.amount_field, stretch=1)
        layout.addLayout(row)

        # ─── Period ───────────────────────────────────────────────────────
        start, end = month_bounds(self._today)
        self.start_edit = self._date_edit(start)
        self.end_edit = self._date_edit(end)

        period_row = QHBoxLayout()
        period_row.setSpacing(12)
        period_row.addWidget(LabelledWidget("From", self.start_edit), stretch=1)
        period_row.addWidget(LabelledWidget("To", self.end_edit), stretch=1)
        layout.addLayout(period_row)

        self.this_month_button = QPushButton("Use this month")
        self.this_month_button.setObjectName("SecondaryButton")
        self.this_month_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.this_month_button.clicked.connect(self.use_this_month)
        layout.addWidget(self.this_month_button, alignment=Qt.AlignmentFlag.AlignLeft)

        # ─── Buttons ──────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setText("Save changes" if editing else "Set budget")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("SecondaryButton")
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if budget is not None:
            self._fill_from(budget)

        self.amount_field.input.setFocus()

    @staticmethod
    def _date_edit(value: date) -> QDateEdit:
        edit = QDateEdit()
        edit.setObjectName("FieldSelect")
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd MMM yyyy")
        edit.setDate(QDate(value.year, value.month, value.day))
        return edit

    def use_this_month(self) -> None:
        """Fill the period with the current calendar month.

        Almost every budget is monthly, and picking two dates from a calendar
        for something that common is friction worth removing.
        """
        start, end = month_bounds(self._today)
        self.start_edit.setDate(QDate(start.year, start.month, start.day))
        self.end_edit.setDate(QDate(end.year, end.month, end.day))

    def _fill_from(self, budget: Budget) -> None:
        index = self.category_box.findData(budget.category.id)
        if index < 0:
            # The category may since have been retired, so it is not in the
            # list. Adding it keeps the budget editable rather than silently
            # moving it to whichever category happens to be first.
            self.category_box.addItem(f"{budget.category.name} (retired)", budget.category.id)
            index = self.category_box.findData(budget.category.id)
        self.category_box.setCurrentIndex(index)

        self.amount_field.input.setText(f"{budget.amount:.2f}")
        self.start_edit.setDate(
            QDate(budget.period_start.year, budget.period_start.month, budget.period_start.day)
        )
        self.end_edit.setDate(
            QDate(budget.period_end.year, budget.period_end.month, budget.period_end.day)
        )

    # ─── Submission ───────────────────────────────────────────────────────

    def parse_amount(self) -> Decimal | None:
        """The limit as a Decimal, or None if it is not a usable number."""
        text = self.amount_field.text().strip().replace(",", "")
        if not text:
            return None
        try:
            amount = Decimal(text)
        except InvalidOperation:
            return None

        if amount <= 0 or amount.as_tuple().exponent < -2 or amount >= LARGEST_AMOUNT:
            return None
        return amount

    def payload(self, amount: Decimal) -> dict[str, Any]:
        return {
            "category_id": self.category_box.currentData(),
            "amount": f"{amount:.2f}",
            "period_start": self.start_edit.date().toString(Qt.DateFormat.ISODate),
            "period_end": self.end_edit.date().toString(Qt.DateFormat.ISODate),
        }

    def submit(self) -> None:
        """Validate, then save. Stays open and explains itself on failure."""
        amount = self.parse_amount()
        if amount is None:
            self.banner.show_error("Enter a limit greater than zero, with at most two decimals.")
            self.amount_field.input.setFocus()
            return

        if self.category_box.currentData() is None:
            self.banner.show_error("Choose a category. Budgets need an expense category.")
            return

        if self.end_edit.date() < self.start_edit.date():
            self.banner.show_error("The period cannot end before it starts.")
            return

        self._set_busy(busy=True)
        try:
            self._save(self.payload(amount))
        except ApiError as exc:
            # Most often an overlapping period. The server's message names the
            # problem, so it is shown as-is rather than reworded.
            self.banner.show_error(exc.message)
        else:
            self.accept()
        finally:
            self._set_busy(busy=False)

    def _set_busy(self, *, busy: bool) -> None:
        self.save_button.setEnabled(not busy)
        self.save_button.repaint()

    @property
    def budget_id(self) -> int | None:
        return self._existing.id if self._existing is not None else None
