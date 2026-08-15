"""One subscription, rendered as a card.

Like `BudgetCard`, this displays and decides nothing: the cost equivalents,
`days_until_renewal` and `is_due_soon` all arrive computed, so the 52-weeks
conversion and the due-soon window exist in one place on the server.

The renewal line is the reason a card beats a table row here. "in 3 days" is
the fact the user is looking for, and it deserves more room than a date column
would give it.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api.dto import ACTIVE, CANCELLED, PAUSED, Subscription

#: What each status looks like in the interface. Cancelled is greyed rather
#: than hidden — it is history, and hiding it would make the list look wrong to
#: someone who remembers cancelling something.
STATUS_LABELS = {ACTIVE: "Active", PAUSED: "Paused", CANCELLED: "Cancelled"}


class SubscriptionCard(QFrame):
    """A single subscription: name, cost, cycle, and when it renews."""

    edit_requested = Signal(int)
    delete_requested = Signal(int)
    renew_requested = Signal(int)

    def __init__(
        self, subscription: Subscription, currency: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.subscription = subscription
        self._currency = currency

        self.setObjectName("SubscriptionCard")
        self.setProperty("state", self._state())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        layout.addLayout(self._build_header())
        layout.addLayout(self._build_details())

    def _state(self) -> str:
        """The visual state, which is not quite the stored status.

        An active subscription whose date has passed is "overdue" — worth
        flagging, because it means either a charge went unnoticed or the record
        needs updating. The stored status has no value for that.
        """
        if self.subscription.status != ACTIVE:
            return self.subscription.status
        return "overdue" if self.subscription.is_overdue else ACTIVE

    # ─── Header ───────────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        name = QLabel(self.subscription.name)
        name.setObjectName("SubscriptionName")
        row.addWidget(name)

        badge = QLabel(self._badge_text())
        badge.setObjectName("SubscriptionBadge")
        badge.setProperty("state", self._state())
        row.addWidget(badge)

        row.addStretch(1)

        self.renew_button = QPushButton("Mark renewed")
        self.renew_button.setObjectName("SecondaryButton")
        self.renew_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.renew_button.setToolTip("Record that this charge was taken and move to the next")
        # Renewing a cancelled subscription is refused by the server, so the
        # button is not offered rather than offered and rejected.
        self.renew_button.setEnabled(self.subscription.status != CANCELLED)
        self.renew_button.clicked.connect(lambda: self.renew_requested.emit(self.subscription.id))
        row.addWidget(self.renew_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("SecondaryButton")
        self.edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self.subscription.id))
        row.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.subscription.id))
        row.addWidget(self.delete_button)

        return row

    def _badge_text(self) -> str:
        if self._state() == "overdue":
            return "Overdue"
        return STATUS_LABELS.get(self.subscription.status, self.subscription.status.title())

    # ─── Details ──────────────────────────────────────────────────────────

    def _build_details(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        cost = QLabel(
            f"{self._money(self.subscription.amount)} {self.subscription.cycle_label.lower()}"
            f" · {self._money(self.subscription.monthly_cost)}/month"
        )
        cost.setObjectName("SubscriptionCost")
        row.addWidget(cost)

        if self.subscription.category is not None:
            category = QLabel(f"· {self.subscription.category.name}")
            category.setObjectName("SubscriptionCategory")
            row.addWidget(category)

        row.addStretch(1)

        self.renewal_label = QLabel(self.renewal_text())
        self.renewal_label.setObjectName("SubscriptionRenewal")
        self.renewal_label.setProperty("state", self._state())
        row.addWidget(self.renewal_label)

        return row

    def renewal_text(self) -> str:
        """When the next charge falls, in words.

        "in 3 days" rather than a bare date: the number of days is the thing
        being looked for, and working it out from a date is work the interface
        should have done.
        """
        subscription = self.subscription
        when = f"{subscription.next_billing_date:%d %b %Y}"

        if subscription.status == CANCELLED:
            return "Cancelled"
        if subscription.status == PAUSED:
            return f"Paused · would renew {when}"

        days = subscription.days_until_renewal
        if days < 0:
            overdue = -days
            return f"Overdue by {overdue} day{'s' if overdue != 1 else ''} · {when}"
        if days == 0:
            return f"Renews today · {when}"
        if days == 1:
            return f"Renews tomorrow · {when}"
        return f"Renews in {days} days · {when}"

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()
