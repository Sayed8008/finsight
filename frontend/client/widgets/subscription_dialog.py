"""The track/edit subscription form.

Same contract as the other dialogs: given a `save` callable, knows nothing
about HTTP, stays open and explains itself when the server refuses.

`next_billing_date` is deliberately not a field. It is derived from the start
date and the cycle, so offering it would invite a user to enter three things
that contradict each other. The dialog shows what the next charge *will* be
instead, updated as the other two change.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiError
from client.api.dto import ACTIVE, CANCELLED, CYCLE_LABELS, PAUSED, Category, Subscription
from client.widgets.forms import (
    FormField,
    LabelledWidget,
    MessageBanner,
    payment_method_options,
)

logger = logging.getLogger(__name__)

LARGEST_AMOUNT = Decimal("1000000000000.00")
MAX_NOTES_LENGTH = 2000

STATUS_CHOICES = ((ACTIVE, "Active"), (PAUSED, "Paused"), (CANCELLED, "Cancelled"))


class SubscriptionDialog(QDialog):
    """Collect the fields of a subscription, then hand them to `save`."""

    def __init__(
        self,
        categories: list[Category],
        *,
        save: Callable[[dict[str, Any]], object],
        subscription: Subscription | None = None,
        payment_methods: list[str] | None = None,
        currency: str = "",
        today: date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._save = save
        self._existing = subscription
        self._today = today or date.today()
        self._categories = categories

        editing = subscription is not None
        self.setWindowTitle("Edit subscription" if editing else "Track a subscription")
        self.setObjectName("SubscriptionDialog")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        # ─── Name and amount ──────────────────────────────────────────────
        self.name_field = FormField("Name", placeholder="Netflix, Spotify…")
        self.amount_field = FormField(
            f"Amount{f' ({currency})' if currency else ''}", placeholder="0.00"
        )

        first = QHBoxLayout()
        first.setSpacing(12)
        first.addWidget(self.name_field, stretch=2)
        first.addWidget(self.amount_field, stretch=1)
        layout.addLayout(first)

        # ─── Cycle and start ──────────────────────────────────────────────
        self.cycle_box = QComboBox()
        self.cycle_box.setObjectName("FieldSelect")
        for value, label in CYCLE_LABELS.items():
            self.cycle_box.addItem(label, value)
        self.cycle_box.setCurrentIndex(self.cycle_box.findData("monthly"))

        self.start_edit = QDateEdit()
        self.start_edit.setObjectName("FieldSelect")
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("dd MMM yyyy")
        self.start_edit.setDate(QDate(self._today.year, self._today.month, self._today.day))

        second = QHBoxLayout()
        second.setSpacing(12)
        second.addWidget(LabelledWidget("Billing cycle", self.cycle_box), stretch=1)
        second.addWidget(LabelledWidget("First charge", self.start_edit), stretch=1)
        layout.addLayout(second)

        # ─── Category, status, payment method ─────────────────────────────
        self.category_box = QComboBox()
        self.category_box.setObjectName("FieldSelect")
        # None is a real choice here, not a placeholder: a subscription may be
        # tracked before anyone decides where it belongs.
        self.category_box.addItem("No category", None)
        for category in categories:
            self.category_box.addItem(category.name, category.id)

        self.status_box = QComboBox()
        self.status_box.setObjectName("FieldSelect")
        for value, label in STATUS_CHOICES:
            self.status_box.addItem(label, value)

        third = QHBoxLayout()
        third.setSpacing(12)
        third.addWidget(LabelledWidget("Category", self.category_box), stretch=1)
        third.addWidget(LabelledWidget("Status", self.status_box), stretch=1)
        layout.addLayout(third)

        self.method_box = QComboBox()
        self.method_box.setObjectName("FieldSelect")
        self.method_box.setEditable(True)
        self.method_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.method_box.addItem("")
        self.method_box.addItems(payment_method_options(payment_methods))
        if self.method_box.lineEdit() is not None:
            self.method_box.lineEdit().setPlaceholderText("Card, bKash…")
        layout.addWidget(LabelledWidget("Payment method", self.method_box))

        # ─── Optional end date ────────────────────────────────────────────
        self.has_end_date = QCheckBox("This subscription ends on a set date")
        self.has_end_date.toggled.connect(self._on_end_date_toggled)
        layout.addWidget(self.has_end_date)

        self.end_edit = QDateEdit()
        self.end_edit.setObjectName("FieldSelect")
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("dd MMM yyyy")
        self.end_edit.setDate(QDate(self._today.year + 1, self._today.month, self._today.day))
        self.end_row = LabelledWidget("Ends", self.end_edit)
        self.end_row.setVisible(False)
        layout.addWidget(self.end_row)

        # ─── Notes ────────────────────────────────────────────────────────
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setObjectName("FieldInput")
        self.notes_edit.setPlaceholderText("Anything worth remembering about this plan")
        self.notes_edit.setFixedHeight(64)
        layout.addWidget(LabelledWidget("Notes", self.notes_edit))

        # ─── Buttons ──────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setText("Save changes" if editing else "Track it")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("SecondaryButton")
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if subscription is not None:
            self._fill_from(subscription)

        self.name_field.input.setFocus()

    # ─── End date ─────────────────────────────────────────────────────────

    def _on_end_date_toggled(self, checked: bool) -> None:
        """Hide the date picker unless an end date is actually wanted.

        A date editor cannot be empty, so a visible one with no way to clear it
        would imply every subscription has an end date. The checkbox is what
        expresses "no end date".
        """
        self.end_row.setVisible(checked)

    # ─── Filling ──────────────────────────────────────────────────────────

    def _fill_from(self, subscription: Subscription) -> None:
        self.name_field.input.setText(subscription.name)
        self.amount_field.input.setText(f"{subscription.amount:.2f}")

        cycle_index = self.cycle_box.findData(subscription.billing_cycle)
        if cycle_index >= 0:
            self.cycle_box.setCurrentIndex(cycle_index)

        status_index = self.status_box.findData(subscription.status)
        if status_index >= 0:
            self.status_box.setCurrentIndex(status_index)

        start = subscription.start_date
        self.start_edit.setDate(QDate(start.year, start.month, start.day))

        if subscription.category is not None:
            index = self.category_box.findData(subscription.category.id)
            if index < 0:
                # Retired since, so not in the list. Keeping it means editing
                # the amount does not silently drop the category.
                self.category_box.addItem(
                    f"{subscription.category.name} (retired)", subscription.category.id
                )
                index = self.category_box.findData(subscription.category.id)
            self.category_box.setCurrentIndex(index)

        if subscription.payment_method:
            self.method_box.setCurrentText(subscription.payment_method)
        if subscription.notes:
            self.notes_edit.setPlainText(subscription.notes)

        if subscription.end_date is not None:
            self.has_end_date.setChecked(True)
            end = subscription.end_date
            self.end_edit.setDate(QDate(end.year, end.month, end.day))

    # ─── Submission ───────────────────────────────────────────────────────

    def parse_amount(self) -> Decimal | None:
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
        """The request body.

        `next_billing_date` is absent: the server derives it from the start
        date and the cycle.

        On an edit, the start date and the cycle are sent *only if they
        changed*. The server recomputes the next billing date whenever either
        is present — deliberately, because a subscription may not claim a
        schedule its own anchor contradicts — and it decides "present" with
        `exclude_unset`. So a body that repeats the unchanged anchor reads as
        "the anchor was set", and the recomputed date is the first occurrence
        on or after today.

        That is what made editing a price undo every renewal: a monthly
        subscription anchored 10 Jan and marked renewed twice sat at 10 Nov,
        and saving a new amount moved it back to 10 Sep. The recorded charges
        were gone, and the card then read as overdue.
        """
        notes = self.notes_edit.toPlainText().strip()
        method = self.method_box.currentText().strip()

        body: dict[str, Any] = {
            "name": self.name_field.text().strip(),
            "amount": f"{amount:.2f}",
            "status": self.status_box.currentData(),
            "category_id": self.category_box.currentData(),
            "payment_method": method or None,
            "notes": notes or None,
        }

        cycle = self.cycle_box.currentData()
        start = self.start_edit.date().toString(Qt.DateFormat.ISODate)
        if self._existing is None or cycle != self._existing.billing_cycle:
            body["billing_cycle"] = cycle
        if self._existing is None or start != self._existing.start_date.isoformat():
            body["start_date"] = start

        if self.has_end_date.isChecked():
            body["end_date"] = self.end_edit.date().toString(Qt.DateFormat.ISODate)
        else:
            body["end_date"] = None
        return body

    def submit(self) -> None:
        if not self.name_field.text().strip():
            self.banner.show_error("Give the subscription a name.")
            self.name_field.input.setFocus()
            return

        amount = self.parse_amount()
        if amount is None:
            self.banner.show_error("Enter an amount greater than zero, with at most two decimals.")
            self.amount_field.input.setFocus()
            return

        if self.has_end_date.isChecked() and self.end_edit.date() < self.start_edit.date():
            self.banner.show_error("The end date cannot be before the first charge.")
            return

        if len(self.notes_edit.toPlainText()) > MAX_NOTES_LENGTH:
            self.banner.show_error(f"Notes are limited to {MAX_NOTES_LENGTH} characters.")
            return

        self._set_busy(busy=True)
        try:
            self._save(self.payload(amount))
        except ApiError as exc:
            self.banner.show_error(exc.message)
        else:
            self.accept()
        finally:
            self._set_busy(busy=False)

    def _set_busy(self, *, busy: bool) -> None:
        self.save_button.setEnabled(not busy)
        self.save_button.repaint()

    @property
    def subscription_id(self) -> int | None:
        return self._existing.id if self._existing is not None else None
