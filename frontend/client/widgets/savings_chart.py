"""Net savings per completed month, as a line.

**Why a line and not bars.** The trend chart next to this one uses bars,
because it compares two independent quantities month by month and bar heights
are what the eye compares well. This chart shows one quantity moving through
time, and the question is the *shape* of it — is it climbing, did it dip in
March. A line encodes that continuity; twelve separate bars make the reader
reconstruct it.

**Zero is drawn, and the axis always includes it.** A deficit is a negative
number and the point of the chart is that it falls below the line rather than
simply being short. An axis fitted to the data alone would put a run of small
positive months near the bottom and make them look like losses.

The axes are created once and reused, and every redraw clears the series. See
`SpendingChart._rebuild` for what happens otherwise — recreated axes leak their
graphics items and stack each render's labels on the last.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCharts import (
    QCategoryAxis,
    QChart,
    QChartView,
    QLineSeries,
    QScatterSeries,
    QValueAxis,
)
from PySide6.QtCore import QMargins, QPointF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QStackedWidget, QToolTip, QVBoxLayout, QWidget

from client.api.dto import SavingsMonth
from client.core.animation import configure_chart

#: The line itself — the interface's primary blue, as used by every other
#: single-series chart here.
LINE_COLOUR = QColor("#1a56c4")
#: A month that lost money. The one place this chart uses a second colour,
#: because "below zero" is the distinction it exists to make.
DEFICIT_COLOUR = QColor("#b4232c")
ZERO_LINE_COLOUR = QColor("#c9cfd6")

GRID_COLOUR = QColor("#eef0f3")
LABEL_COLOUR = QColor("#6b7480")

CHART_PAGE = 0
EMPTY_PAGE = 1

NO_HISTORY_TITLE = "No completed months yet"
NO_HISTORY_MESSAGE = (
    "A month appears here once it has finished. Record income and spending and "
    "the journey starts next month."
)

#: Headroom above and below the plotted range, so the line never runs along the
#: frame. A share of the range rather than a fixed amount, because the amounts
#: here span from hundreds to hundreds of thousands.
HEADROOM = Decimal("0.15")


class SavingsChart(QStackedWidget):
    """A line of net savings per month, or words when there is no history."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SavingsChart")

        self._currency = ""
        #: The months currently plotted, so a hovered point can name itself.
        self._plotted: tuple[SavingsMonth, ...] = ()

        self.chart = QChart()
        self.chart.legend().setVisible(False)  # one series; the panel titles it
        self.chart.setBackgroundVisible(False)
        self.chart.setPlotAreaBackgroundVisible(False)
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        # The line draws itself, and re-draws when the range changes. Kept
        # to a single short animation on the series — the panel no longer
        # fades the chart as well, because two transitions over the same
        # pixels read as a stutter rather than as one movement.
        configure_chart(self.chart)

        # Created once and reused. A *category* axis, so each tick can be
        # named with its month: a value axis formats labels from the number,
        # which here is a position and would read 0, 1, 2.
        self._month_axis = QCategoryAxis()
        self._month_axis.setGridLineVisible(False)
        self._month_axis.setLineVisible(False)
        self._month_axis.setLabelsColor(LABEL_COLOUR)
        self._month_axis.setLabelsFont(QFont("", 9))
        # On the value, not at the end of its range — the label belongs under
        # the point it names, not between it and the next one.
        self._month_axis.setLabelsPosition(
            QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue
        )
        self.chart.addAxis(self._month_axis, Qt.AlignmentFlag.AlignBottom)

        self._value_axis = QValueAxis()
        self._value_axis.setLabelFormat("%.0f")
        self._value_axis.setGridLineColor(GRID_COLOUR)
        self._value_axis.setLineVisible(False)
        self._value_axis.setLabelsColor(LABEL_COLOUR)
        self._value_axis.setLabelsFont(QFont("", 9))
        self._value_axis.setTickCount(5)
        self.chart.addAxis(self._value_axis, Qt.AlignmentFlag.AlignLeft)

        self.view = QChartView(self.chart)
        self.view.setObjectName("SavingsChartView")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.addWidget(self.view)

        self.addWidget(self._build_empty_state())

    def _build_empty_state(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("ChartEmptyState")
        box = QVBoxLayout(panel)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(6)

        self.empty_title = QLabel(NO_HISTORY_TITLE)
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel(NO_HISTORY_MESSAGE)
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_message.setWordWrap(True)
        box.addWidget(self.empty_message)

        return panel

    # ─── Data ─────────────────────────────────────────────────────────────

    def set_currency(self, code: str) -> None:
        self._currency = code

    def set_months(self, months: tuple[SavingsMonth, ...]) -> None:
        """Redraw for a span of completed months, or show the empty state."""
        if not months:
            # Cleared, not merely hidden: switching to the empty page and
            # returning would leave the previous user's months loaded
            # underneath it, tooltips and all.
            self._clear()
            self.setCurrentIndex(EMPTY_PAGE)
            return

        self.setCurrentIndex(CHART_PAGE)
        self._rebuild(months)

    def show_failure(self, title: str, message: str) -> None:
        """Say the history could not be fetched, rather than that there is none."""
        self._clear()
        self.empty_title.setText(title)
        self.empty_message.setText(message)
        self.setCurrentIndex(EMPTY_PAGE)

    def _clear(self) -> None:
        """Drop the plotted data, leaving the axes in place to be reused."""
        self.chart.removeAllSeries()
        self._plotted = ()

    def _rebuild(self, months: tuple[SavingsMonth, ...]) -> None:
        """Redraw for a new span.

        `removeAllSeries` first, every time. Appending without it is what
        makes a chart accumulate: the old line stays, the new one is drawn
        over it, and switching a filter twice leaves three lines on screen.
        """
        self.chart.removeAllSeries()
        self._plotted = months

        line = QLineSeries()
        line.setPen(QPen(LINE_COLOUR, 2))
        for index, month in enumerate(months):
            line.append(float(index), float(month.net))

        # A single month is a point, not a line, and a line series alone would
        # draw nothing at all for it. The markers carry the values in every
        # case, so one month renders as one dot rather than an empty frame.
        markers = QScatterSeries()
        markers.setMarkerSize(9.0)
        markers.setColor(LINE_COLOUR)
        markers.setBorderColor(Qt.GlobalColor.white)
        for index, month in enumerate(months):
            markers.append(float(index), float(month.net))
        markers.hovered.connect(self._on_hover)

        deficits = QScatterSeries()
        deficits.setMarkerSize(9.0)
        deficits.setColor(DEFICIT_COLOUR)
        deficits.setBorderColor(Qt.GlobalColor.white)
        for index, month in enumerate(months):
            if not month.is_positive:
                deficits.append(float(index), float(month.net))
        deficits.hovered.connect(self._on_hover)

        for series in (line, markers, deficits):
            self.chart.addSeries(series)
            series.attachAxis(self._month_axis)
            series.attachAxis(self._value_axis)

        self._month_axis.setRange(-0.35, max(len(months) - 1, 0) + 0.35)
        self._apply_month_labels(months)

        low, high = self._value_range(months)
        self._value_axis.setRange(low, high)
        self._value_axis.applyNiceNumbers()

    def _apply_month_labels(self, months: tuple[SavingsMonth, ...]) -> None:
        """Name the ticks, thinned so they fit and never repeat.

        Two traps, both found by rendering rather than by reading:

        `QCategoryAxis` has no `clear()`. Labels have to be removed one at a
        time, and a redraw that skips this keeps every label the last one set
        — the axis of a 24-month span stays under a 3-month one.

        It also *silently ignores a label it already holds*, exactly as
        `QBarCategoryAxis` does. Twenty-four months repeat "Oct", so the
        repeats would vanish and the survivors would sit under the wrong
        points. Uniqueness therefore decides the format: short while it stays
        distinct, and the year on every label the moment it does not.
        """
        for label in list(self._month_axis.categoriesLabels()):
            self._month_axis.remove(label)

        shown = _label_positions(len(months))
        labels = [f"{months[i].first_day:%b}" for i in shown]
        if len(set(labels)) != len(labels):
            labels = [f"{months[i].first_day:%b %y}" for i in shown]

        for position, label in zip(shown, labels, strict=True):
            self._month_axis.append(label, position)

    @staticmethod
    def _value_range(months: tuple[SavingsMonth, ...]) -> tuple[float, float]:
        """The vertical range, always including zero.

        Zero is the line between saving and overspending, so a chart that
        omitted it would show a deficit as merely a low point.
        """
        values = [month.net for month in months]
        low = min(min(values), Decimal("0"))
        high = max(max(values), Decimal("0"))
        span = high - low
        if span == 0:
            # Every month identical, or a single month at zero. A range of no
            # height cannot be drawn, so one is invented around the value.
            padding = abs(high) * HEADROOM if high else Decimal("100")
            return float(low - padding), float(high + padding)
        padding = span * HEADROOM
        return float(low - padding), float(high + padding)

    # ─── Hovering ─────────────────────────────────────────────────────────

    def _on_hover(self, point: QPointF, state: bool) -> None:
        if not state:
            QToolTip.hideText()
            return
        QToolTip.showText(QCursor.pos(), self.tooltip_for(round(point.x())))

    def tooltip_for(self, index: int) -> str:
        """The sentence a hovered point shows.

        Indexed against the plotted order, which is chronological — the same
        order the points were appended in, so an index is a month.
        """
        if not 0 <= index < len(self._plotted):
            return ""

        month = self._plotted[index]
        figure = f"{month.net:,.2f} {self._currency}".strip()
        verb = "saved" if month.is_positive else "overspent by"
        amount = figure if month.is_positive else f"{-month.net:,.2f} {self._currency}".strip()
        return (
            f"{month.first_day:%B %Y} · {verb} {amount} · "
            f"{month.income:,.2f} in, {month.expense:,.2f} out"
        )

    # ─── For tests ────────────────────────────────────────────────────────

    @property
    def point_values(self) -> list[float]:
        """The plotted line, oldest first. Empty when the chart is empty."""
        for series in self.chart.series():
            if isinstance(series, QLineSeries) and not isinstance(series, QScatterSeries):
                return [series.at(i).y() for i in range(series.count())]
        return []

    @property
    def series_count(self) -> int:
        """How many series the chart holds — three when drawn, none when not.

        A test asserts on this because accumulation is the failure mode these
        charts have had twice: a redraw that appends without clearing leaves
        the old series behind, and nothing about the picture says so.
        """
        return len(self.chart.series())

    @property
    def axis_count(self) -> int:
        """How many axes the chart holds. Two, always — they are reused."""
        return len(self.chart.axes())

    @property
    def month_labels(self) -> list[str]:
        """The months currently plotted, as the tooltips name them."""
        return [f"{month.first_day:%b %y}" for month in self._plotted]


#: The most month labels the axis will carry. Beyond this they overlap and Qt
#: elides them, which names no month at all — the same failure the trend
#: chart's 24-month span had.
MAX_AXIS_LABELS = 8


def _label_positions(count: int) -> list[int]:
    """Which point indices get a label, always including the first and last.

    Thinned by a whole step rather than by dropping the middle, so the labels
    that remain are evenly spaced and the reader can count between them.
    """
    if count <= 0:
        return []
    if count <= MAX_AXIS_LABELS:
        return list(range(count))

    step = -(-count // MAX_AXIS_LABELS)  # ceiling division
    positions = list(range(0, count, step))
    if positions[-1] != count - 1:
        positions.append(count - 1)
    return positions
