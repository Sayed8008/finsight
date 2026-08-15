"""The dashboard: the first screen, and the only one that reads from everything.

One request fills it. Five would mean five loading states and five chances to
show figures taken at five different moments — the net for March beside a budget
count from a second later.

Nothing here is computed. Totals, shares, budget counts and the subscription
commitment all arrive worked out; this file decides layout and wording only.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import Dashboard, Transaction
from client.widgets.forms import MessageBanner
from client.widgets.spending_chart import SpendingChart
from client.widgets.stat_tile import NEGATIVE, POSITIVE, HeroTile, StatTile

logger = logging.getLogger(__name__)


class DashboardView(QWidget):
    """Headline figures, where the money went, and what needs attention."""

    #: Asks the shell to open another section. The dashboard points at things;
    #: it does not reproduce the screens that own them.
    navigate_requested = Signal(str)

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardView")
        self._api = api_client

        self._dashboard = Dashboard.empty()
        self._currency = ""
        self._loaded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("DashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        page = QWidget()
        page.setObjectName("DashboardPage")
        scroll.setWidget(page)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        layout.addLayout(self._build_header())

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        layout.addWidget(self._build_tiles())
        layout.addWidget(self._build_middle(), stretch=1)
        layout.addWidget(self._build_attention())
        layout.addStretch(0)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.greeting = QLabel("Dashboard")
        self.greeting.setObjectName("SectionTitle")
        row.addWidget(self.greeting)

        self.period_label = QLabel("")
        self.period_label.setObjectName("SectionSubtitle")
        row.addWidget(self.period_label)

        row.addStretch(1)
        return row

    def _build_tiles(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("TileRow")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        # The hero is "kept", not "spent": what a month leaves behind is the
        # figure that decides whether it went well.
        self.net_tile = HeroTile("Kept this period")
        row.addWidget(self.net_tile, stretch=2)

        self.income_tile = StatTile("Money in")
        row.addWidget(self.income_tile, stretch=1)

        self.expense_tile = StatTile("Money out")
        row.addWidget(self.expense_tile, stretch=1)

        self.commitment_tile = StatTile("Subscriptions")
        row.addWidget(self.commitment_tile, stretch=1)

        return holder

    def _build_middle(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("DashboardMiddle")
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        grid.addWidget(self._build_chart_panel(), 0, 0)
        grid.addWidget(self._build_recent_panel(), 0, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

        return holder

    def _build_chart_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DashboardPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        title = QLabel("Where the money went")
        title.setObjectName("PanelTitle")
        box.addWidget(title)

        self.chart = SpendingChart()
        self.chart.setMinimumHeight(240)
        box.addWidget(self.chart, stretch=1)

        return panel

    def _build_recent_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DashboardPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Recent activity")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch(1)

        see_all = QPushButton("See all")
        see_all.setObjectName("LinkButton")
        see_all.setCursor(Qt.CursorShape.PointingHandCursor)
        see_all.clicked.connect(lambda: self.navigate_requested.emit("transactions"))
        header.addWidget(see_all)
        box.addLayout(header)

        self._recent_holder = QWidget()
        self._recent_holder.setObjectName("RecentList")
        self._recent_layout = QVBoxLayout(self._recent_holder)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(0)
        self._recent_layout.addStretch(1)
        box.addWidget(self._recent_holder, stretch=1)

        self.recent_empty = QLabel("Nothing recorded yet.")
        self.recent_empty.setObjectName("EmptyMessage")
        self.recent_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.recent_empty)

        return panel

    def _build_attention(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("AttentionBar")
        row = QHBoxLayout(panel)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(12)

        self.attention_label = QLabel("")
        self.attention_label.setObjectName("AttentionText")
        row.addWidget(self.attention_label)

        row.addStretch(1)

        self.budgets_button = QPushButton("Open budgets")
        self.budgets_button.setObjectName("SecondaryButton")
        self.budgets_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.budgets_button.clicked.connect(lambda: self.navigate_requested.emit("budgets"))
        row.addWidget(self.budgets_button)

        self.subscriptions_button = QPushButton("Open subscriptions")
        self.subscriptions_button.setObjectName("SecondaryButton")
        self.subscriptions_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subscriptions_button.clicked.connect(
            lambda: self.navigate_requested.emit("subscriptions")
        )
        row.addWidget(self.subscriptions_button)

        self.insights_button = QPushButton("See all insights")
        self.insights_button.setObjectName("SecondaryButton")
        self.insights_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.insights_button.clicked.connect(lambda: self.navigate_requested.emit("insights"))
        row.addWidget(self.insights_button)

        self.attention_bar = panel
        return panel

    # ─── Loading ──────────────────────────────────────────────────────────

    def load_once(self, currency: str = "", name: str = "") -> None:
        """Fetch on first open; refresh the greeting every time.

        `name` is the user's *full* name, deliberately. Shortening it means
        guessing which word someone goes by, and that is not decidable from the
        string: "Md. Abu Sayed" has its honorific first, and whether the short
        form is "Abu" or "Sayed" is knowledge the name itself does not carry.
        Greeting someone by their full name is always right.
        """
        self._currency = currency
        self.chart.set_currency(currency)
        if name:
            self.greeting.setText(f"Hello, {name}")

        if self._loaded:
            return
        self._loaded = True
        self.reload()

    def reload(self) -> None:
        """Fetch the whole dashboard in one request."""
        try:
            dashboard = self._api.dashboard()
        except ApiError as exc:
            self._show_error(exc)
            return

        self.banner.clear_message()
        self._dashboard = dashboard
        self._render()

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render(self) -> None:
        data = self._dashboard
        self.period_label.setText(self._period_text(data.period_start, data.period_end))

        totals = data.totals
        self.net_tile.set_value(
            self._money(totals.net),
            tone=NEGATIVE if totals.overspent else POSITIVE,
            detail=(
                "More went out than came in"
                if totals.overspent
                else f"from {totals.transaction_count} transaction"
                f"{'s' if totals.transaction_count != 1 else ''}"
            ),
        )
        self.income_tile.set_value(self._money(totals.income))
        self.expense_tile.set_value(self._money(totals.expense))

        commitment = data.subscriptions
        self.commitment_tile.set_value(
            self._money(commitment.monthly_total),
            detail=(
                f"{commitment.active_count} active" if commitment.active_count else "None tracked"
            ),
        )

        self.chart.set_shares(data.spending)
        self._render_recent(data.recent)
        self._render_attention()

    @staticmethod
    def _period_text(start: date, end: date) -> str:
        if (start.year, start.month) == (end.year, end.month):
            return f"{start:%B %Y}"
        return f"{start:%d %b %Y} – {end:%d %b %Y}"

    def _render_recent(self, recent: tuple[Transaction, ...]) -> None:
        for index in reversed(range(self._recent_layout.count())):
            widget = self._recent_layout.itemAt(index).widget()
            if widget is not None:
                self._recent_layout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

        self.recent_empty.setVisible(not recent)
        self._recent_holder.setVisible(bool(recent))

        for transaction in recent:
            self._recent_layout.insertWidget(
                self._recent_layout.count() - 1, self._recent_row(transaction)
            )

    def _recent_row(self, transaction: Transaction) -> QWidget:
        row = QWidget()
        row.setObjectName("RecentRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(1)

        description = QLabel(transaction.description or transaction.category.name)
        description.setObjectName("RecentDescription")
        left.addWidget(description)

        meta = QLabel(f"{transaction.category.name} · {transaction.date:%d %b}")
        meta.setObjectName("RecentMeta")
        left.addWidget(meta)
        layout.addLayout(left)

        layout.addStretch(1)

        sign = "+" if transaction.is_income else "−"
        amount = QLabel(f"{sign}{self._money(transaction.amount)}")
        amount.setObjectName("RecentAmount")
        # The same green/red the transactions table uses, so the two screens
        # agree about what a colour means.
        amount.setProperty("direction", "income" if transaction.is_income else "expense")
        layout.addWidget(amount)

        return row

    def _render_attention(self) -> None:
        """Show the most urgent insight, or say there is nothing.

        This used to work out its own line from budget counts and the next
        renewal — a second place deciding what deserves attention, free to
        disagree with the insights screen about it. It now renders the top
        insight the server already ranked (ADR-008), so the application has one
        set of thresholds rather than two.
        """
        insights = self._dashboard.insights
        needs = self._dashboard.needs_attention

        if not insights:
            self.attention_label.setText("Nothing needs attention")
            self._set_attention_state("calm")
            return

        top = insights[0]
        extra = len(insights) - 1
        suffix = f" · {extra} more" if extra else ""
        self.attention_label.setText(f"{top.title} — {top.detail}{suffix}")
        self._set_attention_state("warning" if needs else "calm")

    def _set_attention_state(self, state: str) -> None:
        self.attention_bar.setProperty("state", state)
        self.attention_bar.style().unpolish(self.attention_bar)
        self.attention_bar.style().polish(self.attention_bar)

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()

    # ─── Failure ──────────────────────────────────────────────────────────

    def _show_error(self, exc: ApiError) -> None:
        logger.warning("Dashboard request failed: %s", exc.message)
        self.banner.show_error(exc.message)
        self._dashboard = Dashboard.empty()
        self._render()
        self.period_label.setText("")
