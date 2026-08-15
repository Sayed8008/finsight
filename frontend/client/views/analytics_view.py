"""The analytics screen: how things moved, and against what.

Two requests rather than one, unlike the dashboard. These answer two separate
questions and the span control only affects one of them, so bundling them would
mean refetching a comparison that had not changed.

The comparison table is where most of the value is. A number on its own is not
information — 12,000 spent on food only means something beside last month's
8,000 — so every row shows both figures and the movement between them.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import CategoryChange, Change, Comparison, Trend
from client.core.formatting import percentage_text
from client.widgets.forms import LabelledWidget, MessageBanner
from client.widgets.stat_tile import NEGATIVE, NEUTRAL, POSITIVE, StatTile
from client.widgets.trend_chart import TrendChart

logger = logging.getLogger(__name__)

SPANS: tuple[tuple[str, int], ...] = (
    ("Last 3 months", 3),
    ("Last 6 months", 6),
    ("Last 12 months", 12),
    ("Last 24 months", 24),
)

#: How many category rows the comparison shows before it stops. The list is
#: sorted by size of movement, so the tail is by definition the part that
#: barely moved.
MAX_CATEGORY_ROWS = 8

#: What an empty comparison table says when the account genuinely has nothing
#: to compare. Kept apart from the failure wording on purpose: "you have no
#: data" and "we could not fetch your data" call for different acts from the
#: user, and showing the first when the second happened is a quiet lie.
NOTHING_TO_COMPARE = "Nothing to compare yet."


class AnalyticsView(QWidget):
    """Trend over time, and this period against the one before it."""

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnalyticsView")
        self._api = api_client

        self._trend = Trend.empty()
        self._comparison = Comparison.empty()
        self._currency = ""
        self._loaded = False
        #: Which requests are currently failing, by name. The screen makes two
        #: independent requests, so "did anything fail" cannot be a single
        #: flag: without this, a trend that failed had its message wiped the
        #: moment the comparison succeeded.
        self._failures: dict[str, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("DashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # As needed, not never. A page wider than its viewport with the bar
        # switched off is content nobody can reach — the panel is simply cut
        # off at the edge with nothing to say so.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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

        layout.addWidget(self._build_trend_panel(), stretch=1)
        layout.addWidget(self._build_change_tiles())
        layout.addWidget(self._build_comparison_panel(), stretch=1)
        layout.addStretch(0)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("Analytics")
        title.setObjectName("SectionTitle")
        row.addWidget(title)

        self.period_label = QLabel("")
        self.period_label.setObjectName("SectionSubtitle")
        row.addWidget(self.period_label)

        row.addStretch(1)

        self.span_box = QComboBox()
        self.span_box.setObjectName("FieldSelect")
        self.span_box.setMinimumWidth(160)
        for label, months in SPANS:
            self.span_box.addItem(label, months)
        self.span_box.setCurrentIndex(1)  # six months
        # Only the trend depends on the span, so only the trend is refetched.
        self.span_box.currentIndexChanged.connect(self.reload_trend)
        row.addWidget(LabelledWidget("Span", self.span_box))

        return row

    def _build_trend_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DashboardPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        title = QLabel("Income and expense by month")
        title.setObjectName("PanelTitle")
        box.addWidget(title)

        self.trend_chart = TrendChart()
        self.trend_chart.setMinimumHeight(260)
        box.addWidget(self.trend_chart, stretch=1)

        return panel

    def _build_change_tiles(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("TileRow")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.income_tile = StatTile("Money in")
        self.expense_tile = StatTile("Money out")
        self.net_tile = StatTile("Kept")
        for tile in (self.income_tile, self.expense_tile, self.net_tile):
            row.addWidget(tile, stretch=1)

        return holder

    def _build_comparison_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DashboardPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        self.comparison_title = QLabel("What changed")
        self.comparison_title.setObjectName("PanelTitle")
        box.addWidget(self.comparison_title)

        self._rows_holder = QWidget()
        self._rows_holder.setObjectName("ChangeList")
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch(1)
        box.addWidget(self._rows_holder, stretch=1)

        self.comparison_empty = QLabel(NOTHING_TO_COMPARE)
        self.comparison_empty.setObjectName("EmptyMessage")
        self.comparison_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.comparison_empty.setWordWrap(True)
        box.addWidget(self.comparison_empty)

        return panel

    # ─── Loading ──────────────────────────────────────────────────────────

    def load_once(self, currency: str = "") -> None:
        """Set what belongs to the user. `reload` fetches the figures, and the
        shell calls it every time this section is shown."""
        self._currency = currency
        # The chart labels its own tooltips, and the currency is per user, so
        # it cannot be known until somebody is signed in.
        self.trend_chart.set_currency(currency)
        self._loaded = True

    def reload(self) -> None:
        """Both requests. They are independent and tracked separately (ADR-028),
        but a visit to this screen wants each of them current."""
        self.reload_trend()
        self.reload_comparison()

    def reset(self) -> None:
        """Forget this session's data. See `DashboardView.reset`."""
        self._loaded = False
        self._currency = ""
        self._trend = Trend.empty()
        self._comparison = Comparison.empty()
        self._failures.clear()
        self.banner.clear_message()
        self.trend_chart.set_months((), has_activity=False)
        self._render_rows(())

    def reload_trend(self) -> None:
        """Refetch only the trend. The comparison does not depend on the span."""
        try:
            self._trend = self._api.trend(months=self.span_box.currentData())
        except ApiError as exc:
            self._record_failure("trend", exc)
            # Not `set_months((), has_activity=False)`: that shows "No activity
            # in this span", which is a claim about the account rather than
            # about the connection.
            self.trend_chart.show_failure(exc.message)
            return

        self._record_success("trend")
        self.trend_chart.set_months(self._trend.months, has_activity=self._trend.has_activity)

    def reload_comparison(self) -> None:
        try:
            self._comparison = self._api.comparison()
        except ApiError as exc:
            self._record_failure("comparison", exc)
            # Not the "nothing to compare yet" line. The banner names the
            # failure, but the panel is where the user is looking, and leaving
            # it saying "nothing yet" reads as an empty account rather than an
            # unreachable one. Found by auditing the empty states rather than
            # by a test failing — which is what the audit was for.
            self._render_rows(())
            self.comparison_empty.setText(f"Could not load the comparison. {exc.message}")
            return

        self._record_success("comparison")
        self.comparison_empty.setText(NOTHING_TO_COMPARE)
        self._render_comparison()

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render_comparison(self) -> None:
        data = self._comparison
        self.period_label.setText(f"{data.period_start:%d %b} – {data.period_end:%d %b %Y}")
        self.comparison_title.setText(
            f"What changed since {data.previous_start:%d %b} – {data.previous_end:%d %b}"
        )

        # Spending more is bad, earning more is good — so the same arithmetic
        # gets the opposite tone depending on which figure it describes.
        self.income_tile.set_value(
            self._money(data.income.current),
            tone=self._tone(data.income, rise_is_good=True),
            detail=self._change_text(data.income),
        )
        self.expense_tile.set_value(
            self._money(data.expense.current),
            tone=self._tone(data.expense, rise_is_good=False),
            detail=self._change_text(data.expense),
        )
        self.net_tile.set_value(
            self._money(data.net.current),
            tone=self._tone(data.net, rise_is_good=True),
            detail=self._change_text(data.net),
        )

        self._render_rows(data.categories)

    @staticmethod
    def _tone(change: Change, *, rise_is_good: bool) -> str:
        if change.unchanged:
            return NEUTRAL
        good = change.rose if rise_is_good else change.fell
        return POSITIVE if good else NEGATIVE

    def _change_text(self, change: Change) -> str:
        """The movement in words, with the previous figure named.

        A percentage on its own hides the size of what moved; an amount on its
        own hides how big a shift it was. Both, or neither.
        """
        if change.is_new:
            return "new this period"
        if change.unchanged:
            return "no change"

        direction = "up" if change.rose else "down"
        size = self._money(abs(change.difference))
        if change.percentage is None:
            return f"{direction} {size}"
        return f"{direction} {size} ({percentage_text(abs(change.percentage))}%)"

    def _render_rows(self, categories: tuple[CategoryChange, ...]) -> None:
        for index in reversed(range(self._rows_layout.count())):
            widget = self._rows_layout.itemAt(index).widget()
            if widget is not None:
                self._rows_layout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

        shown = categories[:MAX_CATEGORY_ROWS]
        self.comparison_empty.setVisible(not shown)
        self._rows_holder.setVisible(bool(shown))

        for category in shown:
            self._rows_layout.insertWidget(
                self._rows_layout.count() - 1, self._change_row(category)
            )

    def _change_row(self, category: CategoryChange) -> QWidget:
        row = QWidget()
        row.setObjectName("ChangeRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(10)

        swatch = QLabel()
        swatch.setObjectName("CategorySwatch")
        swatch.setFixedSize(10, 10)
        if category.color:
            swatch.setStyleSheet(f"background-color: {category.color}; border-radius: 5px;")
        layout.addWidget(swatch)

        name = QLabel(category.name)
        name.setObjectName("ChangeName")
        layout.addWidget(name)

        layout.addStretch(1)

        was = QLabel(f"was {self._money(category.change.previous)}")
        was.setObjectName("ChangePrevious")
        layout.addWidget(was)

        now = QLabel(self._money(category.change.current))
        now.setObjectName("ChangeCurrent")
        layout.addWidget(now)

        movement = QLabel(self._movement_text(category.change))
        movement.setObjectName("ChangeMovement")
        # Spending is the subject here, so a rise is the unwelcome direction.
        movement.setProperty("tone", self._tone(category.change, rise_is_good=False))
        layout.addWidget(movement)

        return row

    def _movement_text(self, change: Change) -> str:
        if change.is_new:
            return "new"
        if change.unchanged:
            return "—"
        arrow = "▲" if change.rose else "▼"
        if change.percentage is None:
            return f"{arrow} {self._money(abs(change.difference))}"
        return f"{arrow} {percentage_text(abs(change.percentage))}%"

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()

    # ─── Failure ──────────────────────────────────────────────────────────

    def _record_failure(self, source: str, exc: ApiError) -> None:
        logger.warning("Analytics %s request failed: %s", source, exc.message)
        self._failures[source] = exc.message
        self._refresh_banner()

    def _record_success(self, source: str) -> None:
        self._failures.pop(source, None)
        self._refresh_banner()

    def _refresh_banner(self) -> None:
        """Show whatever is still failing, or nothing.

        Tracked per request rather than as one flag. The two requests are
        independent, and clearing the banner on any success would erase the
        other one's error — which is exactly what happened before a test
        caught it.
        """
        if not self._failures:
            self.banner.clear_message()
            return

        # Deduplicated: both requests failing for the same reason — the backend
        # being down — should say it once.
        messages = list(dict.fromkeys(self._failures.values()))
        self.banner.show_error(" · ".join(messages))
