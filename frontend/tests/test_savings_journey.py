"""Tests for the savings journey panel and its line chart.

The failure mode these mostly defend against is accumulation. Both existing
charts in this application have shipped a version that appended without
clearing — one stacked axis labels, the other left a previous user's data
loaded under an empty state — and neither looked wrong in a single render.
So the chart tests here switch ranges repeatedly and count what is left.

Nothing here recomputes savings. The panel is given a journey and asked what
it displays; a test that worked out the net itself would be checking its own
arithmetic rather than the widget's rendering.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from client.api.client import ApiError
from client.api.dto import SavingsBadge, SavingsJourney, SavingsMonth, SavingsSummary
from client.views.analytics_view import AnalyticsView
from client.widgets.savings_chart import CHART_PAGE, EMPTY_PAGE, SavingsChart
from client.widgets.savings_journey import ALL_TIME, RANGES, SavingsJourneyPanel

pytestmark = pytest.mark.gui


def month(year: int, number: int, net: str, income: str = "50000.00") -> SavingsMonth:
    money_in = Decimal(income)
    saved = Decimal(net)
    rate = (saved / money_in * 100).quantize(Decimal("0.01")) if money_in else Decimal("0.00")
    return SavingsMonth(
        year=year,
        month=number,
        first_day=date(year, number, 1),
        income=money_in,
        expense=money_in - saved,
        net=saved,
        rate=rate,
    )


def span(count: int, *, end_year: int = 2026, end_month: int = 7) -> tuple[SavingsMonth, ...]:
    """`count` consecutive months ending at the given one, oldest first.

    Each month saves 500 more than the one before, so the latest is always the
    personal best and the order is visible in the values themselves — a test
    that got the direction wrong would fail rather than quietly pass.
    """
    dates: list[tuple[int, int]] = []
    year, number = end_year, end_month
    for _ in range(count):
        dates.append((year, number))
        number -= 1
        if number == 0:
            year, number = year - 1, 12
    dates.reverse()
    return tuple(
        month(year, number, str(5000 + step * 500))
        for step, (year, number) in enumerate(dates)
    )


def journey(
    months: tuple[SavingsMonth, ...] = (),
    badges: tuple[SavingsBadge, ...] = (),
    observations: tuple[str, ...] = (),
) -> SavingsJourney:
    if not months:
        return SavingsJourney.empty()
    latest = months[-1]
    previous = months[-2] if len(months) > 1 else None
    best = max(months, key=lambda item: item.net)
    return SavingsJourney(
        months=months,
        summary=SavingsSummary(
            latest=latest,
            previous=previous,
            best=best,
            change=latest.net - (previous.net if previous else Decimal("0.00")),
            change_percentage=None,
            is_personal_best=best is latest,
        ),
        badges=badges,
        observations=observations,
        has_history=True,
    )


# ─── The chart ────────────────────────────────────────────────────────────


def test_the_chart_plots_one_point_per_month(qtbot) -> None:
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months(span(6))

    assert len(chart.point_values) == 6


def test_the_chart_keeps_months_in_order(qtbot) -> None:
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months(span(4))

    assert chart.point_values == sorted(chart.point_values)


def test_a_deficit_is_plotted_below_zero(qtbot) -> None:
    """Negative savings are negative. Plotting the magnitude would show a bad
    month as a good one."""
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months((month(2026, 6, "-5000.00"), month(2026, 7, "14000.00")))

    assert chart.point_values == [-5000.0, 14000.0]


def test_one_month_renders_rather_than_showing_an_empty_frame(qtbot) -> None:
    """A line through one point draws nothing, so the markers carry it."""
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months((month(2026, 7, "14000.00"),))

    assert chart.currentIndex() == CHART_PAGE
    assert chart.point_values == [14000.0]


def test_no_history_shows_the_empty_state(qtbot) -> None:
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months(())

    assert chart.currentIndex() == EMPTY_PAGE
    assert chart.point_values == []


def test_emptying_the_chart_keeps_none_of_the_last_render(qtbot) -> None:
    """Signing out empties it, and the next person must not inherit it."""
    chart = SavingsChart()
    qtbot.addWidget(chart)
    chart.set_months(span(6))

    chart.set_months(())

    assert chart.point_values == []
    assert chart.tooltip_for(0) == ""
    assert chart.series_count == 0


@pytest.mark.parametrize("count", [1, 2, 3, 6, 12, 24])
def test_the_chart_holds_the_same_series_and_axes_whatever_the_span(
    qtbot, count: int
) -> None:
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months(span(count))

    assert chart.series_count == 3
    assert chart.axis_count == 2


def test_switching_ranges_repeatedly_never_accumulates(qtbot) -> None:
    """The fault both other charts have shipped: a redraw that appends without
    clearing leaves the old data behind, and the picture does not say so."""
    chart = SavingsChart()
    qtbot.addWidget(chart)

    for count in (12, 3, 24, 6, 24, 3, 12, 1, 24):
        chart.set_months(span(count))

    assert chart.series_count == 3
    assert chart.axis_count == 2
    assert len(chart.point_values) == 24


def test_a_redrawn_chart_shows_only_the_current_months(qtbot) -> None:
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months(span(12))
    chart.set_months(span(3))

    assert len(chart.point_values) == 3


def test_a_tooltip_names_the_month_and_what_it_saved(qtbot) -> None:
    chart = SavingsChart()
    qtbot.addWidget(chart)
    chart.set_currency("BDT")

    chart.set_months((month(2026, 7, "14000.00"),))

    assert "July 2026" in chart.tooltip_for(0)
    assert "saved 14,000.00 BDT" in chart.tooltip_for(0)


def test_a_tooltip_says_overspent_rather_than_saved_minus(qtbot) -> None:
    chart = SavingsChart()
    qtbot.addWidget(chart)
    chart.set_currency("BDT")

    chart.set_months((month(2026, 6, "-5000.00"),))

    assert "overspent by 5,000.00 BDT" in chart.tooltip_for(0)


def test_a_tooltip_for_a_point_that_is_not_there_is_empty(qtbot) -> None:
    """Qt can emit a hover for an index outside the current data mid-redraw."""
    chart = SavingsChart()
    qtbot.addWidget(chart)
    chart.set_months(span(3))

    assert chart.tooltip_for(9) == ""
    assert chart.tooltip_for(-1) == ""


def test_a_flat_history_does_not_collapse_the_axis(qtbot) -> None:
    """Every month identical gives a range of no height, which cannot be drawn."""
    chart = SavingsChart()
    qtbot.addWidget(chart)

    chart.set_months((month(2026, 6, "0.00"), month(2026, 7, "0.00")))

    assert chart.point_values == [0.0, 0.0]


def test_the_month_labels_are_unique_and_do_not_accumulate(qtbot) -> None:
    """`QCategoryAxis` has no `clear()` and silently ignores a label it already
    holds — the same trap the trend chart's axis had."""
    from PySide6.QtCharts import QCategoryAxis

    chart = SavingsChart()
    qtbot.addWidget(chart)

    def labels() -> list[str]:
        for axis in chart.chart.axes():
            if isinstance(axis, QCategoryAxis):
                return list(axis.categoriesLabels())
        return []

    for count in (24, 3, 24, 6, 24):
        chart.set_months(span(count))
        current = labels()
        assert len(current) == len(set(current)), current
        assert current, "the axis lost every label"


