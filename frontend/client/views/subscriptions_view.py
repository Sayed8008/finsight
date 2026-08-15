"""The subscriptions screen: what you pay for, and what renews next.

The summary strip is fetched, not computed. Unlike the budgets screen — which
totals the cards on display, a presentation sum — the recurring commitment
comes from `GET /subscriptions/summary`, because it must reflect *every* active
subscription regardless of the filters, and because converting weekly to
monthly is arithmetic that belongs on one side of the wire only.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import ACTIVE, CANCELLED, PAUSED, Category, Subscription, SubscriptionSummary
from client.widgets.busy import working
from client.widgets.detection_dialog import DetectionDialog
from client.widgets.forms import LabelledWidget, MessageBanner
from client.widgets.subscription_card import SubscriptionCard
from client.widgets.subscription_dialog import SubscriptionDialog

logger = logging.getLogger(__name__)

CARDS_PAGE = 0
EMPTY_PAGE = 1

#: The "renewing soon" filter. A week matches the server's own due-soon window.
DUE_SOON_DAYS = 7

STATUS_FILTERS: tuple[tuple[str, str | None], ...] = (
    ("All statuses", None),
    ("Active", ACTIVE),
    ("Paused", PAUSED),
    ("Cancelled", CANCELLED),
)


class SubscriptionsView(QWidget):
    """The Subscriptions section of the application."""

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SubscriptionsView")
        self._api = api_client

        self._categories: list[Category] = []
        self._subscriptions: list[Subscription] = []
        self._summary = SubscriptionSummary.empty()
        self._payment_methods: list[str] = []
        self._currency = ""
        self._loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)

        layout.addLayout(self._build_header())

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        layout.addWidget(self._build_summary())
        layout.addWidget(self._build_controls())

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_card_area())
        self._pages.addWidget(self._build_empty_state())
        layout.addWidget(self._pages, stretch=1)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("Subscriptions")
        title.setObjectName("SectionTitle")
        row.addWidget(title)

        self.count_label = QLabel("")
        self.count_label.setObjectName("SectionSubtitle")
        row.addWidget(self.count_label)

        row.addStretch(1)

        self.detect_button = QPushButton("Find subscriptions")
        self.detect_button.setObjectName("SecondaryButton")
        self.detect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detect_button.setToolTip(
            "Look for recurring charges in your transaction history. Nothing is "
            "added without your say-so."
        )
        self.detect_button.clicked.connect(self.find_subscriptions)
        row.addWidget(self.detect_button)

        self.add_button = QPushButton("Track a subscription")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_subscription)
        row.addWidget(self.add_button)

        return row

    def _build_summary(self) -> QWidget:
        self.summary_strip = QFrame()
        self.summary_strip.setObjectName("SummaryStrip")
        row = QHBoxLayout(self.summary_strip)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(28)

        self.monthly_total = self._figure(row, "Per month")
        self.yearly_total = self._figure(row, "Per year")
        self.active_total = self._figure(row, "Active")
        self.next_renewal = self._figure(row, "Renews next")
        row.addStretch(1)

        return self.summary_strip

    @staticmethod
    def _figure(row: QHBoxLayout, caption: str) -> QLabel:
        box = QVBoxLayout()
        box.setSpacing(2)

        label = QLabel(caption)
        label.setObjectName("SummaryCaption")
        box.addWidget(label)

        value = QLabel("—")
        value.setObjectName("SummaryValue")
        box.addWidget(value)

        row.addLayout(box)
        return value

    def _build_controls(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("FilterBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(16)

        self.status_filter = QComboBox()
        self.status_filter.setObjectName("FieldSelect")
        self.status_filter.setMinimumWidth(160)
        self.status_filter.setMaximumWidth(200)
        for label, value in STATUS_FILTERS:
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self.reload)
        row.addWidget(LabelledWidget("Status", self.status_filter))

        self.category_filter = QComboBox()
        self.category_filter.setObjectName("FieldSelect")
        self.category_filter.setMinimumWidth(180)
        self.category_filter.setMaximumWidth(240)
        self.category_filter.addItem("All categories", None)
        self.category_filter.currentIndexChanged.connect(self.reload)
        row.addWidget(LabelledWidget("Category", self.category_filter))

        self.due_soon_only = QCheckBox("Renewing within a week")
        self.due_soon_only.setObjectName("FilterCheck")
        self.due_soon_only.setCursor(Qt.CursorShape.PointingHandCursor)
        self.due_soon_only.stateChanged.connect(self.reload)
        row.addWidget(self.due_soon_only, alignment=Qt.AlignmentFlag.AlignBottom)

        row.addStretch(1)
        return bar

    def _build_card_area(self) -> QWidget:
        self._card_holder = QWidget()
        self._card_holder.setObjectName("CardHolder")
        self._card_layout = QVBoxLayout(self._card_holder)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(10)
        self._card_layout.addStretch(1)

        area = QScrollArea()
        area.setObjectName("CardScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(self._card_holder)
        return area

    def _build_empty_state(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("EmptyState")
        box = QVBoxLayout(panel)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(8)

        self.empty_title = QLabel("Nothing tracked yet")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel("Add a subscription to see what it costs you.")
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_message)

        return panel

    # ─── Loading ──────────────────────────────────────────────────────────

    def load_once(self, currency: str = "") -> None:
        """The one-off lookups. `reload` fetches the subscriptions themselves,
        and the shell calls it every time this section is shown."""
        self._currency = currency
        if self._loaded:
            return
        self._loaded = True
        self.refresh_categories()

    def reset(self) -> None:
        """Forget this session's data. See `DashboardView.reset`."""
        self._loaded = False
        self._currency = ""
        self._categories = []
        self._subscriptions = []
        self._payment_methods = []
        self._summary = SubscriptionSummary.empty()
        self._clear_cards()
        self.banner.clear_message()

    @property
    def is_loaded(self) -> bool:
        """Whether this section has fetched anything yet.

        Asked by the shell before refreshing category pickers: a section nobody
        has opened has no picker to refresh, and forcing one would make a
        request for a screen the user may never look at.
        """
        return self._loaded

    def refresh_categories(self) -> None:
        """Load categories and payment methods once, for the filter and dialog."""
        try:
            self._categories = self._api.categories()
            self._payment_methods = self._api.payment_methods()
        except ApiError as exc:
            self._show_error(exc)
            return

        previous = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All categories", None)
        for category in self._categories:
            self.category_filter.addItem(category.name, category.id)
        if previous is not None:
            index = self.category_filter.findData(previous)
            if index >= 0:
                self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def reload(self) -> None:
        """Fetch subscriptions and the commitment summary."""
        try:
            subscriptions = self._api.subscriptions(
                status=self.status_filter.currentData(),
                category_id=self.category_filter.currentData(),
                due_within_days=DUE_SOON_DAYS if self.due_soon_only.isChecked() else None,
            )
            summary = self._api.subscription_summary()
        except ApiError as exc:
            self._show_error(exc)
            return

        self.banner.clear_message()
        self._subscriptions = subscriptions
        self._summary = summary
        self._render_cards()
        self._render_summary()

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render_cards(self) -> None:
        self._clear_cards()

        for subscription in self._subscriptions:
            card = SubscriptionCard(subscription, currency=self._currency)
            card.edit_requested.connect(self.edit_subscription)
            card.delete_requested.connect(self.delete_subscription)
            card.renew_requested.connect(self.renew_subscription)
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)

        self._pages.setCurrentIndex(CARDS_PAGE if self._subscriptions else EMPTY_PAGE)
        if not self._subscriptions:
            self._describe_empty_state()

        count = len(self._subscriptions)
        self.count_label.setText(f"{count} shown" if count else "")

    def _clear_cards(self) -> None:
        for index in reversed(range(self._card_layout.count())):
            widget = self._card_layout.itemAt(index).widget()
            if widget is not None:
                self._card_layout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

    def _render_summary(self) -> None:
        """Show the commitment. These figures come from the server, not the cards.

        Deliberately unaffected by the filters: "what do I pay each month" must
        not change because the list is filtered to one category.
        """
        summary = self._summary
        self.monthly_total.setText(self._money(summary.monthly_total))
        self.yearly_total.setText(self._money(summary.yearly_total))

        counts = f"{summary.active_count}"
        if summary.paused_count:
            counts += f" · {summary.paused_count} paused"
        self.active_total.setText(counts)

        if summary.next_renewal is None:
            self.next_renewal.setText("—")
        else:
            upcoming = summary.next_renewal
            self.next_renewal.setText(f"{upcoming.name} · {upcoming.next_billing_date:%d %b}")
            self.next_renewal.setProperty("status", "exceeded" if upcoming.is_overdue else "")
            self.next_renewal.style().unpolish(self.next_renewal)
            self.next_renewal.style().polish(self.next_renewal)

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()

    def _describe_empty_state(self) -> None:
        filtered = (
            self.status_filter.currentData() is not None
            or self.category_filter.currentData() is not None
            or self.due_soon_only.isChecked()
        )
        if filtered:
            self.empty_title.setText("Nothing matches")
            self.empty_message.setText("Try clearing the filters above.")
        else:
            self.empty_title.setText("Nothing tracked yet")
            self.empty_message.setText("Add a subscription to see what it costs you.")

    # ─── Actions ──────────────────────────────────────────────────────────

    def subscription_by_id(self, subscription_id: int) -> Subscription | None:
        return next((s for s in self._subscriptions if s.id == subscription_id), None)

    def add_subscription(self) -> None:
        dialog = SubscriptionDialog(
            self._categories,
            save=lambda payload: self._api.create_subscription(**payload),
            payment_methods=self._payment_methods,
            currency=self._currency,
            parent=self,
        )
        if dialog.exec():
            self.reload()

    def find_subscriptions(self) -> None:
        """Search transaction history and review whatever it proposes.

        The search happens here; the *creating* happens one candidate at a time
        inside the dialog, and only when the user asks for it (ADR-007).
        """
        try:
            with working(
                banner=self.banner,
                message="Searching your transaction history…",
                disable=(self.detect_button, self.add_button),
            ):
                detection = self._api.detect_subscriptions()
        except ApiError as exc:
            self._show_error(exc)
            return

        self.banner.clear_message()
        dialog = DetectionDialog(
            detection,
            track=lambda candidate: self._api.create_subscription(**candidate.as_subscription()),
            currency=self._currency,
            parent=self,
        )
        dialog.exec()

        if dialog.tracked_anything:
            self.reload()

    def edit_subscription(self, subscription_id: int) -> None:
        subscription = self.subscription_by_id(subscription_id)
        if subscription is None:
            return

        dialog = SubscriptionDialog(
            self._categories,
            save=lambda payload: self._api.update_subscription(subscription_id, **payload),
            subscription=subscription,
            payment_methods=self._payment_methods,
            currency=self._currency,
            parent=self,
        )
        if dialog.exec():
            self.reload()

    def renew_subscription(self, subscription_id: int) -> None:
        """Record that a charge was taken.

        Confirmed first: it moves the billing date, and clicking it twice by
        accident would skip a month with nothing to show that it happened.
        """
        subscription = self.subscription_by_id(subscription_id)
        if subscription is None:
            return

        answer = QMessageBox.question(
            self,
            "Mark as renewed",
            f"Record that {subscription.name} was charged on "
            f"{subscription.next_billing_date:%d %b %Y}?\n\n"
            "The next billing date moves forward one cycle.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        try:
            self._api.renew_subscription(subscription_id)
        except ApiError as exc:
            self._show_error(exc)
            return

        self.reload()

    def delete_subscription(self, subscription_id: int) -> None:
        subscription = self.subscription_by_id(subscription_id)
        if subscription is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete subscription",
            f"Delete {subscription.name}?\n\n"
            "This removes the record entirely. To keep the history, set its "
            "status to Cancelled instead.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        try:
            self._api.delete_subscription(subscription_id)
        except ApiError as exc:
            self._show_error(exc)
            return

        self.reload()

    # ─── Failure ──────────────────────────────────────────────────────────

    def _show_error(self, exc: ApiError) -> None:
        logger.warning("Subscriptions request failed: %s", exc.message)
        self.banner.show_error(exc.message)
        self._subscriptions = []
        self._clear_cards()
        self._pages.setCurrentIndex(EMPTY_PAGE)
        self.empty_title.setText("Could not load subscriptions")
        self.empty_message.setText(exc.message)
        self.count_label.setText("")
