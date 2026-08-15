"""Tests for the budgets screen, its cards and its dialog.

The theme running through these: the client displays what the server computed
and decides nothing about it. A card must not work out its own status, and the
dialog must not offer a category the server would refuse.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QCheckBox

from client.api.client import ApiError
from client.api.dto import Budget, Category
from client.main import load_stylesheet
from client.views.budgets_view import CARDS_PAGE, EMPTY_PAGE, BudgetsView
from client.widgets.budget_card import BudgetCard
from client.widgets.budget_dialog import BudgetDialog, month_bounds

pytestmark = pytest.mark.gui

CATEGORIES = [
    Category(id=1, name="Salary", category_type="income", color="#1a7f4b"),
    Category(id=2, name="Food", category_type="expense", color="#c4472f"),
    Category(id=3, name="Transport", category_type="expense", color="#d9782e"),
]
FOOD = CATEGORIES[1]


def budget(
    id: int = 1,
    amount: str = "5000.00",
    spent: str = "1000.00",
    status: str = "healthy",
    category: Category = FOOD,
    days_remaining: int | None = 16,
    is_current: bool = True,
    start: str = "2026-03-01",
    end: str = "2026-03-31",
) -> Budget:
    limit = Decimal(amount)
    used = Decimal(spent)
    return Budget(
        id=id,
        category=category,
        amount=limit,
        period_start=date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        spent=used,
        remaining=limit - used,
        percentage_used=(used / limit * 100).quantize(Decimal("0.01")),
        status=status,
        is_current=is_current,
        days_remaining=days_remaining,
    )


class StubApi:
    """Records requests; returns whatever it was told to."""

    def __init__(self, budgets: list[Budget] | None = None) -> None:
        self.rows = budgets if budgets is not None else [budget()]
        self.calls: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[int, dict[str, Any]]] = []
        self.deleted: list[int] = []

    def categories(self, **_: Any) -> list[Category]:
        return list(CATEGORIES)

    def budgets(self, **kwargs: Any) -> list[Budget]:
        self.calls.append(kwargs)
        return list(self.rows)

    def create_budget(self, **fields: Any) -> Budget:
        self.created.append(fields)
        return budget()

    def update_budget(self, budget_id: int, **changes: Any) -> Budget:
        self.updated.append((budget_id, changes))
        return budget()

    def delete_budget(self, budget_id: int) -> None:
        self.deleted.append(budget_id)

    @property
    def last_call(self) -> dict[str, Any]:
        return self.calls[-1]

    def reset(self) -> None:
        self.calls.clear()


class FailingApi(StubApi):
    def budgets(self, **kwargs: Any) -> list[Budget]:
        raise ApiError("Cannot reach the FinSight backend. Is it running?")


@pytest.fixture
def view(qtbot) -> BudgetsView:
    widget = BudgetsView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()
    return widget


def api_of(view: BudgetsView) -> StubApi:
    return view._api


def cards(view: BudgetsView) -> list[BudgetCard]:
    return view.findChildren(BudgetCard)


# ─── The card ─────────────────────────────────────────────────────────────


def test_a_card_shows_the_figures_it_was_given(qtbot) -> None:
    card = BudgetCard(budget(amount="5000.00", spent="1250.50"), currency="BDT")
    qtbot.addWidget(card)

    assert (
        "1,250.50 BDT of 5,000.00 BDT spent"
        in card.findChild(type(card.remaining_label), "BudgetSpent").text()
    )
    assert card.remaining_label.text() == "3,749.50 BDT left"


def test_a_card_uses_the_status_the_server_sent(qtbot) -> None:
    """The client must not re-derive thresholds — that would be a second copy."""
    card = BudgetCard(budget(status="warning"), currency="BDT")
    qtbot.addWidget(card)

    assert card.property("status") == "warning"
    assert card.bar.property("status") == "warning"


def test_an_overspent_card_reads_over_by_rather_than_minus_left(qtbot) -> None:
    card = BudgetCard(budget(amount="1000.00", spent="1250.00", status="exceeded"), currency="BDT")
    qtbot.addWidget(card)

    assert card.remaining_label.text() == "over by 250.00 BDT"
    assert "-" not in card.remaining_label.text()


def test_the_bar_is_capped_at_a_hundred_but_the_number_is_not(qtbot) -> None:
    """A progress bar cannot render 150%, so the real figure is printed beside it."""
    over = budget(amount="1000.00", spent="1500.00", status="exceeded")
    card = BudgetCard(over, currency="BDT")
    qtbot.addWidget(card)

    assert card.bar.value() == 100
    assert over.percentage_used == Decimal("150.00")


def test_a_card_shows_days_remaining_while_running(qtbot) -> None:
    card = BudgetCard(budget(days_remaining=16), currency="BDT")
    qtbot.addWidget(card)

    assert "16 days left" in card._period_text()


def test_one_day_left_is_not_pluralised(qtbot) -> None:
    card = BudgetCard(budget(days_remaining=1), currency="BDT")
    qtbot.addWidget(card)

    assert "1 day left" in card._period_text()


def test_a_finished_budget_says_so_instead_of_showing_days(qtbot) -> None:
    card = BudgetCard(budget(days_remaining=None, is_current=False), currency="BDT")
    qtbot.addWidget(card)

    assert "ended" in card._period_text()
    assert "left" not in card._period_text()


def test_a_card_emits_its_id_when_asked_to_edit_or_delete(qtbot) -> None:
    card = BudgetCard(budget(id=42), currency="BDT")
    qtbot.addWidget(card)
    edits: list[int] = []
    deletes: list[int] = []
    card.edit_requested.connect(edits.append)
    card.delete_requested.connect(deletes.append)

    card.edit_button.click()
    card.delete_button.click()

    assert edits == [42]
    assert deletes == [42]


# ─── Loading and rendering ────────────────────────────────────────────────


def test_opening_the_view_requests_budgets(view: BudgetsView) -> None:
    assert len(api_of(view).calls) == 1


def test_reopening_the_section_fetches_current_data(view: BudgetsView) -> None:
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


def test_one_card_per_budget(qtbot) -> None:
    widget = BudgetsView(StubApi([budget(id=1), budget(id=2), budget(id=3)]))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert len(cards(widget)) == 3
    assert widget._pages.currentIndex() == CARDS_PAGE


def test_reloading_replaces_cards_rather_than_stacking_them(view: BudgetsView) -> None:
    """A rebuild that appended would double the list on every refresh."""
    view.reload()
    view.reload()

    assert len(cards(view)) == 1


def test_the_count_is_shown_and_pluralised(qtbot) -> None:
    one = BudgetsView(StubApi([budget()]))
    qtbot.addWidget(one)
    one.load_once("BDT")
    one.reload()
    assert one.count_label.text() == "1 budget"

    many = BudgetsView(StubApi([budget(id=1), budget(id=2)]))
    qtbot.addWidget(many)
    many.load_once("BDT")
    many.reload()
    assert many.count_label.text() == "2 budgets"


# ─── The summary strip ────────────────────────────────────────────────────


def test_the_summary_totals_the_cards_on_screen(qtbot) -> None:
    widget = BudgetsView(
        StubApi(
            [
                budget(id=1, amount="5000.00", spent="1000.00"),
                budget(id=2, amount="3000.00", spent="2500.00"),
            ]
        )
    )
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.total_budgeted.text() == "8,000.00 BDT"
    assert widget.total_spent.text() == "3,500.00 BDT"
    assert widget.total_remaining.text() == "4,500.00 BDT"


def test_summary_totals_stay_exact(qtbot) -> None:
    """Ten lots of 0.10 must total 1.00 — with floats they would not (ADR-003)."""
    widget = BudgetsView(StubApi([budget(id=i, amount="0.10", spent="0.00") for i in range(10)]))
    qtbot.addWidget(widget)
    widget.load_once("")
    widget.reload()

    assert widget.total_budgeted.text() == "1.00"


def test_an_overspent_total_is_flagged(qtbot) -> None:
    widget = BudgetsView(StubApi([budget(amount="1000.00", spent="1500.00", status="exceeded")]))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget.total_remaining.text() == "-500.00 BDT"
    assert widget.total_remaining.property("status") == "exceeded"


def test_the_summary_hides_when_there_is_nothing_to_total(qtbot) -> None:
    widget = BudgetsView(StubApi([]))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert not widget.summary.isVisible()


# ─── Filters ──────────────────────────────────────────────────────────────


def test_the_category_filter_offers_only_expense_categories(view: BudgetsView) -> None:
    """A budget cannot be set on an income category, so filtering by one is useless."""
    labels = [view.category_filter.itemText(i) for i in range(view.category_filter.count())]

    assert labels == ["All categories", "Food", "Transport"]


def test_choosing_a_category_filters_on_the_server(view: BudgetsView) -> None:
    api_of(view).reset()

    view.category_filter.setCurrentIndex(view.category_filter.findData(FOOD.id))

    assert api_of(view).last_call["category_id"] == FOOD.id


def test_current_only_is_sent_to_the_server(view: BudgetsView) -> None:
    api_of(view).reset()

    view.current_only.setChecked(True)

    assert api_of(view).last_call["current_only"] is True


def test_no_filters_are_sent_by_default(view: BudgetsView) -> None:
    call = api_of(view).last_call

    assert call["category_id"] is None
    assert call["current_only"] is False


# ─── Empty and error states ───────────────────────────────────────────────


def test_no_budgets_says_so(qtbot) -> None:
    widget = BudgetsView(StubApi([]))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    assert widget._pages.currentIndex() == EMPTY_PAGE
    assert widget.empty_title.text() == "No budgets yet"


def test_no_matches_is_a_different_message_from_no_data(qtbot) -> None:
    widget = BudgetsView(StubApi([]))
    qtbot.addWidget(widget)
    widget.load_once("BDT")
    widget.reload()

    widget.current_only.setChecked(True)

    assert widget.empty_title.text() == "No budgets match"
    assert "filters" in widget.empty_message.text()


def test_an_unreachable_backend_is_reported_not_crashed(qtbot) -> None:
    widget = BudgetsView(FailingApi())
    qtbot.addWidget(widget)

    widget.load_once("BDT")
    widget.reload()

    widget.reload()

    assert "Cannot reach" in widget.banner.text()
    assert cards(widget) == []


# ─── Deleting ─────────────────────────────────────────────────────────────


def test_deleting_asks_first_and_does_nothing_if_declined(view: BudgetsView, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)

    view.delete_budget(1)

    assert api_of(view).deleted == []


def test_confirming_deletes_and_reloads(view: BudgetsView, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    api_of(view).reset()

    view.delete_budget(1)

    assert api_of(view).deleted == [1]
    assert len(api_of(view).calls) == 1


def test_deleting_an_unknown_id_does_nothing(view: BudgetsView) -> None:
    """A card can be clicked just as a refresh removes the budget behind it."""
    view.delete_budget(999)

    assert api_of(view).deleted == []


# ─── The dialog ───────────────────────────────────────────────────────────


def make_dialog(qtbot, **kwargs) -> tuple[BudgetDialog, list]:
    saved: list = []
    dialog = BudgetDialog(
        list(CATEGORIES),
        save=kwargs.pop("save", saved.append),
        today=kwargs.pop("today", date(2026, 3, 15)),
        **kwargs,
    )
    qtbot.addWidget(dialog)
    return dialog, saved


def test_the_dialog_offers_only_expense_categories(qtbot) -> None:
    """Mirrors the server rule, so the refused request cannot be built."""
    dialog, _ = make_dialog(qtbot)

    labels = [dialog.category_box.itemText(i) for i in range(dialog.category_box.count())]
    assert labels == ["Food", "Transport"]


def test_the_dialog_defaults_to_the_current_month(qtbot) -> None:
    dialog, _ = make_dialog(qtbot, today=date(2026, 3, 15))

    assert dialog.start_edit.date() == QDate(2026, 3, 1)
    assert dialog.end_edit.date() == QDate(2026, 3, 31)


@pytest.mark.parametrize(
    ("today", "expected_end"),
    [
        (date(2026, 2, 10), date(2026, 2, 28)),
        (date(2028, 2, 10), date(2028, 2, 29)),  # leap year
        (date(2026, 4, 10), date(2026, 4, 30)),
        (date(2026, 12, 10), date(2026, 12, 31)),
    ],
)
def test_month_bounds_handles_month_lengths(today: date, expected_end: date) -> None:
    start, end = month_bounds(today)

    assert start == date(today.year, today.month, 1)
    assert end == expected_end


def test_use_this_month_fills_the_period(qtbot) -> None:
    dialog, _ = make_dialog(qtbot, today=date(2026, 7, 20))
    dialog.start_edit.setDate(QDate(2020, 1, 1))

    dialog.use_this_month()

    assert dialog.start_edit.date() == QDate(2026, 7, 1)
    assert dialog.end_edit.date() == QDate(2026, 7, 31)


def test_the_dialog_sends_the_amount_as_a_string(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText("5000")

    dialog.submit()

    assert saved[0]["amount"] == "5000.00"
    assert isinstance(saved[0]["amount"], str)


def test_the_dialog_sends_iso_dates(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText("100.00")

    dialog.submit()

    assert saved[0]["period_start"] == "2026-03-01"
    assert saved[0]["period_end"] == "2026-03-31"


@pytest.mark.parametrize("text", ["", "0", "-5", "abc", "10.005", "1000000000000.00"])
def test_an_unusable_limit_is_refused_before_any_request(qtbot, text: str) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText(text)

    dialog.submit()

    assert saved == []
    assert "limit" in dialog.banner.text().lower()


def test_a_backwards_period_is_caught_before_any_request(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.amount_field.input.setText("100.00")
    dialog.start_edit.setDate(QDate(2026, 3, 31))
    dialog.end_edit.setDate(QDate(2026, 3, 1))

    dialog.submit()

    assert saved == []
    assert "end before it starts" in dialog.banner.text()


def test_the_dialog_stays_open_when_the_period_overlaps(qtbot) -> None:
    """The commonest refusal. What was typed must survive it."""

    def refuse(payload):
        raise ApiError("A budget for that category already covers part of this period.")

    dialog, _ = make_dialog(qtbot, save=refuse)
    dialog.amount_field.input.setText("5000.00")

    dialog.submit()

    assert dialog.result() != BudgetDialog.DialogCode.Accepted
    assert "already covers" in dialog.banner.text()
    assert dialog.amount_field.text() == "5000.00"


def test_editing_fills_the_form(qtbot) -> None:
    existing = budget(amount="7500.00", start="2026-05-01", end="2026-05-31")

    dialog, _ = make_dialog(qtbot, budget=existing)

    assert dialog.amount_field.text() == "7500.00"
    assert dialog.start_edit.date() == QDate(2026, 5, 1)
    assert dialog.category_box.currentData() == FOOD.id
    assert dialog.budget_id == existing.id


def test_editing_keeps_a_retired_category_available(qtbot) -> None:
    retired = Category(id=9, name="Old", category_type="expense", is_active=False)
    dialog, _ = make_dialog(qtbot, budget=budget(category=retired))

    assert dialog.category_box.currentData() == retired.id
    assert "retired" in dialog.category_box.currentText()


def test_adding_a_budget_reloads_the_list(view: BudgetsView, monkeypatch) -> None:
    monkeypatch.setattr(BudgetDialog, "exec", lambda self: 1)
    api_of(view).reset()

    view.add_budget()

    assert len(api_of(view).calls) == 1


# ─── Rendering ────────────────────────────────────────────────────────────


def test_the_filter_checkbox_actually_has_a_box(qtbot) -> None:
    """Found by rendering (ADR-012), like the invisible button before it.

    Qt switches a widget to stylesheet rendering as soon as any rule matches
    it, then draws only what the sheet describes. Styling the label alone left
    a checkbox with no box — clickable, checkable and invisible. Only the
    pixels show it, so this counts the drawn colours where the indicator sits.
    """
    stylesheet = load_stylesheet()
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(stylesheet)
    try:
        box = QCheckBox("Only budgets running now")
        box.setObjectName("FilterCheck")
        qtbot.addWidget(box)
        box.show()
        unchecked = box.grab().toImage()

        box.setChecked(True)
        checked = box.grab().toImage()
    finally:
        app.setStyleSheet(previous)

    def indicator_colours(image) -> set[str]:
        return {
            image.pixelColor(x, y).name()
            for x in range(min(18, image.width()))
            for y in range(image.height())
        }

    # The unchecked box is a white fill with a grey border.
    assert "#cdd2d9" in indicator_colours(unchecked), "the checkbox has no visible border"
    # Checking it fills the box with the primary blue.
    assert "#1a56c4" in indicator_colours(checked), "checking the box shows nothing"


def test_the_card_buttons_are_actually_painted(qtbot) -> None:
    """ADR-022 again: `#BudgetCard QWidget` would match these and blank them.

    The Delete button sits on a white card and is styled white with a red
    border, so "not painted" and "painted correctly" both look white in a
    geometry test. Only the border pixel distinguishes them.
    """
    stylesheet = load_stylesheet()
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(stylesheet)
    try:
        card = BudgetCard(budget(), currency="BDT")
        qtbot.addWidget(card)
        card.show()
        image = card.delete_button.grab().toImage()
        # Just inside the left edge, where the 1px border is drawn.
        border = image.pixelColor(0, image.height() // 2)
    finally:
        app.setStyleSheet(previous)

    assert image.width() > 0
    assert border == QColor("#f0c2be"), "the danger button lost its border"
