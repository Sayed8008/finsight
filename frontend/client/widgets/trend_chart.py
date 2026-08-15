"""Income against expense, month by month, as grouped bars.

**Why not green and red.** Every other screen shows income green and expense
red, and that convention is kept wherever an amount carries a sign — the sign
does the work and colour reinforces it. Here there is no sign: both series are
positive bar heights, so colour is the *only* thing separating them. Measured,
`#1a7f4b` and `#b4232c` are ΔE 4.5 apart under deuteranopia — the same colour to
roughly one man in twelve. Blue and orange are ΔE 29.7 apart under the same
simulation, so the chart uses those and the legend names them (ADR-027).

**Why grouped rather than stacked.** Stacking income on expense would imply
they add up to something. They do not; the interesting quantity is the gap
between them, and side-by-side bars show it directly.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from client.api.dto import MonthTotals

#: A colour-vision-safe pair, verified rather than assumed. Deliberately not
#: the green/red used for signed amounts — see the module docstring.
INCOME_COLOUR = QColor("#1a56c4")
EXPENSE_COLOUR = QColor("#d9782e")

GRID_COLOUR = QColor("#eef0f3")
LABEL_COLOUR = QColor("#6b7480")

CHART_PAGE = 0
EMPTY_PAGE = 1


class TrendChart(QStackedWidget):
    """Grouped monthly bars, or an empty state when there is no activity."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TrendChart")

        self.chart = QChart()
        self.chart.setBackgroundVisible(False)
        self.chart.setPlotAreaBackgroundVisible(False)
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        self.chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

        # Two series, so a legend is not optional: without it the colours mean
        # nothing, and colour would be the only thing telling them apart.
        legend = self.chart.legend()
        legend.setVisible(True)
        legend.setAlignment(Qt.AlignmentFlag.AlignBottom)
        legend.setLabelColor(LABEL_COLOUR)
        legend.setFont(QFont("", 9))
        legend.setBackgroundVisible(False)
        legend.setMarkerShape(legend.MarkerShape.MarkerShapeCircle)

        self.view = QChartView(self.chart)
        self.view.setObjectName("TrendChartView")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.addWidget(self.view)

        self.addWidget(self._build_empty_state())

    def _build_empty_state(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("ChartEmptyState")
        box = QVBoxLayout(panel)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(6)

        self.empty_title = QLabel("No activity in this span")
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel("Record some transactions to see the trend.")
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_message)

        return panel

    # ─── Data ─────────────────────────────────────────────────────────────

    def set_months(self, months: tuple[MonthTotals, ...], *, has_activity: bool = True) -> None:
        """Redraw for a span of months.

        An all-zero span shows the empty state rather than a row of flat bars:
        a chart of nothing is harder to read than a sentence saying so.
        """
        if not months or not has_activity:
            self.setCurrentIndex(EMPTY_PAGE)
            return

        self.setCurrentIndex(CHART_PAGE)
        self._rebuild(months)

    def _rebuild(self, months: tuple[MonthTotals, ...]) -> None:
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        income = QBarSet("Income")
        income.setColor(INCOME_COLOUR)
        income.setBorderColor(Qt.GlobalColor.transparent)

        expense = QBarSet("Expense")
        expense.setColor(EXPENSE_COLOUR)
        expense.setBorderColor(Qt.GlobalColor.transparent)

        for month in months:
            income.append(float(month.income))
            expense.append(float(month.expense))

        series = QBarSeries()
        series.setBarWidth(0.7)
        series.setLabelsVisible(False)
        series.append(income)
        series.append(expense)
        self.chart.addSeries(series)

        categories = QBarCategoryAxis()
        categories.append([self._month_label(month, months) for month in months])
        categories.setGridLineVisible(False)
        categories.setLineVisible(False)
        categories.setLabelsColor(LABEL_COLOUR)
        categories.setLabelsFont(QFont("", 9))
        self.chart.addAxis(categories, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(categories)

        values = QValueAxis()
        values.setRange(0, self._axis_maximum(months))
        values.setLabelFormat("%.0f")
        values.setGridLineColor(GRID_COLOUR)
        values.setLineVisible(False)
        values.setLabelsColor(LABEL_COLOUR)
        values.setLabelsFont(QFont("", 9))
        values.setTickCount(5)
        values.applyNiceNumbers()
        self.chart.addAxis(values, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(values)

    @staticmethod
    def _month_label(month: MonthTotals, months: tuple[MonthTotals, ...]) -> str:
        """ "Mar", or "Jan 26" where the year changes.

        Repeating the year on all twelve labels is noise; omitting it entirely
        makes a span crossing December ambiguous. It appears on the first label
        and wherever the year turns over.
        """
        turns_over = month is months[0] or month.month == 1
        return f"{month.first_day:%b %y}" if turns_over else f"{month.first_day:%b}"

    @staticmethod
    def _axis_maximum(months: tuple[MonthTotals, ...]) -> float:
        largest = max((max(month.income, month.expense) for month in months), default=Decimal("0"))
        return float(largest) * 1.1 if largest > 0 else 1.0

    # ─── For tests ────────────────────────────────────────────────────────

    @property
    def series_values(self) -> dict[str, list[float]]:
        """Each series by name, so a test can check the bars without pixels."""
        result: dict[str, list[float]] = {}
        for series in self.chart.series():
            for bar_set in series.barSets():
                result[bar_set.label()] = [bar_set.at(i) for i in range(bar_set.count())]
        return result

    @property
    def month_labels(self) -> list[str]:
        for axis in self.chart.axes():
            if isinstance(axis, QBarCategoryAxis):
                return list(axis.categories())
        return []
