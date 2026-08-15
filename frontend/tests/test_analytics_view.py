"""Tests for the analytics screen, its trend chart and its comparison table.

The interesting behaviour here is **tone**: spending more is bad news and
earning more is good news, so identical arithmetic has to be coloured
oppositely depending on which figure it describes. Getting that backwards would
congratulate someone for overspending.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from client.api.client import ApiError
from client.api.dto import CategoryChange, Change, Comparison, MonthTotals, Trend
from client.views.analytics_view import MAX_CATEGORY_ROWS, AnalyticsView
from client.widgets.stat_tile import NEGATIVE, NEUTRAL, POSITIVE
from client.widgets.trend_chart import CHART_PAGE, EMPTY_PAGE, TrendChart

pytestmark = pytest.mark.gui


def month(year: int, number: int, income: str = "0.00", expense: str = "0.00") -> MonthTotals:
    money_in, money_out = Decimal(income), Decimal(expense)
    return MonthTotals(
        year=year,
        month=number,
        first_day=date(year, number, 1),
        income=money_in,
        expense=money_out,
        net=money_in - money_out,
    )


def change(current: str, previous: str) -> Change:
    now, before = Decimal(current), Decimal(previous)
    difference = now - before
    percentage = (difference / before * 100).quantize(Decimal("0.01")) if before != 0 else None
    return Change(
        current=now,
        previous=before,
        difference=difference,
        percentage=percentage,
        is_new=before == 0 and now != 0,
    )


def category(name: str, current: str, previous: str, color: str = "#c0392b") -> CategoryChange:
    return CategoryChange(category_id=1, name=name, color=color, change=change(current, previous))


def comparison(
    income: Change | None = None,
    expense: Change | None = None,
    net: Change | None = None,
    categories: tuple[CategoryChange, ...] = (),
) -> Comparison:
    return Comparison(
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        previous_start=date(2026, 2, 1),
        previous_end=date(2026, 2, 28),
        income=income or change("5000.00", "4000.00"),
        expense=expense or change("3000.00", "2000.00"),
        net=net or change("2000.00", "2000.00"),
        categories=categories,
    )


def trend(months: tuple[MonthTotals, ...] = (), has_activity: bool = True) -> Trend:
    return Trend(months=months, has_activity=has_activity)


class StubApi:
    def __init__(
        self, trend_payload: Trend | None = None, comparison_payload: Comparison | None = None
    ) -> None:
        self.trend_payload = (
            trend_payload
            if trend_payload is not None
            else trend((month(2026, 2, "4000.00", "2000.00"), month(2026, 3, "5000.00", "3000.00")))
        )
        self.comparison_payload = (
            comparison_payload if comparison_payload is not None else comparison()
        )
        self.trend_calls: list[dict[str, Any]] = []
        self.comparison_calls: list[dict[str, Any]] = []

    def trend(self, **kwargs: Any) -> Trend:
        self.trend_calls.append(kwargs)
        return self.trend_payload

    def comparison(self, **kwargs: Any) -> Comparison:
        self.comparison_calls.append(kwargs)
        return self.comparison_payload


class FailingApi(StubApi):
    def trend(self, **kwargs: Any) -> Trend:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")


@pytest.fixture
def view(qtbot) -> AnalyticsView:
    widget = AnalyticsView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()
    return widget


def api_of(view: AnalyticsView) -> StubApi:
    return view._api


# ─── Loading ──────────────────────────────────────────────────────────────


def test_opening_fetches_both_the_trend_and_the_comparison(view: AnalyticsView) -> None:
    assert len(api_of(view).trend_calls) == 1
    assert len(api_of(view).comparison_calls) == 1


def test_reopening_the_section_fetches_current_data(view: AnalyticsView) -> None:
    """Used to assert the opposite. Both requests go out again, because both
    describe transactions that any other screen may have changed."""
    trends = len(api_of(view).trend_calls)
    comparisons = len(api_of(view).comparison_calls)

    view.load_once("BDT")
    view.reload()

    assert len(api_of(view).trend_calls) == trends + 1
    assert len(api_of(view).comparison_calls) == comparisons + 1


def test_the_default_span_is_six_months(view: AnalyticsView) -> None:
    assert api_of(view).trend_calls[0]["months"] == 6


def test_changing_the_span_refetches_only_the_trend(view: AnalyticsView) -> None:
    """The comparison does not depend on the span, so refetching it is waste."""
    before = len(api_of(view).comparison_calls)

    view.span_box.setCurrentIndex(view.span_box.findData(12))

    assert api_of(view).trend_calls[-1]["months"] == 12
    assert len(api_of(view).comparison_calls) == before


# ─── The trend chart ──────────────────────────────────────────────────────


def test_the_chart_plots_both_series(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)

    chart.set_months((month(2026, 2, "4000.00", "2000.00"), month(2026, 3, "5000.00", "3000.00")))

    assert chart.series_values == {
        "Income": [4000.0, 5000.0],
        "Expense": [2000.0, 3000.0],
    }


def test_the_chart_has_a_legend(qtbot) -> None:
    """Two series, so colour alone must never be the only thing telling them apart."""
    chart = TrendChart()
    qtbot.addWidget(chart)
    chart.set_months((month(2026, 3, "1.00", "1.00"),))

    assert chart.chart.legend().isVisible()


def test_the_series_use_a_colour_vision_safe_pair(qtbot) -> None:
    """Not the green/red used for signed amounts — measured at ΔE 4.5 under
    deuteranopia, which is the same colour to roughly one man in twelve."""
    from client.widgets.trend_chart import EXPENSE_COLOUR, INCOME_COLOUR

    assert INCOME_COLOUR.name() == "#1a56c4"
    assert EXPENSE_COLOUR.name() == "#d9782e"


def test_month_labels_name_the_year_where_it_turns_over(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)

    chart.set_months((month(2025, 12, "1.00"), month(2026, 1, "1.00"), month(2026, 2, "1.00")))

    assert chart.month_labels == ["Dec 25", "Jan 26", "Feb"]


def test_an_empty_span_shows_words_not_flat_bars(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)

    chart.set_months((month(2026, 2), month(2026, 3)), has_activity=False)

    assert chart.currentIndex() == EMPTY_PAGE


def test_activity_switches_the_chart_on(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)
    chart.set_months((), has_activity=False)

    chart.set_months((month(2026, 3, "100.00"),))

    assert chart.currentIndex() == CHART_PAGE


def test_redrawing_replaces_the_series(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)

    chart.set_months((month(2026, 2, "1.00"), month(2026, 3, "2.00")))
    chart.set_months((month(2026, 3, "9.00"),))

    assert chart.series_values["Income"] == [9.0]


# ─── Tone: the same arithmetic, opposite meanings ─────────────────────────


def test_earning_more_is_good_news(qtbot) -> None:
    widget = AnalyticsView(
        StubApi(comparison_payload=comparison(income=change("5000.00", "4000.00")))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.income_tile.value_label.property("tone") == POSITIVE


def test_spending_more_is_bad_news(qtbot) -> None:
    """Identical arithmetic to the test above, and the opposite verdict."""
    widget = AnalyticsView(
        StubApi(comparison_payload=comparison(expense=change("3000.00", "2000.00")))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.expense_tile.value_label.property("tone") == NEGATIVE


def test_spending_less_is_good_news(qtbot) -> None:
    widget = AnalyticsView(
        StubApi(comparison_payload=comparison(expense=change("1000.00", "2000.00")))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.expense_tile.value_label.property("tone") == POSITIVE


def test_no_change_is_neither(qtbot) -> None:
    widget = AnalyticsView(
        StubApi(comparison_payload=comparison(expense=change("2000.00", "2000.00")))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.expense_tile.value_label.property("tone") == NEUTRAL


# ─── Change wording ───────────────────────────────────────────────────────


def test_a_movement_names_both_the_amount_and_the_percentage(qtbot) -> None:
    """A percentage hides the size; an amount hides the significance."""
    widget = AnalyticsView(
        StubApi(comparison_payload=comparison(expense=change("3000.00", "2000.00")))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.expense_tile.detail_label.text() == "up 1,000.00 BDT (50%)"


def test_a_fall_reads_as_down(qtbot) -> None:
    widget = AnalyticsView(
        StubApi(comparison_payload=comparison(expense=change("500.00", "2000.00")))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.expense_tile.detail_label.text() == "down 1,500.00 BDT (75%)"


def test_something_new_says_so_rather_than_inventing_a_percentage(qtbot) -> None:
    widget = AnalyticsView(StubApi(comparison_payload=comparison(expense=change("500.00", "0.00"))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.expense_tile.detail_label.text() == "new this period"


def test_no_movement_says_no_change(qtbot) -> None:
    widget = AnalyticsView(
        StubApi(comparison_payload=comparison(expense=change("500.00", "500.00")))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.expense_tile.detail_label.text() == "no change"


# ─── The comparison table ─────────────────────────────────────────────────


def rows_of(view: AnalyticsView) -> list:
    from PySide6.QtWidgets import QWidget

    return view._rows_holder.findChildren(QWidget, "ChangeRow")


def test_each_category_becomes_a_row(qtbot) -> None:
    widget = AnalyticsView(
        StubApi(
            comparison_payload=comparison(
                categories=(
                    category("Rent", "15000.00", "15000.00"),
                    category("Food", "3000.00", "2000.00"),
                )
            )
        )
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert len(rows_of(widget)) == 2


def test_the_table_stops_after_the_biggest_movers(qtbot) -> None:
    """The list is sorted by movement, so the tail barely moved by definition."""
    many = tuple(category(f"Cat {i}", "100.00", "50.00") for i in range(20))
    widget = AnalyticsView(StubApi(comparison_payload=comparison(categories=many)))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert len(rows_of(widget)) == MAX_CATEGORY_ROWS


def test_the_title_names_the_period_being_compared_against(view: AnalyticsView) -> None:
    assert "01 Feb – 28 Feb" in view.comparison_title.text()


def test_the_period_is_named(view: AnalyticsView) -> None:
    assert view.period_label.text() == "01 Mar – 31 Mar 2026"


def test_an_empty_comparison_says_so(qtbot) -> None:
    widget = AnalyticsView(StubApi(comparison_payload=comparison(categories=())))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.comparison_empty.isVisibleTo(widget)
    assert rows_of(widget) == []


def test_movement_text_uses_an_arrow_as_well_as_colour(view: AnalyticsView) -> None:
    """Colour alone would exclude anyone who cannot distinguish red from green."""
    assert view._movement_text(change("300.00", "200.00")).startswith("▲")
    assert view._movement_text(change("100.00", "200.00")).startswith("▼")
    assert view._movement_text(change("200.00", "200.00")) == "—"
    assert view._movement_text(change("200.00", "0.00")) == "new"


# ─── Failure ──────────────────────────────────────────────────────────────


def test_an_unreachable_backend_is_reported_not_crashed(qtbot) -> None:
    widget = AnalyticsView(FailingApi())
    qtbot.addWidget(widget)

    widget.load_once("BDT")
    widget.reload()

    widget.reload()

    assert "Cannot reach" in widget.banner.text()
    assert widget.trend_chart.currentIndex() == EMPTY_PAGE


def test_one_request_succeeding_does_not_erase_the_others_error(qtbot) -> None:
    """The bug this test was written to catch.

    The screen makes two independent requests. With a single "did it fail"
    flag, the comparison succeeding a moment after the trend failed cleared the
    banner, and the failure vanished with no sign it had happened.
    """
    widget = AnalyticsView(FailingApi())
    qtbot.addWidget(widget)

    widget.load_once("BDT")  # trend fails, comparison succeeds
    widget.reload()

    assert "Cannot reach" in widget.banner.text()


def test_the_banner_clears_once_the_failure_stops(qtbot) -> None:
    api = FailingApi()
    widget = AnalyticsView(api)
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()
    assert widget.banner.text()

    # Recover: the stub stops raising.
    api.trend = lambda **kwargs: trend((month(2026, 3, "100.00"),))
    widget.reload_trend()

    assert widget.banner.text() == ""


def test_two_failures_are_not_repeated_word_for_word(qtbot) -> None:
    class BothFail(StubApi):
        def trend(self, **kwargs: Any) -> Trend:
            raise ApiError("Cannot reach the FinSight backend. Is it running?")

        def comparison(self, **kwargs: Any) -> Comparison:
            raise ApiError("Cannot reach the FinSight backend. Is it running?")

    widget = AnalyticsView(BothFail())
    qtbot.addWidget(widget)

    widget.load_once("BDT")
    widget.reload()

    widget.reload()

    assert widget.banner.text().count("Cannot reach") == 1


# ─── Failure is not emptiness ─────────────────────────────────────────────
#
# Found by auditing the empty states rather than by a test failing. Both panels
# had one message for "your account has nothing" and used it for "we could not
# fetch anything", which reads as an empty account to the one person who cannot
# tell the difference.


class BothFailingApi(StubApi):
    def trend(self, **kwargs: Any) -> Trend:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")

    def comparison(self, **kwargs: Any) -> Comparison:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")


def test_a_failed_trend_does_not_claim_there_was_no_activity(qtbot) -> None:
    """"No activity in this span" is a claim about the account. When the
    request failed, it is a false one — and it is the sentence being read,
    since the banner is elsewhere on the screen."""
    widget = AnalyticsView(BothFailingApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.trend_chart.currentIndex() == EMPTY_PAGE
    assert widget.trend_chart.empty_title.text() == "Could not load the trend"
    assert "Cannot reach" in widget.trend_chart.empty_message.text()


def test_a_failed_comparison_does_not_claim_there_was_nothing_to_compare(qtbot) -> None:
    widget = AnalyticsView(BothFailingApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert "Could not load the comparison" in widget.comparison_empty.text()


def test_a_genuinely_empty_account_still_says_so(qtbot) -> None:
    """The other half of the same fix: the failure wording must not leak into
    the ordinary empty state."""
    widget = AnalyticsView(StubApi(trend_payload=trend((), has_activity=False)))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.trend_chart.empty_title.text() == "No activity in this span"
    assert widget.comparison_empty.text() == "Nothing to compare yet."


def test_recovering_restores_the_ordinary_wording(qtbot) -> None:
    """A failure followed by a success must not leave the failure on screen."""
    api = BothFailingApi()
    widget = AnalyticsView(api)
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    widget._api = StubApi(trend_payload=trend((), has_activity=False))
    widget.reload_trend()
    widget.reload_comparison()

    assert widget.trend_chart.empty_title.text() == "No activity in this span"
    assert widget.comparison_empty.text() == "Nothing to compare yet."


# ─── Tooltips ─────────────────────────────────────────────────────────────
#
# The wording is checked directly rather than by synthesising mouse movement
# over a chart: the sentence is the part that can be wrong, and hovering is
# Qt's job.


def test_a_bar_names_its_month_and_its_figure(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)
    chart.set_currency("BDT")
    chart.set_months((month(2026, 2, "4000.00", "2500.00"),))

    assert chart.tooltip_for(0, "Income") == "February 2026 · income 4,000.00 BDT"
    assert chart.tooltip_for(0, "Expense") == "February 2026 · expense 2,500.00 BDT"


def test_a_tooltip_for_a_bar_that_is_not_there_is_empty(qtbot) -> None:
    """Qt can emit a hover for an index outside the current data during a
    redraw, and an IndexError inside a signal handler is a crash."""
    chart = TrendChart()
    qtbot.addWidget(chart)
    chart.set_months((month(2026, 2, "1.00", "1.00"),))

    assert chart.tooltip_for(9, "Income") == ""
    assert chart.tooltip_for(-1, "Income") == ""


def test_tooltips_follow_a_redraw(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)
    chart.set_months((month(2026, 2, "1.00", "1.00"),))
    chart.set_months((month(2026, 7, "9.00", "9.00"),))

    assert "July 2026" in chart.tooltip_for(0, "Income")


def test_a_failed_load_leaves_no_stale_tooltips(qtbot) -> None:
    chart = TrendChart()
    qtbot.addWidget(chart)
    chart.set_months((month(2026, 2, "1.00", "1.00"),))

    chart.show_failure("Cannot reach the FinSight backend.")

    assert chart.tooltip_for(0, "Income") == ""


def test_the_chart_is_told_the_currency(view: AnalyticsView) -> None:
    view.trend_chart.set_months((month(2026, 2, "10.00", "5.00"),))

    assert view.trend_chart.tooltip_for(0, "Income").endswith("BDT")
