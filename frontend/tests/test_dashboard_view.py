"""Tests for the dashboard, its stat tiles and its spending chart.

Two things get most of the attention:

  * the dashboard is **one** request — a screen assembled from five would show
    figures taken at five different moments;
  * the chart is a ranked bar chart, not a pie, and its bars are ordered
    largest-first with the folded "Other categories" row last.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from client.api.client import ApiError
from client.api.dto import (
    BudgetHealth,
    Category,
    CategoryShare,
    Dashboard,
    Insight,
    PeriodTotals,
    Subscription,
    SubscriptionSummary,
    Transaction,
    User,
)
from client.views.dashboard_view import DashboardView
from client.widgets.spending_chart import CHART_PAGE, EMPTY_PAGE, SpendingChart
from client.widgets.stat_tile import NEGATIVE, POSITIVE, StatTile

pytestmark = pytest.mark.gui

FOOD = Category(id=2, name="Food", category_type="expense", color="#c0392b")


def share(name: str, total: str, percentage: str, category_id: int | None = 1) -> CategoryShare:
    return CategoryShare(
        category_id=category_id,
        name=name,
        color="#c0392b" if category_id else None,
        total=Decimal(total),
        percentage=Decimal(percentage),
    )


def transaction(id: int = 1, amount: str = "250.00", kind: str = "expense") -> Transaction:
    return Transaction(
        id=id,
        amount=Decimal(amount),
        transaction_type=kind,
        date=date(2026, 3, 12),
        category=FOOD,
        description="Lunch at campus",
        payment_method="cash",
    )


def subscription(name: str = "Netflix", days: int = 4) -> Subscription:
    return Subscription(
        id=1,
        name=name,
        amount=Decimal("499.00"),
        billing_cycle="monthly",
        status="active",
        start_date=date(2026, 1, 10),
        next_billing_date=date(2026, 3, 19),
        end_date=None,
        category=None,
        payment_method="card",
        notes=None,
        monthly_cost=Decimal("499.00"),
        yearly_cost=Decimal("5988.00"),
        days_until_renewal=days,
        is_due_soon=days <= 7,
    )


def dashboard(
    income: str = "45000.00",
    expense: str = "12000.00",
    spending: tuple[CategoryShare, ...] = (),
    recent: tuple[Transaction, ...] = (),
    budgets: BudgetHealth | None = None,
    upcoming: Subscription | None = None,
    active: int = 0,
    start: str = "2026-03-01",
    end: str = "2026-03-31",
    insights: tuple[Insight, ...] = (),
    needs_attention: int = 0,
) -> Dashboard:
    money_in, money_out = Decimal(income), Decimal(expense)
    return Dashboard(
        period_start=date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        totals=PeriodTotals(
            income=money_in,
            expense=money_out,
            net=money_in - money_out,
            transaction_count=len(recent) or 3,
        ),
        spending=spending,
        recent=recent,
        budgets=budgets or BudgetHealth(0, 0, 0, 0, 0),
        subscriptions=SubscriptionSummary(
            active_count=active,
            paused_count=0,
            cancelled_count=0,
            monthly_total=Decimal("499.00") if active else Decimal("0.00"),
            yearly_total=Decimal("5988.00") if active else Decimal("0.00"),
            next_renewal=upcoming,
        ),
        insights=insights,
        needs_attention=needs_attention,
    )


def insight(
    title: str = "Food budget exceeded",
    detail: str = "You have spent 12,000.00 against a 10,000.00 budget.",
    severity: str = "critical",
) -> Insight:
    return Insight(code="budget_exceeded", severity=severity, title=title, detail=detail)


class StubApi:
    def __init__(self, payload: Dashboard | None = None) -> None:
        self.payload = payload if payload is not None else dashboard()
        self.calls: list[dict[str, Any]] = []

    def dashboard(self, **kwargs: Any) -> Dashboard:
        self.calls.append(kwargs)
        return self.payload


class FailingApi(StubApi):
    def dashboard(self, **kwargs: Any) -> Dashboard:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")


@pytest.fixture
def view(qtbot) -> DashboardView:
    widget = DashboardView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")
    return widget


def api_of(view: DashboardView) -> StubApi:
    return view._api


# ─── One request ──────────────────────────────────────────────────────────


def test_the_whole_screen_comes_from_one_request(view: DashboardView) -> None:
    """Five requests would mean five loading states and five different moments."""
    assert len(api_of(view).calls) == 1


def test_opening_twice_does_not_refetch(view: DashboardView) -> None:
    before = len(api_of(view).calls)

    view.load_once("BDT", "Sayed")

    assert len(api_of(view).calls) == before


def test_the_greeting_uses_the_name_it_was_given(view: DashboardView) -> None:
    """Whole name, unshortened: no rule can tell which word someone goes by."""
    assert view.greeting.text() == "Hello, Sayed"


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        # The honorific goes; which of the two remaining words someone goes by
        # is not knowable from the string, so the first is taken.
        ("Md. Abu Sayed", "Abu"),
        ("Mohammad Abu Sayed", "Abu"),
        ("Dr. Jane Roberts", "Jane"),
        ("MRS Anita Bose", "Anita"),
        ("Anita Bose", "Anita"),
        ("Cher", "Cher"),
        # Only an honorific: better the whole string than an empty greeting.
        ("Md.", "Md."),
    ],
)
def test_first_name_skips_honorifics(full_name: str, expected: str) -> None:
    """Found by rendering the dashboard, which greeted the author as "Md.".

    The greeting itself now uses the full name — picking a short form from a
    full name is guesswork. This property is still fixed, because returning a
    title where a name was asked for was simply wrong.
    """
    user = User(
        id=1,
        email="s@example.com",
        full_name=full_name,
        currency_code="BDT",
        role="user",
        is_active=True,
    )

    assert user.first_name == expected


# ─── Headline figures ─────────────────────────────────────────────────────


def test_the_lead_figure_is_what_was_kept(view: DashboardView) -> None:
    assert view.net_tile.value_label.text() == "33,000.00 BDT"
    assert view.income_tile.value_label.text() == "45,000.00 BDT"
    assert view.expense_tile.value_label.text() == "12,000.00 BDT"


def test_a_positive_month_reads_positive(view: DashboardView) -> None:
    assert view.net_tile.value_label.property("tone") == POSITIVE


def test_a_negative_month_is_flagged_and_explained(qtbot) -> None:
    widget = DashboardView(StubApi(dashboard(income="1000.00", expense="2500.00")))
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    assert widget.net_tile.value_label.text() == "-1,500.00 BDT"
    assert widget.net_tile.value_label.property("tone") == NEGATIVE
    assert "More went out" in widget.net_tile.detail_label.text()


def test_the_period_is_named(view: DashboardView) -> None:
    assert view.period_label.text() == "March 2026"


def test_a_period_spanning_months_shows_both_ends(qtbot) -> None:
    widget = DashboardView(StubApi(dashboard(start="2026-01-01", end="2026-03-31")))
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    assert widget.period_label.text() == "01 Jan 2026 – 31 Mar 2026"


def test_the_subscription_tile_shows_the_monthly_commitment(qtbot) -> None:
    widget = DashboardView(StubApi(dashboard(active=2, upcoming=subscription())))
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    assert widget.commitment_tile.value_label.text() == "499.00 BDT"
    assert widget.commitment_tile.detail_label.text() == "2 active"


def test_no_subscriptions_says_none_tracked(view: DashboardView) -> None:
    assert view.commitment_tile.detail_label.text() == "None tracked"


# ─── Stat tiles ───────────────────────────────────────────────────────────


def test_a_tile_without_context_hides_its_detail_line(qtbot) -> None:
    """A blank label would make one tile taller and break the row's alignment."""
    tile = StatTile("Money in", "100.00")
    qtbot.addWidget(tile)

    assert not tile.detail_label.isVisible()

    tile.set_value("200.00", detail="from 3 transactions")
    assert tile.detail_label.isVisibleTo(tile)


