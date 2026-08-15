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

from client.api.dto import SavingsBadge, SavingsJourney, SavingsMonth
from client.core.animation import FAST_MS, fade_in, stagger_in
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
    """Summary tiles, a line of monthly savings, badges and observations."""

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

        self._badge_row = QWidget()
        self._badge_row.setObjectName("BadgeRow")
        self._badge_layout = QHBoxLayout(self._badge_row)
        self._badge_layout.setContentsMargins(0, 0, 0, 0)
        self._badge_layout.setSpacing(8)
        self._badge_layout.addStretch(1)
        box.addWidget(self._badge_row)

        # What each badge was awarded for, in the order the pills appear.
        #
        # The detail used to live only in a tooltip, which made a row of
        # coloured words look like decoration — the exact thing
        # `savings_rules` says a badge must not be. Hover is also no way to
        # read four sentences, and there is no keyboard path to a tooltip at
        # all. So the reason is on the screen, and the tooltip stays as well
        # for anyone who hovers one pill in particular.
        self._badge_details = QLabel("")
        self._badge_details.setObjectName("SavingsBadgeDetails")
        self._badge_details.setWordWrap(True)
        self._badge_details.setVisible(False)
        box.addWidget(self._badge_details)

        self._observations = QLabel("")
        self._observations.setObjectName("SavingsObservations")
        self._observations.setWordWrap(True)
        self._observations.setVisible(False)
        box.addWidget(self._observations)

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
        self._render_badges(journey.badges)
        self._render_observations(journey.observations)
        self._render_subtitle(journey)
        stagger_in([self.saved_tile, self.change_tile, self.rate_tile, self.best_tile])

    def show_failure(self, message: str) -> None:
        """Say it could not be fetched, rather than that there is none."""
        self.chart.show_failure("Could not load your savings history", message)
        self._render_tiles(SavingsJourney.empty())
        self._render_badges(())
        self._render_observations(())
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

    def _render_badges(self, badges: tuple[SavingsBadge, ...]) -> None:
        """Rebuild the row, clearing it first.

        Every badge widget is removed and deleted rather than hidden. Leaving
        them would stack one render's awards on the next — the same fault the
        charts had, in a layout instead of a scene.
        """
        while self._badge_layout.count():
            item = self._badge_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Unparented *now*, then deleted when Qt gets round to it.
                # `deleteLater` alone is deferred to the next event loop turn,
                # so two renders in quick succession — which is exactly what
                # switching a filter twice does — would leave the first
                # render's chips still parented, still found, and still drawn.
                widget.setParent(None)
                widget.deleteLater()

        for badge in badges:
            chip = QLabel(badge.title)
            chip.setObjectName("SavingsBadge")
            chip.setProperty("badge", badge.code)
            chip.setToolTip(badge.detail)
            self._badge_layout.addWidget(chip)
            fade_in(chip, FAST_MS)

        self._badge_layout.addStretch(1)
        self._badge_row.setVisible(bool(badges))

        # Titled, so a sentence can be matched to the pill it belongs to. A
        # colon rather than a dash: several of the details contain an em dash
        # already, and two in one clause reads as a stutter.
        self._badge_details.setText(
            " · ".join(f"{badge.title}: {badge.detail}" for badge in badges)
        )
        self._badge_details.setVisible(bool(badges))

    def _render_observations(self, observations: tuple[str, ...]) -> None:
        self._observations.setText(" · ".join(observations))
        self._observations.setVisible(bool(observations))

    # ─── Formatting ───────────────────────────────────────────────────────

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()

    # ─── For tests ────────────────────────────────────────────────────────

    @property
    def badge_titles(self) -> list[str]:
        """The awards currently on screen, in order.

        Read from the live widgets rather than from the last payload, because
        the fault worth catching is a badge row that kept a previous render's
        chips — which a stored list would not show.
        """
        return [label.text() for label in self._badge_row.findChildren(QLabel, "SavingsBadge")]

    @property
    def badge_details_text(self) -> str:
        """What is actually on screen explaining the badges.

        Read from the label rather than the payload: the fault this exists to
        prevent is a badge whose reason is present in the data but invisible
        to the reader.
        """
        return self._badge_details.text()

    @property
    def observations_text(self) -> str:
        return self._observations.text()

    @staticmethod
    def month_label(month: SavingsMonth) -> str:
        return f"{month.first_day:%B %Y}"