# ─── The panel ────────────────────────────────────────────────────────────


@pytest.fixture
def panel(qtbot) -> SavingsJourneyPanel:
    widget = SavingsJourneyPanel()
    qtbot.addWidget(widget)
    widget.set_currency("BDT")
    return widget


def test_the_panel_offers_every_documented_range(panel: SavingsJourneyPanel) -> None:
    offered = [panel.range_box.itemData(i) for i in range(panel.range_box.count())]

    assert offered == [months for _, months in RANGES]
    assert ALL_TIME in offered


def test_the_panel_defaults_to_twelve_months(panel: SavingsJourneyPanel) -> None:
    assert panel.selected_range == 12


def test_the_panel_shows_the_latest_month_and_its_figures(
    panel: SavingsJourneyPanel,
) -> None:
    panel.set_journey(journey(span(3)))

    assert "6,000.00 BDT" in panel.saved_tile.value_label.text()
    assert "July 2026" in panel.saved_tile.detail_label.text()


def test_a_deficit_month_is_shown_as_negative_and_said_plainly(
    panel: SavingsJourneyPanel,
) -> None:
    panel.set_journey(journey((month(2026, 7, "-5000.00"),)))

    assert "-5,000.00 BDT" in panel.saved_tile.value_label.text()
    assert "spent more than it earned" in panel.saved_tile.detail_label.text()


def test_the_rate_is_shown_as_a_percentage(panel: SavingsJourneyPanel) -> None:
    panel.set_journey(journey((month(2026, 7, "20000.00", income="50000.00"),)))

    assert panel.rate_tile.value_label.text() == "40%"


def test_a_month_with_no_income_says_so_beside_its_rate(
    panel: SavingsJourneyPanel,
) -> None:
    panel.set_journey(journey((month(2026, 7, "-5000.00", income="0.00"),)))

    assert "no income recorded" in panel.rate_tile.detail_label.text()


def test_the_first_month_has_nothing_to_compare_against(
    panel: SavingsJourneyPanel,
) -> None:
    panel.set_journey(journey((month(2026, 7, "14000.00"),)))

    assert panel.change_tile.value_label.text() == "—"
    assert "No earlier month" in panel.change_tile.detail_label.text()


def test_the_change_names_the_month_it_is_against(panel: SavingsJourneyPanel) -> None:
    panel.set_journey(journey(span(2)))

    assert "▲" in panel.change_tile.value_label.text()
    assert "June 2026" in panel.change_tile.detail_label.text()


def test_the_personal_best_is_shown_with_its_month(panel: SavingsJourneyPanel) -> None:
    panel.set_journey(journey(span(4)))

    assert "6,500.00 BDT" in panel.best_tile.value_label.text()
    assert "July 2026" in panel.best_tile.detail_label.text()