def test_a_tile_updates_its_tone(qtbot) -> None:
    tile = StatTile("Kept", "0.00")
    qtbot.addWidget(tile)

    tile.set_value("-50.00", tone=NEGATIVE)

    assert tile.value_label.property("tone") == NEGATIVE


# ─── The spending chart ───────────────────────────────────────────────────


def test_the_chart_ranks_categories_largest_first(qtbot) -> None:
    chart = SpendingChart()
    qtbot.addWidget(chart)

    chart.set_shares(
        (
            share("Rent", "900.00", "50.00"),
            share("Food", "600.00", "33.33"),
            share("Transport", "300.00", "16.67"),
        )
    )

    assert chart.bar_values == [900.0, 600.0, 300.0]
    assert [label.split("  ")[0] for label in chart.axis_labels] == [
        "Rent",
        "Food",
        "Transport",
    ]


def test_the_chart_labels_carry_the_share(qtbot) -> None:
    """A bar chart loses part-to-whole, so the percentage is printed back in."""
    chart = SpendingChart()
    qtbot.addWidget(chart)

    chart.set_shares((share("Rent", "900.00", "75.00"),))

    assert "75%" in chart.axis_labels[0]


def test_the_chart_has_no_legend(qtbot) -> None:
    """One series — the panel title names it, so a legend box is noise."""
    chart = SpendingChart()
    qtbot.addWidget(chart)
    chart.set_shares((share("Rent", "900.00", "100.00"),))

    assert not chart.chart.legend().isVisible()


