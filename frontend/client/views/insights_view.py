"""The insights screen: what is worth knowing, and why.

Every row is one finding with its own explanation. The explanation is not
supporting detail — it is the point. "Unusual spending detected" tells nobody
anything; "Food is 2,000.00 over a 10,000.00 budget with 16 days left" can be
acted on.

Nothing on this screen is decided here. Severity, ordering and wording all
arrive from the server, so there is exactly one place that defines what
"critical" means (ADR-008).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiClient, ApiError
from client.api.dto import CRITICAL, GOOD, INFO, SEVERITY_WARNING, Insight, Insights
from client.widgets.forms import LabelledWidget, MessageBanner

logger = logging.getLogger(__name__)

LIST_PAGE = 0
EMPTY_PAGE = 1

#: The word shown on each row's badge. The severity itself is never displayed
#: raw — "good" as a label would read as a rating rather than a category.
SEVERITY_LABELS = {
    CRITICAL: "Needs action",
    SEVERITY_WARNING: "Worth a look",
    INFO: "For information",
    GOOD: "Good news",
}

FILTERS: tuple[tuple[str, str | None], ...] = (
    ("Everything", None),
    ("Needs attention", "attention"),
    ("Good news", GOOD),
)


class InsightsView(QWidget):
    """A list of findings, most urgent first."""

    #: Opening the thing an insight is about. The screen points; it does not
    #: reproduce the budgets or subscriptions screens.
    navigate_requested = Signal(str)

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InsightsView")
        self._api = api_client

        self._insights = Insights.empty()
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

        self._pages = QVBoxLayout()
        layout.addLayout(self._pages)

        self._list_holder = QWidget()
        self._list_holder.setObjectName("InsightList")
        self._list_layout = QVBoxLayout(self._list_holder)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)
        layout.addWidget(self._list_holder, stretch=1)

        layout.addWidget(self._build_empty_state())
        layout.addStretch(0)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("Insights")
        title.setObjectName("SectionTitle")
        row.addWidget(title)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("SectionSubtitle")
        row.addWidget(self.summary_label)

        row.addStretch(1)

        self.filter_box = QComboBox()
        self.filter_box.setObjectName("FieldSelect")
        self.filter_box.setMinimumWidth(170)
        for label, value in FILTERS:
            self.filter_box.addItem(label, value)
        # Filtering is local: everything is already here, and a round trip to
        # hide four rows would be waste.
        self.filter_box.currentIndexChanged.connect(self._render)
        row.addWidget(LabelledWidget("Show", self.filter_box))

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("SecondaryButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.reload)
        row.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignBottom)

        return row

    def _build_empty_state(self) -> QWidget:
        self.empty_panel = QWidget()
        self.empty_panel.setObjectName("EmptyState")
        box = QVBoxLayout(self.empty_panel)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(8)
        self.empty_panel.setMinimumHeight(180)

        self.empty_title = QLabel("Nothing needs your attention")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel("Budgets are on track and nothing is overdue.")
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_message)

        return self.empty_panel

    # ─── Loading ──────────────────────────────────────────────────────────

    def load_once(self, currency: str = "") -> None:
        """Insights are recomputed on every request and can never be stale on
        the server; the client must not make them stale by caching them, so
        the shell calls `reload` every time this section is shown."""
        self._currency = currency
        self._loaded = True

    def reset(self) -> None:
        """Forget this session's data. See `DashboardView.reset`."""
        self._loaded = False
        self._currency = ""
        self._insights = Insights.empty()
        self.banner.clear_message()
        self._render()

    def reload(self) -> None:
        try:
            self._insights = self._api.insights()
        except ApiError as exc:
            self._show_error(exc)
            return

        self.banner.clear_message()
        self._render()

    # ─── Rendering ────────────────────────────────────────────────────────

    def visible_insights(self) -> tuple[Insight, ...]:
        """The findings the current filter admits."""
        chosen = self.filter_box.currentData()
        if chosen is None:
            return self._insights.items
        if chosen == "attention":
            return tuple(item for item in self._insights.items if item.is_bad_news)
        return tuple(item for item in self._insights.items if item.severity == chosen)

    def _render(self) -> None:
        self._clear_rows()
        visible = self.visible_insights()

        for insight in visible:
            self._list_layout.insertWidget(self._list_layout.count() - 1, self._row(insight))

        self._list_holder.setVisible(bool(visible))
        self.empty_panel.setVisible(not visible)
        if not visible:
            self._describe_empty_state()

        self.summary_label.setText(self._summary_text())

    def _summary_text(self) -> str:
        """A count that says something, or nothing at all.

        "0 insights" is worse than silence: it reads as a failure rather than
        as an account in good order.
        """
        needs = self._insights.needs_attention
        total = len(self._insights.items)
        if not total:
            return ""
        if not needs:
            return f"{total} to read · nothing needs action"
        return f"{needs} of {total} need attention"

    def _clear_rows(self) -> None:
        for index in reversed(range(self._list_layout.count())):
            widget = self._list_layout.itemAt(index).widget()
            if widget is not None:
                self._list_layout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

    def _row(self, insight: Insight) -> QWidget:
        card = QFrame()
        card.setObjectName("InsightCard")
        card.setProperty("severity", insight.severity)

        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel(insight.title)
        title.setObjectName("InsightTitle")
        header.addWidget(title)

        badge = QLabel(SEVERITY_LABELS.get(insight.severity, insight.severity.title()))
        badge.setObjectName("InsightBadge")
        badge.setProperty("severity", insight.severity)
        header.addWidget(badge)

        header.addStretch(1)

        target = self._target_for(insight)
        if target is not None:
            link = QPushButton(f"Open {target}")
            link.setObjectName("LinkButton")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(lambda _=False, key=target: self.navigate_requested.emit(key))
            header.addWidget(link)

        box.addLayout(header)

        detail = QLabel(insight.detail)
        detail.setObjectName("InsightDetail")
        detail.setWordWrap(True)
        box.addWidget(detail)

        return card

    @staticmethod
    def _target_for(insight: Insight) -> str | None:
        """Which screen this finding is about, if any.

        Derived from what the insight is attached to rather than from its code,
        so a new rule about a budget gets its link without this needing to
        learn the rule's name.
        """
        if insight.subscription_id is not None:
            return "subscriptions"
        if insight.category_id is not None:
            return "budgets"
        return None

    def _describe_empty_state(self) -> None:
        if self._insights.items:
            self.empty_title.setText("Nothing matches that filter")
            self.empty_message.setText("There are other insights — try showing everything.")
        else:
            self.empty_title.setText("Nothing needs your attention")
            self.empty_message.setText("Budgets are on track and nothing is overdue.")

    # ─── Failure ──────────────────────────────────────────────────────────

    def _show_error(self, exc: ApiError) -> None:
        logger.warning("Insights request failed: %s", exc.message)
        self.banner.show_error(exc.message)
        self._insights = Insights.empty()
        self._clear_rows()
        self._list_holder.setVisible(False)
        self.empty_panel.setVisible(True)
        self.empty_title.setText("Could not load insights")
        self.empty_message.setText(exc.message)
        self.summary_label.setText("")
