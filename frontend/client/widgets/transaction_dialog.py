"""The add/edit transaction form.

One dialog serves both jobs. Adding and editing differ in their title, their
button text, and whether the fields start filled — not in their rules, so a
second dialog would be the same code with a different heading and one more place
to forget a validation.

The dialog knows nothing about HTTP. It is given a `save` callable and calls it
with a payload; the view supplies one that talks to the API. That is what lets
the dialog stay open and show a server error in place rather than vanishing and
losing everything the user typed — and what lets it be tested without a
network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiError
from client.api.dto import EXPENSE, INCOME, Category, Transaction
from client.widgets.forms import FormField, LabelledWidget, MessageBanner

logger = logging.getLogger(__name__)

MAX_DESCRIPTION_LENGTH = 255
MAX_PAYMENT_METHOD_LENGTH = 50

#: DECIMAL(14,2) holds twelve digits before the point and two after, so this is
#: the first value the column cannot store. Checked here as well as on the
#: server, so the user hears about it without a round trip (ADR-019).
LARGEST_AMOUNT = Decimal("1000000000000.00")


class TransactionDialog(QDialog):
    """Collect the fields of a transaction, then hand them to `save`."""

    def __init__(
        self,
        categories: list[Category],
        *,
        save: Callable[[dict[str, Any]], object],
        payment_methods: list[str] | None = None,
        transaction: Transaction | None = None,
        currency: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._all_categories = categories
        self._save = save
        self._existing = transaction
        self._currency = currency

        editing = transaction is not None
        self.setWindowTitle("Edit transaction" if editing else "Add transaction")
        self.setObjectName("TransactionDialog")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        # ─── Type and amount ──────────────────────────────────────────────
        self.type_box = QComboBox()
        self.type_box.setObjectName("FieldSelect")
        self.type_box.addItem("Expense", EXPENSE)
        self.type_box.addItem("Income", INCOME)
        # Changing the type must change which categories are on offer, or the
        # form would let the user build a request the server is bound to reject.
        self.type_box.currentIndexChanged.connect(self._repopulate_categories)

        self.amount_field = FormField(
            f"Amount{f' ({currency})' if currency else ''}", placeholder="0.00"
        )

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(LabelledWidget("Type", self.type_box), stretch=1)
        row.addWidget(self.amount_field, stretch=1)
        layout.addLayout(row)

        # ─── Category and date ────────────────────────────────────────────
        self.category_box = QComboBox()
        self.category_box.setObjectName("FieldSelect")

        self.date_edit = QDateEdit()
        self.date_edit.setObjectName("FieldSelect")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd MMM yyyy")
        self.date_edit.setDate(QDate.currentDate())

        second_row = QHBoxLayout()
        second_row.setSpacing(12)
        second_row.addWidget(LabelledWidget("Category", self.category_box), stretch=1)
        second_row.addWidget(LabelledWidget("Date", self.date_edit), stretch=1)
        layout.addLayout(second_row)

        # ─── Description and payment method ───────────────────────────────
        self.description_field = FormField("Description", placeholder="What was it for?")
        self.description_field.input.setMaxLength(MAX_DESCRIPTION_LENGTH)
        layout.addWidget(self.description_field)

        self.method_box = QComboBox()
        self.method_box.setObjectName("FieldSelect")
        # Editable so a method that has never been used can still be typed;
        # the list is a convenience, not a constraint.
        self.method_box.setEditable(True)
        self.method_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.method_box.addItem("")
        self.method_box.addItems(payment_methods or [])
        if self.method_box.lineEdit() is not None:
            self.method_box.lineEdit().setMaxLength(MAX_PAYMENT_METHOD_LENGTH)
            self.method_box.lineEdit().setPlaceholderText("Cash, bKash, card…")
        layout.addWidget(LabelledWidget("Payment method", self.method_box))

        # ─── Buttons ──────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setText("Save changes" if editing else "Add transaction")
        # Named too, or it keeps the platform's default look beside a styled
        # primary button and the pair reads as two different interfaces.
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("SecondaryButton")
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._repopulate_categories()
        if transaction is not None:
            self._fill_from(transaction)

        self.amount_field.input.setFocus()

    # ─── Category list ────────────────────────────────────────────────────

    def selected_type(self) -> str:
        return str(self.type_box.currentData())

    def _repopulate_categories(self) -> None:
        """Offer only the categories matching the selected type.

        The server enforces this pairing too (an expense in an income category
        is refused). Filtering here means the user is never able to choose the
        invalid combination in the first place — client-side validation as
        feedback, not as the authority (ADR-019).
        """
        wanted = self.selected_type()
        previous = self.category_box.currentData()

        self.category_box.clear()
        for category in self._all_categories:
            if category.category_type == wanted:
                self.category_box.addItem(category.name, category.id)

        if previous is not None:
            restored = self.category_box.findData(previous)
            if restored >= 0:
                self.category_box.setCurrentIndex(restored)

    def _fill_from(self, transaction: Transaction) -> None:
        """Populate the form from an existing transaction."""
        type_index = self.type_box.findData(transaction.transaction_type)
        if type_index >= 0:
            self.type_box.setCurrentIndex(type_index)

        # The category may since have been deactivated, in which case it is not
        # in the list. Adding it keeps the transaction editable rather than
        # silently moving it to whichever category happens to be first.
        category_index = self.category_box.findData(transaction.category.id)
        if category_index < 0:
            self.category_box.addItem(
                f"{transaction.category.name} (retired)", transaction.category.id
            )
            category_index = self.category_box.findData(transaction.category.id)
        self.category_box.setCurrentIndex(category_index)

        self.amount_field.input.setText(f"{transaction.amount:.2f}")
        self.date_edit.setDate(
            QDate(transaction.date.year, transaction.date.month, transaction.date.day)
        )
        self.description_field.input.setText(transaction.description or "")
        if transaction.payment_method:
            self.method_box.setCurrentText(transaction.payment_method)

    # ─── Submission ───────────────────────────────────────────────────────

    def parse_amount(self) -> Decimal | None:
        """The amount as a Decimal, or None if it is not a usable number.

        `Decimal(str)` rather than `float(str)`: the value is about to be sent as
        a string and compared against a DECIMAL column, and going through a
        float would round it on the way (ADR-003).
        """
        text = self.amount_field.text().strip().replace(",", "")
        if not text:
            return None
        try:
            amount = Decimal(text)
        except InvalidOperation:
            return None

        if amount <= 0:
            return None
        # More than two decimal places would be truncated by DECIMAL(14,2), and
        # silently changing what someone typed is worse than refusing it.
        if amount.as_tuple().exponent < -2:
            return None
        if amount >= LARGEST_AMOUNT:
            return None
        return amount

    def payload(self, amount: Decimal) -> dict[str, Any]:
        """The request body, with the amount as a string.

        Takes the validated amount rather than re-parsing, so there is no path
        through this method that can produce a body the form has not checked.
        """
        description = self.description_field.text().strip()
        method = self.method_box.currentText().strip()

        return {
            "amount": f"{amount:.2f}",
            "transaction_type": self.selected_type(),
            "category_id": self.category_box.currentData(),
            "date": self.date_edit.date().toString(Qt.DateFormat.ISODate),
            "description": description or None,
            "payment_method": method or None,
        }

    def submit(self) -> None:
        """Validate, then save. Stays open and explains itself on failure."""
        amount = self.parse_amount()
        if amount is None:
            self.banner.show_error("Enter an amount greater than zero, with at most two decimals.")
            self.amount_field.input.setFocus()
            return

        if self.category_box.currentData() is None:
            self.banner.show_error("Choose a category. Add one first if the list is empty.")
            return

        self._set_busy(busy=True)
        try:
            self._save(self.payload(amount))
        except ApiError as exc:
            # The server is the authority: whatever it refused, say so here and
            # leave the form as it is so nothing typed has to be typed again.
            self.banner.show_error(exc.message)
        else:
            self.accept()
        finally:
            self._set_busy(busy=False)

    def _set_busy(self, *, busy: bool) -> None:
        self.save_button.setEnabled(not busy)
        # The request that follows blocks the event loop, so the disabled state
        # would never be painted without an explicit repaint.
        self.save_button.repaint()

    @property
    def transaction_id(self) -> int | None:
        """The id being edited, or None when adding."""
        return self._existing.id if self._existing is not None else None