def test_an_empty_chart_shows_words_not_empty_axes(qtbot) -> None:
    chart = SpendingChart()
    qtbot.addWidget(chart)

    chart.set_shares(())

    assert chart.currentIndex() == EMPTY_PAGE
    assert chart.empty_title.text() == "Nothing spent yet"


def test_data_switches_the_chart_back_on(qtbot) -> None:
    chart = SpendingChart()
    qtbot.addWidget(chart)
    chart.set_shares(())

    chart.set_shares((share("Rent", "900.00", "100.00"),))

    assert chart.currentIndex() == CHART_PAGE


def test_redrawing_replaces_the_bars_rather_than_adding_to_them(qtbot) -> None:
    chart = SpendingChart()
    qtbot.addWidget(chart)

    chart.set_shares((share("Rent", "900.00", "100.00"),))
    chart.set_shares((share("Food", "100.00", "100.00"),))

    assert chart.bar_values == [100.0]


def test_the_folded_tail_is_the_last_bar(qtbot) -> None:
    chart = SpendingChart()
    qtbot.addWidget(chart)

    chart.set_shares(
        (
            share("Rent", "900.00", "60.00"),
            share("Other categories", "600.00", "40.00", category_id=None),
        )
    )

    assert chart.axis_labels[-1].startswith("Other categories")


