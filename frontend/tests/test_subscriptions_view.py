"""Tests for the subscriptions screen, its cards and its dialog.

Same theme as the budgets tests: the client renders what the server computed.
The one place that matters most here is the renewal wording, which turns
`days_until_renewal` into "in 3 days" / "tomorrow" / "overdue by 2 days" — the
only real logic on this side of the wire.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from PySide6.QtCore import QDate

from client.api.client import ApiError
from client.api.dto import Candidate, Category, Detection, Subscription, SubscriptionSummary
from client.views.subscriptions_view import CARDS_PAGE, EMPTY_PAGE, SubscriptionsView
from client.widgets.subscription_card import SubscriptionCard
from client.widgets.subscription_dialog import SubscriptionDialog

pytestmark = pytest.mark.gui

CATEGORIES = [
    Category(id=1, name="Salary", category_type="income", color="#1a7f4b"),
    Category(id=2, name="Subscriptions", category_type="expense", color="#5b6ee0"),
]
SUBS_CATEGORY = CATEGORIES[1]


def subscription(
    id: int = 1,
    name: str = "Netflix",
    amount: str = "499.00",
    cycle: str = "monthly",
    status: str = "active",
    days: int = 5,
    category: Category | None = None,
    next_date: str = "2026-03-20",
    end_date: str | None = None,
) -> Subscription:
    value = Decimal(amount)
    per_month = {"monthly": value, "yearly": value / 12, "weekly": value * 52 / 12}.get(
        cycle, value
    )
    return Subscription(
        id=id,
        name=name,
        amount=value,
        billing_cycle=cycle,
        status=status,
        start_date=date(2026, 1, 20),
        next_billing_date=date.fromisoformat(next_date),
        end_date=date.fromisoformat(end_date) if end_date else None,
        category=category,
        payment_method="card",
        notes=None,
        monthly_cost=per_month.quantize(Decimal("0.01")),
        yearly_cost=(per_month * 12).quantize(Decimal("0.01")),
        days_until_renewal=days,
        is_due_soon=status == "active" and days <= 7,
    )


def summary(
    monthly: str = "499.00",
    yearly: str = "5988.00",
    active: int = 1,
    paused: int = 0,
    cancelled: int = 0,
    upcoming: Subscription | None = None,
) -> SubscriptionSummary:
    return SubscriptionSummary(
        active_count=active,
        paused_count=paused,
        cancelled_count=cancelled,
        monthly_total=Decimal(monthly),
        yearly_total=Decimal(yearly),
        next_renewal=upcoming,
    )


class StubApi:
    def __init__(
        self,
        subscriptions: list[Subscription] | None = None,
        totals: SubscriptionSummary | None = None,
    ) -> None:
        self.rows = subscriptions if subscriptions is not None else [subscription()]
        self.totals = totals if totals is not None else summary()
        self.calls: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[int, dict[str, Any]]] = []
        self.renewed: list[int] = []
        self.deleted: list[int] = []
        self.detections = 0
        self.detection_payload = Detection(
            searched_from=date(2025, 6, 15), searched_to=date(2026, 6, 15), candidates=()
        )

    def categories(self, **_: Any) -> list[Category]:
        return list(CATEGORIES)

    def payment_methods(self) -> list[str]:
        return ["card", "bKash"]

    def subscriptions(self, **kwargs: Any) -> list[Subscription]:
        self.calls.append(kwargs)
        return list(self.rows)

    def subscription_summary(self) -> SubscriptionSummary:
        return self.totals

    def create_subscription(self, **fields: Any) -> Subscription:
        self.created.append(fields)
        return subscription()

    def update_subscription(self, subscription_id: int, **changes: Any) -> Subscription:
        self.updated.append((subscription_id, changes))
        return subscription()

    def renew_subscription(self, subscription_id: int) -> Subscription:
        self.renewed.append(subscription_id)
        return subscription()

    def delete_subscription(self, subscription_id: int) -> None:
        self.deleted.append(subscription_id)

    def detect_subscriptions(self, **kwargs: Any) -> Detection:
        self.detections += 1
        return self.detection_payload

    @property
    def last_call(self) -> dict[str, Any]:
        return self.calls[-1]

    def reset(self) -> None:
        self.calls.clear()


class FailingApi(StubApi):
    def subscriptions(self, **kwargs: Any) -> list[Subscription]:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")


@pytest.fixture
def view(qtbot) -> SubscriptionsView:
    widget = SubscriptionsView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()
    return widget


def api_of(view: SubscriptionsView) -> StubApi:
    return view._api


def cards(view: SubscriptionsView) -> list[SubscriptionCard]:
    return view.findChildren(SubscriptionCard)


def yes(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


def no(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)


# ─── Renewal wording ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (5, "Renews in 5 days"),
        (1, "Renews tomorrow"),
        (0, "Renews today"),
        (-1, "Overdue by 1 day"),
        (-4, "Overdue by 4 days"),
    ],
)
def test_renewal_wording(qtbot, days: int, expected: str) -> None:
    """Working out "in 3 days" from a date is work the interface should do."""
    card = SubscriptionCard(subscription(days=days), currency="BDT")
    qtbot.addWidget(card)

    assert card.renewal_text().startswith(expected)


def test_a_paused_subscription_says_it_would_renew(qtbot) -> None:
    card = SubscriptionCard(subscription(status="paused"), currency="BDT")
    qtbot.addWidget(card)

    assert "Paused" in card.renewal_text()
    assert "would renew" in card.renewal_text()


def test_a_cancelled_subscription_shows_no_renewal_date(qtbot) -> None:
    card = SubscriptionCard(subscription(status="cancelled"), currency="BDT")
    qtbot.addWidget(card)

    assert card.renewal_text() == "Cancelled"


# ─── Card state ───────────────────────────────────────────────────────────


def test_an_overdue_active_subscription_is_its_own_state(qtbot) -> None:
    """Not a stored status — the server has no value for it, so the card derives it."""
    card = SubscriptionCard(subscription(days=-3), currency="BDT")
    qtbot.addWidget(card)

    assert card.property("state") == "overdue"
    assert card._badge_text() == "Overdue"


def test_a_healthy_subscription_is_active(qtbot) -> None:
    card = SubscriptionCard(subscription(days=5), currency="BDT")
    qtbot.addWidget(card)

    assert card.property("state") == "active"


def test_an_overdue_paused_subscription_is_still_just_paused(qtbot) -> None:
    """Paused means not being charged, so it cannot be overdue."""
    card = SubscriptionCard(subscription(status="paused", days=-30), currency="BDT")
    qtbot.addWidget(card)

    assert card.property("state") == "paused"


def test_a_cancelled_subscription_cannot_be_renewed(qtbot) -> None:
    """The server refuses it, so the button is not offered."""
    card = SubscriptionCard(subscription(status="cancelled"), currency="BDT")
    qtbot.addWidget(card)

    assert not card.renew_button.isEnabled()


def test_the_card_shows_the_monthly_equivalent(qtbot) -> None:
    card = SubscriptionCard(subscription(amount="6000.00", cycle="yearly"), currency="BDT")
    qtbot.addWidget(card)

    cost = card.findChild(type(card.renewal_label), "SubscriptionCost")
    assert "500.00 BDT/month" in cost.text()


def test_a_card_without_a_category_omits_it(qtbot) -> None:
    card = SubscriptionCard(subscription(category=None), currency="BDT")
    qtbot.addWidget(card)

    assert card.findChild(type(card.renewal_label), "SubscriptionCategory") is None


def test_a_card_emits_its_id_for_each_action(qtbot) -> None:
    card = SubscriptionCard(subscription(id=7), currency="BDT")
    qtbot.addWidget(card)
    seen: dict[str, list[int]] = {"edit": [], "delete": [], "renew": []}
    card.edit_requested.connect(seen["edit"].append)
    card.delete_requested.connect(seen["delete"].append)
    card.renew_requested.connect(seen["renew"].append)

    card.edit_button.click()
    card.delete_button.click()
    card.renew_button.click()

    assert seen == {"edit": [7], "delete": [7], "renew": [7]}


# ─── The screen ───────────────────────────────────────────────────────────


def test_opening_the_view_loads_subscriptions(view: SubscriptionsView) -> None:
    assert len(api_of(view).calls) == 1
    assert len(cards(view)) == 1
    assert view._pages.currentIndex() == CARDS_PAGE


def test_reopening_the_section_fetches_current_data(view: SubscriptionsView) -> None:
    """The defect this replaced: these tests used to assert the opposite.

    A section that fetched once and never again showed whatever was true the
    first time it was opened. That is wrong for every screen here, because they
    all describe one account from different angles — a transaction added on one
    changes what the others should say, and none of them know it happened.

    What is *not* refetched is the one-off lookups: `load_once` still only
    fetches the category and payment-method lists once.
    """
    before = len(api_of(view).calls)

    view.load_once("BDT")
    view.reload()

    assert len(api_of(view).calls) == before + 1


def test_the_summary_comes_from_the_server_not_the_cards(qtbot) -> None:
    """It must reflect every active subscription, not just the filtered ones."""
    widget = SubscriptionsView(
        StubApi([subscription()], summary(monthly="1234.00", yearly="14808.00", active=3))
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.monthly_total.text() == "1,234.00 BDT"
    assert widget.yearly_total.text() == "14,808.00 BDT"
    assert widget.active_total.text() == "3"


def test_the_summary_mentions_paused_subscriptions(qtbot) -> None:
    widget = SubscriptionsView(StubApi([subscription()], summary(active=2, paused=1)))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.active_total.text() == "2 · 1 paused"


def test_the_summary_names_the_next_renewal(qtbot) -> None:
    upcoming = subscription(name="Spotify", next_date="2026-04-02")
    widget = SubscriptionsView(StubApi([subscription()], summary(upcoming=upcoming)))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert "Spotify" in widget.next_renewal.text()
    assert "02 Apr" in widget.next_renewal.text()


def test_no_upcoming_renewal_shows_a_dash(qtbot) -> None:
    widget = SubscriptionsView(StubApi([], summary(active=0, monthly="0.00", yearly="0.00")))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.next_renewal.text() == "—"


# ─── Filters ──────────────────────────────────────────────────────────────


def test_filtering_by_status(view: SubscriptionsView) -> None:
    api_of(view).reset()

    view.status_filter.setCurrentIndex(view.status_filter.findData("paused"))

    assert api_of(view).last_call["status"] == "paused"


def test_filtering_by_category(view: SubscriptionsView) -> None:
    api_of(view).reset()

    view.category_filter.setCurrentIndex(view.category_filter.findData(SUBS_CATEGORY.id))

    assert api_of(view).last_call["category_id"] == SUBS_CATEGORY.id


def test_due_soon_sends_a_seven_day_window(view: SubscriptionsView) -> None:
    api_of(view).reset()

    view.due_soon_only.setChecked(True)

    assert api_of(view).last_call["due_within_days"] == 7


def test_no_filters_by_default(view: SubscriptionsView) -> None:
    call = api_of(view).last_call

    assert call["status"] is None
    assert call["category_id"] is None
    assert call["due_within_days"] is None


# ─── Empty and error states ───────────────────────────────────────────────


def test_nothing_tracked_says_so(qtbot) -> None:
    widget = SubscriptionsView(StubApi([]))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget._pages.currentIndex() == EMPTY_PAGE
    assert widget.empty_title.text() == "Nothing tracked yet"


def test_no_matches_is_a_different_message(qtbot) -> None:
    widget = SubscriptionsView(StubApi([]))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    widget.due_soon_only.setChecked(True)

    assert widget.empty_title.text() == "Nothing matches"


def test_an_unreachable_backend_is_reported(qtbot) -> None:
    widget = SubscriptionsView(FailingApi())
    qtbot.addWidget(widget)

    widget.load_once("BDT")
    widget.reload()

    widget.reload()

    assert "Cannot reach" in widget.banner.text()
    assert cards(widget) == []


# ─── Actions ──────────────────────────────────────────────────────────────


def test_renewing_asks_first(view: SubscriptionsView, monkeypatch) -> None:
    """It moves the billing date, and a double-click would skip a month silently."""
    no(monkeypatch)

    view.renew_subscription(1)

    assert api_of(view).renewed == []


def test_confirming_a_renewal_calls_the_api_and_reloads(
    view: SubscriptionsView, monkeypatch
) -> None:
    yes(monkeypatch)
    api_of(view).reset()

    view.renew_subscription(1)

    assert api_of(view).renewed == [1]
    assert len(api_of(view).calls) == 1


def test_deleting_asks_first(view: SubscriptionsView, monkeypatch) -> None:
    no(monkeypatch)

    view.delete_subscription(1)

    assert api_of(view).deleted == []


def test_confirming_deletes(view: SubscriptionsView, monkeypatch) -> None:
    yes(monkeypatch)

    view.delete_subscription(1)

    assert api_of(view).deleted == [1]


def test_acting_on_an_unknown_id_does_nothing(view: SubscriptionsView, monkeypatch) -> None:
    yes(monkeypatch)

    view.renew_subscription(999)
    view.delete_subscription(999)
    view.edit_subscription(999)

    assert api_of(view).renewed == []
    assert api_of(view).deleted == []


# ─── The dialog ───────────────────────────────────────────────────────────


def make_dialog(qtbot, **kwargs) -> tuple[SubscriptionDialog, list]:
    saved: list = []
    dialog = SubscriptionDialog(
        list(CATEGORIES),
        save=kwargs.pop("save", saved.append),
        today=kwargs.pop("today", date(2026, 3, 15)),
        **kwargs,
    )
    qtbot.addWidget(dialog)
    return dialog, saved


def test_the_dialog_has_no_next_billing_date_field(qtbot) -> None:
    """It is derived. Offering it would invite three fields that contradict."""
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("Netflix")
    dialog.amount_field.input.setText("499.00")

    dialog.submit()

    assert "next_billing_date" not in saved[0]


def test_the_dialog_sends_strings_and_iso_dates(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("Netflix")
    dialog.amount_field.input.setText("499")

    dialog.submit()

    assert saved[0]["amount"] == "499.00"
    assert saved[0]["start_date"] == "2026-03-15"
    assert saved[0]["billing_cycle"] == "monthly"


def test_a_category_is_optional_in_the_dialog(qtbot) -> None:
    """ "No category" is a real choice, not a placeholder."""
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("Netflix")
    dialog.amount_field.input.setText("499.00")

    dialog.submit()

    assert saved[0]["category_id"] is None


def test_a_blank_name_is_refused_before_any_request(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText("499.00")

    dialog.submit()

    assert saved == []
    assert "name" in dialog.banner.text().lower()


@pytest.mark.parametrize("text", ["", "0", "-5", "abc", "10.005"])
def test_an_unusable_amount_is_refused(qtbot, text: str) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("Netflix")
    dialog.amount_field.input.setText(text)

    dialog.submit()

    assert saved == []


def test_the_end_date_picker_is_hidden_until_wanted(qtbot) -> None:
    """A date editor cannot be empty, so a checkbox is what expresses "no end"."""
    dialog, _ = make_dialog(qtbot)

    assert not dialog.end_row.isVisible()

    dialog.has_end_date.setChecked(True)
    assert dialog.end_row.isVisibleTo(dialog)


def test_no_end_date_is_sent_as_null(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("Netflix")
    dialog.amount_field.input.setText("499.00")

    dialog.submit()

    assert saved[0]["end_date"] is None


def test_an_end_date_before_the_start_is_caught(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("Netflix")
    dialog.amount_field.input.setText("499.00")
    dialog.has_end_date.setChecked(True)
    dialog.end_edit.setDate(QDate(2020, 1, 1))

    dialog.submit()

    assert saved == []
    assert "before the first charge" in dialog.banner.text()


def test_the_dialog_stays_open_when_the_server_refuses(qtbot) -> None:
    def refuse(payload):
        raise ApiError("That category was not found.")

    dialog, _ = make_dialog(qtbot, save=refuse)
    dialog.name_field.input.setText("Netflix")
    dialog.amount_field.input.setText("499.00")

    dialog.submit()

    assert dialog.result() != SubscriptionDialog.DialogCode.Accepted
    assert "not found" in dialog.banner.text()
    assert dialog.name_field.text() == "Netflix"


def test_editing_fills_the_form(qtbot) -> None:
    existing = subscription(name="Spotify", amount="299.00", cycle="yearly", category=SUBS_CATEGORY)

    dialog, _ = make_dialog(qtbot, subscription=existing)

    assert dialog.name_field.text() == "Spotify"
    assert dialog.amount_field.text() == "299.00"
    assert dialog.cycle_box.currentData() == "yearly"
    assert dialog.category_box.currentData() == SUBS_CATEGORY.id
    assert dialog.subscription_id == existing.id


def test_editing_shows_an_existing_end_date(qtbot) -> None:
    existing = subscription(end_date="2027-01-31")

    dialog, _ = make_dialog(qtbot, subscription=existing)

    assert dialog.has_end_date.isChecked()
    assert dialog.end_edit.date() == QDate(2027, 1, 31)


def test_editing_keeps_a_retired_category(qtbot) -> None:
    retired = Category(id=9, name="Old", category_type="expense", is_active=False)
    dialog, _ = make_dialog(qtbot, subscription=subscription(category=retired))

    assert dialog.category_box.currentData() == retired.id
    assert "retired" in dialog.category_box.currentText()


def test_adding_reloads_the_list(view: SubscriptionsView, monkeypatch) -> None:
    monkeypatch.setattr(SubscriptionDialog, "exec", lambda self: 1)
    api_of(view).reset()

    view.add_subscription()

    assert len(api_of(view).calls) == 1


# ─── Detection ────────────────────────────────────────────────────────────


def found(name: str = "Netflix") -> Candidate:
    return Candidate(
        name=name,
        amount=Decimal("499.00"),
        billing_cycle="monthly",
        confidence="high",
        evidence="5 charges of 499.00, exactly 30 days apart.",
        occurrences=5,
        first_seen=date(2026, 1, 5),
        last_seen=date(2026, 5, 5),
        median_interval_days=30,
        interval_spread_days=0,
        next_expected=date(2026, 6, 4),
        transaction_ids=(1, 2, 3, 4, 5),
        category_id=None,
    )


def test_finding_subscriptions_searches_history(view: SubscriptionsView, monkeypatch) -> None:
    from client.widgets.detection_dialog import DetectionDialog

    monkeypatch.setattr(DetectionDialog, "exec", lambda self: 1)

    view.find_subscriptions()

    assert api_of(view).detections == 1


def test_searching_alone_creates_nothing(view: SubscriptionsView, monkeypatch) -> None:
    """ADR-007: detection proposes. Opening the review must not add anything."""
    from client.widgets.detection_dialog import DetectionDialog

    api_of(view).detection_payload = Detection(
        searched_from=date(2025, 6, 15),
        searched_to=date(2026, 6, 15),
        candidates=(found(),),
    )
    monkeypatch.setattr(DetectionDialog, "exec", lambda self: 1)

    view.find_subscriptions()

    assert api_of(view).created == []


def test_the_list_only_reloads_if_something_was_tracked(
    view: SubscriptionsView, monkeypatch
) -> None:
    """Nothing changed, so refetching would be waste."""
    from client.widgets.detection_dialog import DetectionDialog

    monkeypatch.setattr(DetectionDialog, "exec", lambda self: 1)
    api_of(view).reset()

    view.find_subscriptions()

    assert api_of(view).calls == []


def test_a_failed_search_is_reported(qtbot) -> None:
    class CannotDetect(StubApi):
        def detect_subscriptions(self, **kwargs: Any) -> Detection:
            raise ApiError("Cannot reach the FinSight backend. Is it running?")

    widget = SubscriptionsView(CannotDetect())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    widget.find_subscriptions()

    assert "Cannot reach" in widget.banner.text()
