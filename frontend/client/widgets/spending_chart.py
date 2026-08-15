"""Spending by category, as a ranked horizontal bar chart.

**Why not a donut.** The obvious choice for "spending by category" is a pie, and
it is the wrong one. The reader's job here is to compare magnitudes and find the
largest — and angles are much harder to compare than lengths, especially for the
close values that matter most ("is Food or Transport bigger this month?"). A pie
is defensible only for part-to-whole at a glance with a handful of segments; a
ranked bar answers the actual question directly. The percentage is printed
beside each bar, so the part-to-whole reading is not lost.

**Why one colour.** Colour here would encode identity, but identity is already
carried by the category name on the axis — so a second encoding adds nothing and
costs a great deal: nine categorical hues cannot be made distinguishable for
every pair at once, which was measured rather than assumed (ADR-026). Length
encodes magnitude; the axis labels encode identity; colour stays out of it.

Horizontal rather than vertical because category names are words, and words set
sideways under a vertical bar are unreadable.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalBarSeries,
    QValueAxis,
)
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QStackedWidget, QToolTip, QVBoxLayout, QWidget

from client.api.dto import CategoryShare
from client.core.formatting import percentage_text

#: The single hue every bar is drawn in — the interface's primary blue.
BAR_COLOUR = QColor("#1a56c4")
# The folded "Other categories" row needs no colour of its own: its label says
# what it is, and a second fill would imply it is a category like the others.

GRID_COLOUR = QColor("#eef0f3")
LABEL_COLOUR = QColor("#6b7480")

CHART_PAGE = 0
EMPTY_PAGE = 1


class SpendingChart(QStackedWidget):
    """A ranked bar chart of spending, or an empty state when there is none."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SpendingChart")

        self._currency = ""
        self._shares: tuple[CategoryShare, ...] = ()
        #: The shares in the order they are drawn — reversed, so the largest is
        #: at the top. A hover index refers to this, not to `_shares`.
        self._plotted: tuple[CategoryShare, ...] = ()

        self.chart = QChart()
        self.chart.legend().setVisible(False)  # one series; the title names it
        self.chart.setBackgroundVisible(False)
        self.chart.setPlotAreaBackgroundVisible(False)
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        self.chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

        # The axes are created once and reused, not rebuilt per render. See
        # `_rebuild` for why that matters.
        self._category_axis = QBarCategoryAxis()
        self._category_axis.setGridLineVisible(False)
        self._category_axis.setLineVisible(False)
        self._category_axis.setLabelsColor(LABEL_COLOUR)
        self._category_axis.setLabelsFont(QFont("", 9))
        self.chart.addAxis(self._category_axis, Qt.AlignmentFlag.AlignLeft)

        self._value_axis = QValueAxis()
        self._value_axis.setLabelFormat("%.0f")
        self._value_axis.setGridLineColor(GRID_COLOUR)
        self._value_axis.setLineVisible(False)
        self._value_axis.setLabelsColor(LABEL_COLOUR)
        self._value_axis.setLabelsFont(QFont("", 9))
        self._value_axis.setTickCount(5)
        self.chart.addAxis(self._value_axis, Qt.AlignmentFlag.AlignBottom)

        self.view = QChartView(self.chart)
        self.view.setObjectName("SpendingChartView")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.addWidget(self.view)

        self.addWidget(self._build_empty_state())

    def _build_empty_state(self) -> QWidget:
        """A chart with no data needs words, not an empty pair of axes."""
        panel = QWidget()
        panel.setObjectName("ChartEmptyState")
        box = QVBoxLayout(panel)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(6)

        self.empty_title = QLabel("Nothing spent yet")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel("Record an expense to see where the money goes.")
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_message)

        return panel

    # ─── Data ─────────────────────────────────────────────────────────────

    def set_currency(self, code: str) -> None:
        self._currency = code

    def set_shares(self, shares: tuple[CategoryShare, ...]) -> None:
        """Redraw for a new breakdown, or show the empty state."""
        self._shares = shares

        if not shares:
            # Cleared, not merely hidden. Switching to the empty page and
            # returning left the previous breakdown loaded underneath it —
            # bars, axis labels and the tooltips naming each category. Signing
            # out goes through here, so one person's categories and amounts
            # stayed in the widget while the next person used it.
            self._clear()
            self.setCurrentIndex(EMPTY_PAGE)
            return

        self.setCurrentIndex(CHART_PAGE)
        self._rebuild(shares)

    def _clear(self) -> None:
        """Drop the plotted data, leaving the axes in place to be reused."""
        self.chart.removeAllSeries()
        self._category_axis.clear()
        self._plotted = ()

    def _rebuild(self, shares: tuple[CategoryShare, ...]) -> None:
        """Redraw for a new breakdown.

        The series is replaced and the axes are *reused*. An earlier version
        removed and recreated the axes each time, which looks tidier and leaks:
        `removeAllSeries` deletes the series it owns, but `removeAxis` only
        hands ownership back, and an axis nobody then deletes stays alive and
        stays painted. Every redraw stacked another set of labels and ticks on
        the last — "Rent 60%" printed over "Shopping 50%" — and `deleteLater`
        does not help, because what lingers is the axis's graphics items rather
        than the axis object.

        It went unseen for eight phases because nothing ever redrew: each
        screen fetched once per run. The first thing that made the dashboard
        refresh made it visible.
        """
        self.chart.removeAllSeries()

        # A horizontal bar chart reads bottom-to-top, so the order is reversed
        # to put the largest at the top where the eye starts.
        ordered = list(reversed(shares))

        series = QHorizontalBarSeries()
        series.setBarWidth(0.55)  # thin marks, generous gaps
        series.setLabelsVisible(False)

        bars = QBarSet("")
        bars.setBorderColor(Qt.GlobalColor.transparent)
        for share in ordered:
            bars.append(float(share.total))
        bars.setColor(BAR_COLOUR)
        series.append(bars)
        # The axis label carries the name and the share; the exact amount is a
        # hover away. Printing it on every bar would crowd the one thing this
        # chart exists to make easy, which is comparing lengths.
        series.hovered.connect(self._on_hover)
        self.chart.addSeries(series)
        # Reversed for display (largest at the top), so the hover index has to
        # be mapped back to the original order rather than used directly.
        self._plotted = tuple(ordered)

        self._category_axis.clear()
        self._category_axis.append([self._axis_label(share) for share in ordered])
        series.attachAxis(self._category_axis)

        self._value_axis.setRange(0, self._axis_maximum(shares))
        # Rounds the range and ticks to readable numbers. Without it the axis
        # inherits the 10% headroom and reads 0, 4125, 8250 — arithmetically
        # correct and useless to a person.
        self._value_axis.applyNiceNumbers()
        series.attachAxis(self._value_axis)

    def _axis_label(self, share: CategoryShare) -> str:
        """Name plus share, so part-to-whole survives the move away from a pie."""
        return f"{share.name}  {percentage_text(share.percentage)}%"

    @staticmethod
    def _axis_maximum(shares: tuple[CategoryShare, ...]) -> float:
        """A little headroom above the largest bar, never a zero-width axis."""
        largest = max((share.total for share in shares), default=Decimal("0"))
        return float(largest) * 1.1 if largest > 0 else 1.0

    # ─── Hovering ─────────────────────────────────────────────────────────

    def _on_hover(self, entered: bool, index: int) -> None:
        if not entered:
            QToolTip.hideText()
            return
        QToolTip.showText(QCursor.pos(), self.tooltip_for(index))

    def tooltip_for(self, index: int) -> str:
        """The sentence a hovered bar shows.

        Indexed against the *plotted* order, which is reversed so the largest
        sits at the top. Reading `self._shares[index]` instead would name the
        wrong category on every bar but the middle one — the sort of mistake
        that looks right until somebody checks a number.
        """
        if not 0 <= index < len(self._plotted):
            return ""

        share = self._plotted[index]
        figure = f"{share.total:,.2f} {self._currency}".strip()
        return f"{share.name} · {figure} · {percentage_text(share.percentage)}% of spending"

    # ─── For tests ────────────────────────────────────────────────────────

    @property
    def bar_values(self) -> list[float]:
        """The plotted values, top row first. Empty when the chart is empty."""
        for series in self.chart.series():
            for bar_set in series.barSets():
                return [bar_set.at(i) for i in reversed(range(bar_set.count()))]
        return []

    @property
    def axis_labels(self) -> list[str]:
        """The category labels, top row first."""
        for axis in self.chart.axes():
            if isinstance(axis, QBarCategoryAxis):
                return list(reversed(axis.categories()))
        return []
