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
from PySide6.QtGui import QColor, QCursor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QStackedWidget, QToolTip, QVBoxLayout, QWidget

from client.api.dto import MonthTotals
from client.core.animation import configure_chart

#: A colour-vision-safe pair, verified rather than assumed. Deliberately not
#: the green/red used for signed amounts — see the module docstring.
INCOME_COLOUR = QColor("#1a56c4")
EXPENSE_COLOUR = QColor("#d9782e")

GRID_COLOUR = QColor("#eef0f3")
LABEL_COLOUR = QColor("#6b7480")

CHART_PAGE = 0
EMPTY_PAGE = 1

#: The empty state when the account genuinely has nothing in this span. Kept
#: apart from the failure wording: "no activity" is a statement about the
#: account, and showing it when the request failed is a false one.
NO_ACTIVITY_TITLE = "No activity in this span"
NO_ACTIVITY_MESSAGE = "Record some transactions to see the trend."


class TrendChart(QStackedWidget):
    """Grouped monthly bars, or an empty state when there is no activity."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TrendChart")

        #: The months currently plotted, kept so a hovered bar can name itself.
        self._months: tuple[MonthTotals, ...] = ()
        self._currency = ""

        self.chart = QChart()
        self.chart.setBackgroundVisible(False)
        self.chart.setPlotAreaBackgroundVisible(False)
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        # Grouped bars grow into place on first draw and on every span
        # change. See `configure_chart` for why the animation is Qt's own.
        configure_chart(self.chart)

        # Two series, so a legend is not optional: without it the colours mean
        # nothing, and colour would be the only thing telling them apart.
        legend = self.chart.legend()
        legend.setVisible(True)
        legend.setAlignment(Qt.AlignmentFlag.AlignBottom)
        legend.setLabelColor(LABEL_COLOUR)
        legend.setFont(QFont("", 9))
        legend.setBackgroundVisible(False)
        legend.setMarkerShape(legend.MarkerShape.MarkerShapeCircle)

        # Created once and reused — see `_rebuild` for why.
        self._category_axis = QBarCategoryAxis()
        self._category_axis.setGridLineVisible(False)
        self._category_axis.setLineVisible(False)
        self._category_axis.setLabelsColor(LABEL_COLOUR)
        self._category_axis.setLabelsFont(QFont("", 9))
        self.chart.addAxis(self._category_axis, Qt.AlignmentFlag.AlignBottom)

        self._value_axis = QValueAxis()
        self._value_axis.setLabelFormat("%.0f")
        self._value_axis.setGridLineColor(GRID_COLOUR)
        self._value_axis.setLineVisible(False)
        self._value_axis.setLabelsColor(LABEL_COLOUR)
        self._value_axis.setLabelsFont(QFont("", 9))
        self._value_axis.setTickCount(5)
        self.chart.addAxis(self._value_axis, Qt.AlignmentFlag.AlignLeft)

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

        self.empty_title = QLabel(NO_ACTIVITY_TITLE)
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.empty_title)

        self.empty_message = QLabel(NO_ACTIVITY_MESSAGE)
        self.empty_message.setObjectName("EmptyMessage")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_message.setWordWrap(True)
        box.addWidget(self.empty_message)

        return panel

    # ─── Data ─────────────────────────────────────────────────────────────

    def set_months(self, months: tuple[MonthTotals, ...], *, has_activity: bool = True) -> None:
        """Redraw for a span of months.

        An all-zero span shows the empty state rather than a row of flat bars:
        a chart of nothing is harder to read than a sentence saying so.
        """
        if not months or not has_activity:
            self._show_empty(NO_ACTIVITY_TITLE, NO_ACTIVITY_MESSAGE)
            return

        self._months = months
        self.setCurrentIndex(CHART_PAGE)
        self._rebuild(months)

    def show_failure(self, message: str) -> None:
        """Say the trend could not be fetched, rather than that there is none.

        "No activity in this span" is a statement about the account. When the
        request failed, it is a false one — and it is the sentence the user is
        actually reading, since the banner is elsewhere on the screen.
        """
        self._months = ()
        self._show_empty("Could not load the trend", message)

    def _show_empty(self, title: str, message: str) -> None:
        self.empty_title.setText(title)
        self.empty_message.setText(message)
        self.setCurrentIndex(EMPTY_PAGE)

    def _rebuild(self, months: tuple[MonthTotals, ...]) -> None:
        """Redraw for a span of months, reusing the axes.

        Recreating them each time leaks their graphics items and stacks each
        render's labels on the last. See `SpendingChart._rebuild`, where the
        same mistake was found first.
        """
        self.chart.removeAllSeries()

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
        # Printing a figure on every bar would make twelve months unreadable;
        # a tooltip puts the exact number one hover away and leaves the chart
        # to do what it is for, which is comparing heights.
        series.hovered.connect(self._on_hover)
        self.chart.addSeries(series)

        labels = self._axis_labels(months)
        self._category_axis.clear()
        self._category_axis.append(labels)
        # Twenty-four "Sep 24"s do not fit across the panel, and Qt's answer to
        # a label that does not fit is to elide it — a row reading "S… O… N…"
        # names no month at all. Turned on their side they fit, so the long
        # form is rotated and the short one left flat.
        self._category_axis.setLabelsAngle(-90 if self._is_long_form(labels) else 0)
        series.attachAxis(self._category_axis)

        self._value_axis.setRange(0, self._axis_maximum(months))
        self._value_axis.applyNiceNumbers()
        series.attachAxis(self._value_axis)

    @classmethod
    def _axis_labels(cls, months: tuple[MonthTotals, ...]) -> list[str]:
        """One label per month, and every one of them distinct.

        `QBarCategoryAxis` treats its categories as a *set of names*: appending
        a label it already holds is silently ignored. So a span long enough to
        repeat a month name loses a category per repeat, and every bar after
        the first duplicate sits under the wrong label.

        Reported for the 24-month span, where it is worst: twenty-four bars
        kept only fourteen labels — "Sep 25" was followed by "Jan 26" — and the
        chart quietly misattributed a year and a half of history. Twelve months
        and under were unaffected, which is why it was not seen sooner.

        So uniqueness decides the format rather than taste: the short form is
        used while it stays unambiguous, and the year goes on every label the
        moment it does not.
        """
        short = [cls._month_label(month, months) for month in months]
        if len(set(short)) == len(short):
            return short
        return [f"{month.first_day:%b %y}" for month in months]

    @staticmethod
    def _is_long_form(labels: list[str]) -> bool:
        """Whether every label carries a year, and so needs the room."""
        return len(labels) > 1 and all(" " in label for label in labels)

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

    # ─── Hovering ─────────────────────────────────────────────────────────

    def set_currency(self, currency: str) -> None:
        """What to label a tooltip's amount with. Per user, so it arrives late."""
        self._currency = currency

    def _on_hover(self, entered: bool, index: int, bar_set: QBarSet) -> None:
        if not entered:
            QToolTip.hideText()
            return
        QToolTip.showText(QCursor.pos(), self.tooltip_for(index, bar_set.label()))

    def tooltip_for(self, index: int, series_name: str) -> str:
        """The sentence a hovered bar shows.

        Built separately from the hover handler so a test can read it without
        synthesising mouse movement over a chart — the wording is the part
        worth checking, and the part that can be wrong.
        """
        if not 0 <= index < len(self._months):
            return ""

        month = self._months[index]
        amount = month.income if series_name == "Income" else month.expense
        figure = f"{amount:,.2f} {self._currency}".strip()
        return f"{month.first_day:%B %Y} · {series_name.lower()} {figure}"

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
    def labels_angle(self) -> float:
        """The rotation applied to the month labels."""
        for axis in self.chart.axes():
            if isinstance(axis, QBarCategoryAxis):
                return axis.labelsAngle()
        return 0

    @property
    def month_labels(self) -> list[str]:
        for axis in self.chart.axes():
            if isinstance(axis, QBarCategoryAxis):
                return list(axis.categories())
        return []