def test_the_dashboard_passes_its_breakdown_to_the_chart(qtbot) -> None:
    widget = DashboardView(StubApi(dashboard(spending=(share("Rent", "900.00", "100.00"),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    assert widget.chart.bar_values == [900.0]


# ─── Recent activity ──────────────────────────────────────────────────────


def test_recent_rows_are_listed(qtbot) -> None:
    widget = DashboardView(
        StubApi(dashboard(recent=(transaction(1), transaction(2), transaction(3))))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    rows = widget._recent_holder.findChildren(type(widget._recent_holder), "RecentRow")
    assert len(rows) == 3


def test_an_empty_recent_list_says_so(view: DashboardView) -> None:
    assert view.recent_empty.isVisibleTo(view)


def test_income_and_expense_are_signed_in_the_recent_list(qtbot) -> None:
    from PySide6.QtWidgets import QLabel

    widget = DashboardView(
        StubApi(recent_payload := dashboard(recent=(transaction(1, kind="income"),)))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    amounts = [label.text() for label in widget.findChildren(QLabel, "RecentAmount")]
    assert amounts == ["+250.00 BDT"]
    assert recent_payload.recent[0].is_income


# ─── The attention bar ────────────────────────────────────────────────────


def test_the_attention_bar_renders_the_top_insight(qtbot) -> None:
    """It used to work out its own line from budget counts and the next
    renewal — a second place deciding what matters, free to disagree with the
    insights screen. It now shows what the server already ranked (ADR-008)."""
    widget = DashboardView(StubApi(dashboard(insights=(insight(),), needs_attention=1)))
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    assert "Food budget exceeded" in widget.attention_label.text()
    assert "12,000.00" in widget.attention_label.text()
    assert widget.attention_bar.property("state") == "warning"


def test_the_attention_bar_counts_the_rest(qtbot) -> None:
    widget = DashboardView(
        StubApi(
            dashboard(
                insights=(insight(), insight(title="Rent is up"), insight(title="Netflix renews")),
                needs_attention=2,
            )
        )
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    assert "2 more" in widget.attention_label.text()


def test_good_news_only_leaves_the_bar_calm(qtbot) -> None:
    widget = DashboardView(
        StubApi(
            dashboard(
                insights=(insight(title="Food spending is down", severity="good"),),
                needs_attention=0,
            )
        )
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT", "Sayed")

    assert "Food spending is down" in widget.attention_label.text()
    assert widget.attention_bar.property("state") == "calm"


def test_nothing_to_report_says_so(view: DashboardView) -> None:
    assert view.attention_label.text() == "Nothing needs attention"


# ─── Navigation ───────────────────────────────────────────────────────────


def test_the_dashboard_asks_the_shell_to_navigate(view: DashboardView) -> None:
    """It points at other screens rather than reproducing them."""
    asked: list[str] = []
    view.navigate_requested.connect(asked.append)

    view.budgets_button.click()
    view.subscriptions_button.click()
    view.insights_button.click()

    assert asked == ["budgets", "subscriptions", "insights"]


# ─── Failure ──────────────────────────────────────────────────────────────


def test_an_unreachable_backend_is_reported_not_crashed(qtbot) -> None:
    widget = DashboardView(FailingApi())
    qtbot.addWidget(widget)

    widget.load_once("BDT", "Sayed")

    assert "Cannot reach" in widget.banner.text()
    assert widget.chart.currentIndex() == EMPTY_PAGE
    assert widget.period_label.text() == ""


# ─── Tooltips ─────────────────────────────────────────────────────────────


def test_a_bar_names_its_category_amount_and_share(qtbot) -> None:
    chart = SpendingChart()
    qtbot.addWidget(chart)
    chart.set_currency("BDT")
    chart.set_shares((share("Food", "4000.00", "40.00"), share("Rent", "6000.00", "60.00")))

    # The bars are drawn reversed so the largest sits at the top, and index 0
    # is the *bottom* one. Reading the unreversed list here would name the
    # wrong category on every bar but the middle — right until somebody checks.
    assert chart.tooltip_for(0) == "Rent · 6,000.00 BDT · 60% of spending"
    assert chart.tooltip_for(1) == "Food · 4,000.00 BDT · 40% of spending"


def test_a_tooltip_for_a_bar_that_is_not_there_is_empty(qtbot) -> None:
    """Qt can emit a hover for an index outside the current data during a
    redraw, and an IndexError inside a signal handler is a crash."""
    chart = SpendingChart()
    qtbot.addWidget(chart)
    chart.set_shares((share("Food", "10.00", "100.00"),))

    assert chart.tooltip_for(4) == ""
    assert chart.tooltip_for(-1) == ""


def test_spending_tooltips_follow_a_redraw(qtbot) -> None:
    chart = SpendingChart()
    qtbot.addWidget(chart)
    chart.set_shares((share("Food", "10.00", "100.00"),))
    chart.set_shares((share("Rent", "20.00", "100.00"),))

    assert chart.tooltip_for(0).startswith("Rent")