def test_no_history_leaves_every_tile_blank_rather_than_zero(
    panel: SavingsJourneyPanel,
) -> None:
    """Showing 0.00 would be a claim that the account saved nothing."""
    panel.set_journey(SavingsJourney.empty())

    assert panel.saved_tile.value_label.text() == "—"
    assert panel.best_tile.value_label.text() == "—"
    assert "No completed months yet" in panel.subtitle.text()


def test_a_failure_says_so_rather_than_claiming_no_history(
    panel: SavingsJourneyPanel,
) -> None:
    """"No completed months" is a statement about the account; showing it when
    the request failed is a quiet lie."""
    panel.show_failure("Cannot reach the FinSight backend.")

    assert "Could not load" in panel.chart.empty_title.text()
    assert "Cannot reach" in panel.chart.empty_message.text()


def test_resetting_forgets_the_session(panel: SavingsJourneyPanel) -> None:
    panel.set_journey(journey(span(6)))

    panel.reset()

    assert panel.chart.point_values == []
    assert panel.saved_tile.value_label.text() == "—"
    assert panel.selected_range == 12


# ─── The panel inside the analytics screen ────────────────────────────────


class StubApi:
    """Only what the savings panel needs; the analytics stubs live next door."""

    def __init__(self, payload: SavingsJourney | None = None) -> None:
        self.payload = payload if payload is not None else journey(span(6))
        self.calls: list[dict[str, Any]] = []
        self.failing = False

    def trend(self, **kwargs: Any):
        from client.api.dto import Trend

        return Trend.empty()

    def comparison(self, **kwargs: Any):
        from client.api.dto import Comparison

        return Comparison.empty()

    def savings(self, **kwargs: Any) -> SavingsJourney:
        self.calls.append(kwargs)
        if self.failing:
            raise ApiError("Cannot reach the FinSight backend.")
        return self.payload


@pytest.fixture
def view(qtbot) -> AnalyticsView:
    widget = AnalyticsView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()
    return widget


def test_opening_analytics_fetches_the_savings_history(view: AnalyticsView) -> None:
    assert view._api.calls


def test_the_default_request_asks_for_twelve_months(view: AnalyticsView) -> None:
    assert view._api.calls[0]["months"] == 12


def test_changing_the_range_refetches_with_the_new_window(view: AnalyticsView) -> None:
    view.savings_panel.range_box.setCurrentIndex(
        view.savings_panel.range_box.findData(3)
    )

    assert view._api.calls[-1]["months"] == 3


def test_all_time_is_requested_as_zero(view: AnalyticsView) -> None:
    view.savings_panel.range_box.setCurrentIndex(
        view.savings_panel.range_box.findData(ALL_TIME)
    )

    assert view._api.calls[-1]["months"] == ALL_TIME


def test_changing_the_savings_range_does_not_refetch_the_trend(
    view: AnalyticsView,
) -> None:
    """Two controls on one screen, and each drives only its own request."""
    before = len(view._api.calls)

    view.savings_panel.range_box.setCurrentIndex(
        view.savings_panel.range_box.findData(6)
    )

    assert len(view._api.calls) == before + 1


def test_switching_ranges_repeatedly_leaves_one_chart(view: AnalyticsView) -> None:
    box = view.savings_panel.range_box
    for _ in range(3):
        for index in range(box.count()):
            box.setCurrentIndex(index)

    assert view.savings_panel.chart.series_count == 3
    assert view.savings_panel.chart.axis_count == 2


def test_a_failed_savings_request_does_not_break_the_screen(qtbot) -> None:
    api = StubApi()
    api.failing = True
    widget = AnalyticsView(api)
    qtbot.addWidget(widget)

    widget.load_once("BDT")
    widget.reload()

    assert "Could not load" in widget.savings_panel.chart.empty_title.text()


def test_the_chart_is_told_the_currency(view: AnalyticsView) -> None:
    view.savings_panel.set_journey(journey((month(2026, 7, "14000.00"),)))

    assert "BDT" in view.savings_panel.chart.tooltip_for(0)


def test_the_panel_shows_no_badges(panel: SavingsJourneyPanel) -> None:
    """Badges were removed from this panel deliberately.

    They were four coloured words that could not say what they meant without
    a second paragraph explaining them, and the explanation repeated the
    figures already in the tiles above. The server still awards them; nothing
    on this screen renders them.
    """
    from PySide6.QtWidgets import QLabel

    panel.set_journey(
        journey(
            span(3),
            badges=(
                SavingsBadge(
                    code="personal_best", title="Personal best", detail="highest yet."
                ),
            ),
        )
    )

    # By object name, not by text: "Personal best" is also the caption of the
    # fourth stat tile, which stays. What must be gone is the badge pill and
    # the sentence explaining it.
    assert panel.findChildren(QLabel, "SavingsBadge") == []
    assert panel.findChildren(QLabel, "SavingsBadgeDetails") == []
    assert not any("highest yet" in lab.text() for lab in panel.findChildren(QLabel))
