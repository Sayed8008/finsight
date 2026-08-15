"""Tests for the insights screen.

The rules are tested as pure functions on the server. What matters here is that
the screen **renders and decides nothing** — no severity is recomputed, no
ordering is second-guessed, and every explanation the server wrote reaches the
user intact.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from PySide6.QtWidgets import QFrame, QLabel

from client.api.client import ApiError
from client.api.dto import Insight, Insights
from client.views.insights_view import SEVERITY_LABELS, InsightsView

pytestmark = pytest.mark.gui


def insight(
    code: str = "budget_exceeded",
    severity: str = "critical",
    title: str = "Food budget exceeded",
    detail: str = "You have spent 12,000.00 against a 10,000.00 budget — 2,000.00 over.",
    category_id: int | None = None,
    subscription_id: int | None = None,
) -> Insight:
    return Insight(
        code=code,
        severity=severity,
        title=title,
        detail=detail,
        category_id=category_id,
        subscription_id=subscription_id,
    )


def insights(items: tuple[Insight, ...] = (), needs_attention: int | None = None) -> Insights:
    bad = sum(1 for item in items if item.is_bad_news)
    return Insights(
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        items=items,
        needs_attention=needs_attention if needs_attention is not None else bad,
        counts={},
    )


class StubApi:
    def __init__(self, payload: Insights | None = None) -> None:
        self.payload = payload if payload is not None else insights((insight(),))
        self.calls: list[dict[str, Any]] = []

    def insights(self, **kwargs: Any) -> Insights:
        self.calls.append(kwargs)
        return self.payload


class FailingApi(StubApi):
    def insights(self, **kwargs: Any) -> Insights:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")


@pytest.fixture
def view(qtbot) -> InsightsView:
    widget = InsightsView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()
    return widget


def api_of(view: InsightsView) -> StubApi:
    return view._api


def cards(view: InsightsView) -> list[QFrame]:
    return view.findChildren(QFrame, "InsightCard")


def texts(view: InsightsView, name: str) -> list[str]:
    return [label.text() for label in view.findChildren(QLabel, name)]


# ─── Loading ──────────────────────────────────────────────────────────────


def test_opening_fetches_the_insights(view: InsightsView) -> None:
    assert len(api_of(view).calls) == 1
    assert len(cards(view)) == 1


def test_reopening_the_section_fetches_current_data(view: InsightsView) -> None:
    """Used to assert the opposite. Insights are recomputed on every request
    and can never be stale on the server (ADR-030) — caching them here is the
    one way to make them stale, and it is what this screen used to do."""
    view.load_once("BDT")
    view.reload()

    assert len(api_of(view).calls) == 2


def test_refresh_fetches_again(view: InsightsView) -> None:
    """The only way to see a newly-crossed threshold without restarting."""
    view.refresh_button.click()

    assert len(api_of(view).calls) == 2


# ─── Rendering ────────────────────────────────────────────────────────────


def test_every_explanation_reaches_the_user_intact(qtbot) -> None:
    """The explanation is the feature; truncating it would remove the point."""
    written = "Transport is 2,480.00 this period against 1,100.00 last — up 125%."
    widget = InsightsView(StubApi(insights((insight(detail=written),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert texts(widget, "InsightDetail") == [written]


def test_the_severity_the_server_sent_is_the_one_used(qtbot) -> None:
    """No threshold is recomputed here — there is one definition, on the server."""
    widget = InsightsView(StubApi(insights((insight(severity="warning"),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert cards(widget)[0].property("severity") == "warning"


def test_severity_is_shown_in_words_as_well_as_colour(qtbot) -> None:
    """A coloured edge alone would exclude anyone who cannot see the colour."""
    widget = InsightsView(StubApi(insights((insight(severity="critical"),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert texts(widget, "InsightBadge") == [SEVERITY_LABELS["critical"]]


def test_the_order_the_server_sent_is_preserved(qtbot) -> None:
    """It already ranked them. Re-sorting here could only disagree."""
    ordered = (
        insight(title="First", severity="critical"),
        insight(title="Second", severity="warning"),
        insight(title="Third", severity="good"),
    )
    widget = InsightsView(StubApi(insights(ordered)))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert texts(widget, "InsightTitle") == ["First", "Second", "Third"]


def test_reloading_replaces_the_cards(view: InsightsView) -> None:
    view.reload()
    view.reload()

    assert len(cards(view)) == 1


def test_the_summary_counts_what_needs_attention(qtbot) -> None:
    widget = InsightsView(
        StubApi(
            insights(
                (
                    insight(severity="critical"),
                    insight(severity="good", title="Food is down"),
                )
            )
        )
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.summary_label.text() == "1 of 2 need attention"


def test_only_good_news_is_said_as_such(qtbot) -> None:
    widget = InsightsView(StubApi(insights((insight(severity="good", title="Down"),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert "nothing needs action" in widget.summary_label.text()


def test_no_insights_shows_no_count(view: InsightsView) -> None:
    """ "0 insights" reads as a failure rather than an account in good order."""
    widget = InsightsView(StubApi(insights(())))
    widget.load_once("BDT")
    widget.reload()

    assert widget.summary_label.text() == ""


# ─── Filtering ────────────────────────────────────────────────────────────


def test_filtering_to_what_needs_attention(qtbot) -> None:
    widget = InsightsView(
        StubApi(
            insights(
                (
                    insight(severity="critical", title="Bad"),
                    insight(severity="warning", title="Also bad"),
                    insight(severity="info", title="Neutral"),
                    insight(severity="good", title="Nice"),
                )
            )
        )
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    widget.filter_box.setCurrentIndex(widget.filter_box.findData("attention"))

    assert [item.title for item in widget.visible_insights()] == ["Bad", "Also bad"]


def test_filtering_to_good_news(qtbot) -> None:
    widget = InsightsView(
        StubApi(insights((insight(severity="critical"), insight(severity="good", title="Nice"))))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    widget.filter_box.setCurrentIndex(widget.filter_box.findData("good"))

    assert [item.title for item in widget.visible_insights()] == ["Nice"]


def test_filtering_does_not_refetch(view: InsightsView) -> None:
    """Everything is already here; a round trip to hide rows would be waste."""
    before = len(api_of(view).calls)

    view.filter_box.setCurrentIndex(view.filter_box.findData("attention"))

    assert len(api_of(view).calls) == before


def test_a_filter_matching_nothing_says_so_differently(qtbot) -> None:
    widget = InsightsView(StubApi(insights((insight(severity="good", title="Nice"),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    widget.filter_box.setCurrentIndex(widget.filter_box.findData("attention"))

    assert widget.empty_title.text() == "Nothing matches that filter"


# ─── Links ────────────────────────────────────────────────────────────────


def test_an_insight_about_a_subscription_links_to_subscriptions(qtbot) -> None:
    widget = InsightsView(StubApi(insights((insight(subscription_id=7),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()
    asked: list[str] = []
    widget.navigate_requested.connect(asked.append)

    from PySide6.QtWidgets import QPushButton

    link = widget.findChildren(QPushButton, "LinkButton")[0]
    link.click()

    assert asked == ["subscriptions"]


def test_an_insight_about_a_category_links_to_budgets(qtbot) -> None:
    widget = InsightsView(StubApi(insights((insight(category_id=3),))))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget._target_for(insight(category_id=3)) == "budgets"


def test_an_insight_about_nothing_in_particular_has_no_link(qtbot) -> None:
    """Derived from what it is attached to, so a new rule gets this for free."""
    assert InsightsView._target_for(insight()) is None


# ─── Empty and error states ───────────────────────────────────────────────


def test_nothing_found_is_reported_as_good_standing(qtbot) -> None:
    widget = InsightsView(StubApi(insights(())))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.empty_title.text() == "Nothing needs your attention"
    assert cards(widget) == []


def test_an_unreachable_backend_is_reported_not_crashed(qtbot) -> None:
    widget = InsightsView(FailingApi())
    qtbot.addWidget(widget)

    widget.load_once("BDT")
    widget.reload()

    widget.reload()

    assert "Cannot reach" in widget.banner.text()
    assert widget.empty_title.text() == "Could not load insights"
    assert cards(widget) == []
