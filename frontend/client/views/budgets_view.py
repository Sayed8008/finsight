"""The budgets screen: a summary strip and one card per budget.

Nothing here recomputes a budget. Spent, remaining, percentage and status all
arrive from the server, which is where the transactions are and where the
thresholds are defined (ADR-015, ADR-021). The only arithmetic in this file is
adding up the cards on screen for the summary strip, which is presentation:
three totals of numbers already fetched, not a second opinion about any of them.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import EXPENSE, Budget, Category
from client.widgets.budget_card import BudgetCard
from client.widgets.budget_dialog import BudgetDialog
from client.widgets.confirm import confirm
from client.widgets.forms import LabelledWidget, MessageBanner

logger = logging.getLogger(__name__)

CARDS_PAGE = 0
EMPTY_PAGE = 1

ZERO = Decimal("0.00")

#: How far apart consecutive budget bars begin filling, and the most any one
#: card will wait. Small enough to read as one movement across the list rather
#: than as a queue.
BAR_STAGGER_MS = 55
BAR_STAGGER_CAP_MS = 260


class BudgetsView(QWidget):
    """The Budgets section of the application."""

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BudgetsView")
        self._api = api_client

        self._categories: list[Category] = []
        self._budgets: list[Budget] = []
        self._currency = ""
        self._loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)

        layout.addLayout(self._build_header())

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        layout.addWidget(self._build_controls())
        layout.addWidget(self._build_summary())

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_card_area())
        self._pages.addWidget(self._build_empty_state())
        layout.addWidget(self._pages, stretch=1)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("Budgets")
        title.setObjectName("SectionTitle")
        row.addWidget(title)

        self.count_label = QLabel("")
        self.count_label.setObjectName("SectionSubtitle")
        row.addWidget(self.count_label)

        row.addStretch(1)

        self.add_button = QPushButton("Set a budget")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.add_budget)
        row.addWidget(self.add_button)

        return row

    def _build_controls(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("FilterBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(16)

        self.category_filter = QComboBox()
        self.category_filter.setObjectName("FieldSelect")
        self.category_filter.addItem("All categories", None)
        # Bounded rather than stretched: one control taking half the bar to
        # hold the words "All categories" reads as a layout mistake.
        self.category_filter.setMinimumWidth(200)
        self.category_filter.setMaximumWidth(260)
        self.category_filter.currentIndexChanged.connect(self.reload)
        row.addWidget(LabelledWidget("Category", self.category_filter))

        self.current_only = QCheckBox("Only budgets running now")
        self.current_only.setObjectName("FilterCheck")
        self.current_only.setCursor(Qt.CursorShape.PointingHandCursor)
        self.current_only.stateChanged.connect(self.reload)
        row.addWidget(self.current_only, alignment=Qt.AlignmentFlag.AlignBottom)

        row.addStretch(1)
        return bar

    def _build_summary(self) -> QWidget:
        self.summary = QFrame()
        self.summary.setObjectName("SummaryStrip")
        row = QHBoxLayout(self.summary)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(28)

        self.total_budgeted = self._summary_figure(row, "Budgeted")
        self.total_spent = self._summary_figure(row, "Spent")
        self.total_remaining = self._summary_figure(row, "Remaining")
        row.addStretch(1)

        return self.summary

    @staticmethod
    def _summary_figure(row: QHBoxLayout, caption: str) -> QLabel:
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

    def _build_card_area(self) -> QWidget:
        self._card_holder = QWidget()
        self._card_holder.setObjectName("CardHolder")
        self._card_layout = QVBoxLayout(self._card_holder)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(12)
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

        self.empty_title = QLabel("No budgets yet")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel("Set one to track spending against a limit.")
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_message)

        return panel

    # ─── Loading ──────────────────────────────────────────────────────────

    def load_once(self, currency: str = "") -> None:
        """The one-off category lookup, the first time this section is opened.

        The budgets themselves are fetched by `reload`, which the shell calls
        every time the section is shown — utilisation moves whenever a
        transaction is added anywhere else.
        """
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
        self._budgets = []
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
        """Load the category list once, for the filter and the dialog."""
        try:
            self._categories = self._api.categories()
        except ApiError as exc:
            self._show_error(exc)
            return

        previous = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All categories", None)
        for category in self._categories:
            # Only expense categories can carry a budget, so filtering by an
            # income one would always return nothing.
            if category.category_type == EXPENSE:
                self.category_filter.addItem(category.name, category.id)
        if previous is not None:
            index = self.category_filter.findData(previous)
            if index >= 0:
                self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def reload(self) -> None:
        """Fetch budgets with the current filters and rebuild the cards."""
        try:
            budgets = self._api.budgets(
                category_id=self.category_filter.currentData(),
                current_only=self.current_only.isChecked(),
            )
        except ApiError as exc:
            self._show_error(exc)
            return

        self.banner.clear_message()
        self._budgets = budgets
        self._render_cards()
        self._render_summary()

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render_cards(self) -> None:
        """Rebuild the card list.

        Cards are destroyed and recreated rather than updated in place. There
        are tens of them, not thousands, and a card holds no state worth
        preserving — rebuilding is simpler than diffing, and cannot leave a
        stale figure on screen.
        """
        self._clear_cards()

        cards: list[BudgetCard] = []
        for budget in self._budgets:
            card = BudgetCard(budget, currency=self._currency)
            card.edit_requested.connect(self.edit_budget)
            card.delete_requested.connect(self.delete_budget)
            # Inserted before the trailing stretch, so cards stack from the top
            # instead of spreading down the page.
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)
            cards.append(card)

        self._pages.setCurrentIndex(CARDS_PAGE if self._budgets else EMPTY_PAGE)
        if not self._budgets:
            self._describe_empty_state()

        count = len(self._budgets)
        self.count_label.setText(f"{count} budget{'s' if count != 1 else ''}" if count else "")

        # Filled on the next turn of the event loop, not here: `_activate`
        # runs before the shell switches to this page, so at this moment the
        # cards have no geometry and are not on screen. A fill nobody can see
        # is a fill that has already finished by the time they look.
        QTimer.singleShot(0, lambda: self._fill_bars(cards))

    def _fill_bars(self, cards: list[BudgetCard]) -> None:
        """Grow each card's bar, one just after the last.

        The stagger is deliberately small — 55ms — and capped, so a screen of
        ten budgets still finishes filling in about the time one card takes.
        Cards arriving in sequence reads as a list being drawn; cards arriving
        together reads as a single flash, and cards arriving half a second
        apart reads as waiting.
        """
        for index, card in enumerate(cards):
            try:
                card.animate_bar(delay_ms=min(index * BAR_STAGGER_MS, BAR_STAGGER_CAP_MS))
            except RuntimeError:
                # The card was destroyed by a reload before the timer fired.
                return

    def _clear_cards(self) -> None:
        for index in reversed(range(self._card_layout.count())):
            item = self._card_layout.itemAt(index)
            widget = item.widget()
            if widget is not None:
                self._card_layout.takeAt(index)
                # `deleteLater` rather than an immediate delete: the click that
                # triggered this rebuild may still be being handled by the very
                # card about to be destroyed.
                widget.setParent(None)
                widget.deleteLater()

    def _render_summary(self) -> None:
        """Total the cards on screen.

        Presentation only — a sum of figures the server already computed, not a
        second opinion about any of them.
        """
        if not self._budgets:
            for label in (self.total_budgeted, self.total_spent, self.total_remaining):
                label.setText("—")
            self.summary.setVisible(False)
            return

        self.summary.setVisible(True)
        budgeted = sum((b.amount for b in self._budgets), ZERO)
        spent = sum((b.spent for b in self._budgets), ZERO)
        remaining = budgeted - spent

        self.total_budgeted.setText(self._money(budgeted))
        self.total_spent.setText(self._money(spent))
        self.total_remaining.setText(self._money(remaining))
        self.total_remaining.setProperty("status", "exceeded" if remaining < ZERO else "healthy")
        self.total_remaining.style().unpolish(self.total_remaining)
        self.total_remaining.style().polish(self.total_remaining)

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()

    def _describe_empty_state(self) -> None:
        if self.category_filter.currentData() is not None or self.current_only.isChecked():
            self.empty_title.setText("No budgets match")
            self.empty_message.setText("Try clearing the filters above.")
        else:
            self.empty_title.setText("No budgets yet")
            self.empty_message.setText("Set one to track spending against a limit.")

    # ─── Actions ──────────────────────────────────────────────────────────

    def budget_by_id(self, budget_id: int) -> Budget | None:
        return next((b for b in self._budgets if b.id == budget_id), None)

    def add_budget(self) -> None:
        if not any(c.category_type == EXPENSE for c in self._categories):
            self.banner.show_error("No expense categories are available to budget.")
            return

        dialog = BudgetDialog(
            self._categories,
            save=lambda payload: self._api.create_budget(**payload),
            currency=self._currency,
            parent=self,
        )
        if dialog.exec():
            self.refresh_categories()
            self.reload()

    def edit_budget(self, budget_id: int) -> None:
        budget = self.budget_by_id(budget_id)
        if budget is None:
            return

        dialog = BudgetDialog(
            self._categories,
            save=lambda payload: self._api.update_budget(budget_id, **payload),
            budget=budget,
            currency=self._currency,
            parent=self,
        )
        if dialog.exec():
            self.refresh_categories()
            self.reload()

    def delete_budget(self, budget_id: int) -> None:
        """Delete a budget, after confirming.

        The question names the category and period, because "are you sure?" on
        its own does not let anyone check they clicked the right card.
        """
        budget = self.budget_by_id(budget_id)
        if budget is None:
            return

        if not confirm(
            self,
            "Delete budget",
            f"Delete the {budget.category.name} budget for "
            f"{budget.period_start:%d %b} – {budget.period_end:%d %b %Y}?\n\n"
            "Your transactions are not affected.",
        ):
            return

        try:
            self._api.delete_budget(budget_id)
        except ApiError as exc:
            self._show_error(exc)
            return

        self.reload()

    # ─── Failure ──────────────────────────────────────────────────────────

    def _show_error(self, exc: ApiError) -> None:
        logger.warning("Budgets request failed: %s", exc.message)
        self.banner.show_error(exc.message)
        self._budgets = []
        self._clear_cards()
        self._render_summary()
        self._pages.setCurrentIndex(EMPTY_PAGE)
        self.empty_title.setText("Could not load budgets")
        self.empty_message.setText(exc.message)
        self.count_label.setText("")
