"""The savings journey panel: what each completed month kept, and the trend.

Renders; it does not fetch. The range control is exposed so the screen that
owns it can refetch on change, exactly as the analytics span control works —
the alternative, a widget holding its own API client, would make it the only
one in the application that does.

**Nothing here computes money.** Every figure shown arrives from the server
already worked out, including the change and the rate. A panel that recomputed
"net" from income and expense would be the second calculation system the whole
feature was built to avoid, and it would be the one that drifts.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from client.api.dto import SavingsJourney, SavingsMonth
from client.core.animation import stagger_in
from client.core.formatting import percentage_text
from client.widgets.forms import LabelledWidget
from client.widgets.savings_chart import SavingsChart
from client.widgets.stat_tile import NEGATIVE, NEUTRAL, POSITIVE, StatTile

#: Asks the server for the whole history rather than a window of it. Matches
#: `savings_service.ALL_TIME`.
ALL_TIME = 0

#: The windows offered, in the order they are shown. The first four mirror the
#: analytics span control deliberately: the same words in the same order mean
#: a user does not have to learn a second control on the same screen.
RANGES: tuple[tuple[str, int], ...] = (
    ("Last 3 months", 3),
    ("Last 6 months", 6),
    ("Last 12 months", 12),
    ("Last 24 months", 24),
    ("All time", ALL_TIME),
)

DEFAULT_RANGE = 12

ZERO = Decimal("0")

#: What the panel says when the account has no completed month yet. Kept apart
#: from the failure wording: "you have no history" is a statement about the
#: account, and showing it when the request failed is a quiet lie.
NO_HISTORY = "No completed months yet — the journey starts once a month finishes."


class SavingsJourneyPanel(QFrame):
    """Summary tiles and a line of monthly savings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardPanel")

        self._currency = ""

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(14)

        box.addLayout(self._build_header())
        box.addWidget(self._build_tiles())

        self.chart = SavingsChart()
        self.chart.setMinimumHeight(220)
        box.addWidget(self.chart, stretch=1)

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("Savings journey")
        title.setObjectName("PanelTitle")
        row.addWidget(title)

        self.subtitle = QLabel("")
        self.subtitle.setObjectName("SectionSubtitle")
        row.addWidget(self.subtitle)

        row.addStretch(1)

        self.range_box = QComboBox()
        self.range_box.setObjectName("FieldSelect")
        self.range_box.setMinimumWidth(160)
        self.range_box.setCursor(Qt.CursorShape.PointingHandCursor)
        for label, months in RANGES:
            self.range_box.addItem(label, months)
        self.range_box.setCurrentIndex(self.range_box.findData(DEFAULT_RANGE))
        row.addWidget(LabelledWidget("Range", self.range_box))

        return row

    def _build_tiles(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("TileRow")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.saved_tile = StatTile("Saved that month")
        self.change_tile = StatTile("Change from the month before")
        self.rate_tile = StatTile("Savings rate")
        self.best_tile = StatTile("Personal best")
        for tile in (self.saved_tile, self.change_tile, self.rate_tile, self.best_tile):
            row.addWidget(tile, stretch=1)

        return holder

    # ─── Data ─────────────────────────────────────────────────────────────

    @property
    def selected_range(self) -> int:
        """Months requested, or `ALL_TIME` for the whole history."""
        return int(self.range_box.currentData())

    def set_currency(self, code: str) -> None:
        self._currency = code
        self.chart.set_currency(code)

    def set_journey(self, journey: SavingsJourney) -> None:
        """Render a fetched journey.

        The chart is not faded here: it animates its own line through QtCharts
        (see `configure_chart`), and a fade over the top of that would be two
        transitions across the same pixels, which reads as a stutter rather
        than as one movement. The badges are the part that fades, because they
        genuinely appear rather than change.
        """
        self.chart.set_months(journey.months)
        self._render_tiles(journey)
        self._render_subtitle(journey)
        stagger_in([self.saved_tile, self.change_tile, self.rate_tile, self.best_tile])

    def show_failure(self, message: str) -> None:
        """Say it could not be fetched, rather than that there is none."""
        self.chart.show_failure("Could not load your savings history", message)
        self._render_tiles(SavingsJourney.empty())
        self.subtitle.setText("")

    def reset(self) -> None:
        """Forget this session's data. See `DashboardView.reset`."""
        self._currency = ""
        self.chart.set_currency("")
        self.chart.set_months(())
        self.range_box.blockSignals(True)
        self.range_box.setCurrentIndex(self.range_box.findData(DEFAULT_RANGE))
        self.range_box.blockSignals(False)
        self.set_journey(SavingsJourney.empty())

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render_subtitle(self, journey: SavingsJourney) -> None:
        if not journey.has_history:
            self.subtitle.setText(NO_HISTORY)
            return
        latest = journey.summary.latest
        count = len(journey.months)
        shown = f"{count} completed month{'s' if count != 1 else ''}"
        self.subtitle.setText(
            f"{shown} · most recent {latest.first_day:%B %Y}" if latest else shown
        )

    def _render_tiles(self, journey: SavingsJourney) -> None:
        summary = journey.summary
        latest = summary.latest

        if latest is None:
            for tile in (self.saved_tile, self.change_tile, self.rate_tile, self.best_tile):
                tile.set_value("—")
            return

        self.saved_tile.set_value(
            self._money(latest.net),
            tone=POSITIVE if latest.is_positive else NEGATIVE,
            detail=f"{latest.first_day:%B %Y}"
            + ("" if latest.is_positive else " — spent more than it earned"),
        )

        if summary.previous is None:
            self.change_tile.set_value("—", detail="No earlier month to compare with yet.")
        else:
            rose = summary.change > ZERO
            arrow = "▲" if rose else "▼" if summary.change < ZERO else "—"
            share = (
                f" ({percentage_text(abs(summary.change_percentage))}%)"
                if summary.change_percentage is not None
                else ""
            )
            self.change_tile.set_value(
                f"{arrow} {self._money(abs(summary.change))}{share}",
                tone=POSITIVE if rose else NEGATIVE if summary.change < ZERO else NEUTRAL,
                detail=f"against {summary.previous.first_day:%B %Y}",
            )

        self.rate_tile.set_value(
            f"{percentage_text(latest.rate)}%",
            tone=POSITIVE if latest.is_positive else NEGATIVE,
            detail=(
                "of what came in"
                if latest.income > ZERO
                else "no income recorded that month"
            ),
        )

        best = summary.best
        if best is None:
            self.best_tile.set_value("—", detail="No month has saved anything yet.")
        else:
            self.best_tile.set_value(
                self._money(best.net),
                tone=POSITIVE,
                detail=(
                    f"{best.first_day:%B %Y}"
                    + (" — this month" if summary.is_personal_best else "")
                ),
            )

    # ─── Formatting ───────────────────────────────────────────────────────

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()

    # ─── For tests ────────────────────────────────────────────────────────

    @staticmethod
    def month_label(month: SavingsMonth) -> str:
        return f"{month.first_day:%B %Y}"
