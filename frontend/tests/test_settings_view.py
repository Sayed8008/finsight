"""Tests for the settings screen and the category dialog.

Two server rules show up here as things the screen does rather than things the
user discovers by hitting them, and both are what most of these check:

  * there is no delete, only retirement (ADR-020), so retired categories stay
    visible and restorable rather than vanishing;
  * a category's type is fixed once it exists, so the chooser is gone when
    editing rather than present and refused.

The third thing worth checking is invisible on this screen entirely: changing a
category has to reach the pickers on every other screen, which each hold their
own list fetched once.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from client.api.client import ApiError
from client.api.dto import Category, User
from client.main import load_stylesheet
from client.views.settings_view import SettingsView
from client.widgets.category_dialog import PALETTE, CategoryDialog

pytestmark = pytest.mark.gui

USER = User(
    id=1,
    email="sayed@example.com",
    full_name="Md. Abu Sayed",
    currency_code="BDT",
    role="user",
    is_active=True,
)

CATEGORIES = [
    Category(id=1, name="Salary", category_type="income", color="#1a7f4b"),
    Category(id=2, name="Food", category_type="expense", color="#c0392b"),
    Category(id=3, name="Transport", category_type="expense", color="#2b9ab5"),
    Category(id=9, name="Skydiving", category_type="expense", color="#8a4fbd", is_active=False),
]


class StubApi:
    """Records every request, and answers with whatever it was told."""

    def __init__(self, rows: list[Category] | None = None, error: ApiError | None = None) -> None:
        self.rows = rows if rows is not None else CATEGORIES
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[int, dict[str, Any]]] = []

    def categories(self, **kwargs: Any) -> list[Category]:
        if self.error is not None:
            raise self.error
        self.calls.append(kwargs)
        if kwargs.get("include_inactive"):
            return list(self.rows)
        return [row for row in self.rows if row.is_active]

    def create_category(self, **fields: Any) -> Category:
        self.created.append(fields)
        return CATEGORIES[1]

    def update_category(self, category_id: int, **changes: Any) -> Category:
        self.updated.append((category_id, changes))
        return CATEGORIES[1]


@pytest.fixture
def view(qtbot) -> SettingsView:
    widget = SettingsView(StubApi())
    qtbot.addWidget(widget)
    widget.load_once(USER)
    widget.reload()
    return widget


def api_of(view: SettingsView) -> StubApi:
    return view._api


def texts(widget, name: str) -> list[str]:
    return [label.text() for label in widget.findChildren(QLabel, name)]


def buttons(widget, label: str) -> list[QPushButton]:
    return [b for b in widget.findChildren(QPushButton) if b.text() == label]


# ─── The account ──────────────────────────────────────────────────────────


def test_the_account_is_shown(view: SettingsView) -> None:
    assert view.account_name.text() == "Md. Abu Sayed"
    assert view.account_email.text() == "sayed@example.com"
    assert view.account_currency.text() == "BDT"


def test_the_account_fields_are_not_editable(view: SettingsView) -> None:
    """Shown as text rather than as disabled inputs: a greyed-out field asks
    "why can I not change this?" and answers nothing."""
    assert "fixed for now" in " ".join(texts(view, "SettingsNote"))


# ─── Listing categories ───────────────────────────────────────────────────


def test_categories_are_grouped_by_direction(view: SettingsView) -> None:
    assert texts(view, "CategoryGroup") == ["Money out", "Money in"]


def test_only_categories_in_use_are_shown_by_default(view: SettingsView) -> None:
    assert "Skydiving" not in texts(view, "CategoryName")
    assert set(texts(view, "CategoryName")) == {"Food", "Transport", "Salary"}


def test_retired_categories_can_be_brought_into_view(view: SettingsView) -> None:
    """They cannot be deleted (ADR-020), so a screen that hid them would make
    restoring one impossible."""
    view.show_retired.setChecked(True)

    assert "Skydiving" in texts(view, "CategoryName")
    assert texts(view, "CategoryBadge") == ["retired"]


def test_a_retired_category_offers_restore_rather_than_retire(view: SettingsView) -> None:
    view.show_retired.setChecked(True)

    assert len(buttons(view, "Restore")) == 1
    assert len(buttons(view, "Retire")) == 3


def test_retired_categories_sort_below_the_ones_in_use(view: SettingsView) -> None:
    view.show_retired.setChecked(True)

    names = texts(view, "CategoryName")
    assert names.index("Skydiving") > names.index("Transport")


def test_the_count_says_how_many_are_in_use_and_how_many_are_not(view: SettingsView) -> None:
    view.show_retired.setChecked(True)

    assert view.count_label.text() == "3 in use · 1 retired"


def test_an_account_with_no_categories_says_so(qtbot) -> None:
    widget = SettingsView(StubApi(rows=[]))
    qtbot.addWidget(widget)
    widget.load_once(USER)
    widget.reload()

    assert widget.empty_message.isVisible() is False or "No categories" in (
        widget.empty_message.text()
    )
    assert "No categories" in widget.empty_message.text()


def test_a_failed_load_is_not_reported_as_an_empty_account(qtbot) -> None:
    """"You have none" and "we could not fetch them" call for different acts."""
    widget = SettingsView(StubApi(error=ApiError("Cannot reach the FinSight backend.")))
    qtbot.addWidget(widget)
    widget.load_once(USER)
    widget.reload()

    assert "Cannot reach" in widget.banner.text()
    assert "Could not load categories" in widget.empty_message.text()


# ─── Changing categories ──────────────────────────────────────────────────


def test_retiring_asks_first_and_says_it_is_not_a_delete(
    view: SettingsView, monkeypatch
) -> None:
    """Somebody expecting a delete needs to know the history stays put."""
    asked: list[str] = []

    def fake_question(parent, title, text, *args, **kwargs):
        asked.append(text)
        from PySide6.QtWidgets import QMessageBox

        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr("client.views.settings_view.QMessageBox.question", fake_question)

    view.retire_category(CATEGORIES[1])

    assert "not a delete" in asked[0]
    assert api_of(view).updated == []


def test_retiring_deactivates_rather_than_deleting(view: SettingsView, monkeypatch) -> None:
    monkeypatch.setattr(
        "client.views.settings_view.QMessageBox.question",
        lambda *args, **kwargs: __import__(
            "PySide6.QtWidgets", fromlist=["QMessageBox"]
        ).QMessageBox.StandardButton.Yes,
    )

    view.retire_category(CATEGORIES[1])

    assert api_of(view).updated == [(2, {"is_active": False})]


def test_restoring_puts_it_back(view: SettingsView) -> None:
    view.restore_category(CATEGORIES[3])

    assert api_of(view).updated == [(9, {"is_active": True})]


def test_a_change_tells_the_rest_of_the_application(view: SettingsView, qtbot) -> None:
    """Every other screen holds its own category list, fetched once. Without
    this, a new category would be missing from them until a restart."""
    with qtbot.waitSignal(view.categories_changed, timeout=500):
        view.restore_category(CATEGORIES[3])


def test_a_change_says_what_happened(view: SettingsView) -> None:
    view.restore_category(CATEGORIES[3])

    assert "Skydiving is available again" in view.banner.text()


def test_a_failed_change_is_reported_and_changes_nothing(qtbot) -> None:
    api = StubApi()
    widget = SettingsView(api)
    qtbot.addWidget(widget)
    widget.load_once(USER)
    widget.reload()

    def refuse(category_id: int, **changes: Any) -> Category:
        raise ApiError("That category was not found.")

    api.update_category = refuse  # type: ignore[method-assign]
    widget.restore_category(CATEGORIES[3])

    assert "not found" in widget.banner.text()


# ─── The dialog ───────────────────────────────────────────────────────────


def make_dialog(qtbot, category: Category | None = None):
    saved: list[dict[str, Any]] = []
    dialog = CategoryDialog(save=lambda payload: saved.append(payload), category=category)
    qtbot.addWidget(dialog)
    return dialog, saved


def test_a_new_category_asks_which_kind(qtbot) -> None:
    dialog, _ = make_dialog(qtbot)

    assert dialog.type_box is not None
    assert dialog.type_box.currentData() == "expense"


def test_editing_states_the_kind_instead_of_offering_it(qtbot) -> None:
    """Gone rather than disabled. A greyed-out control invites the question and
    answers nothing; a line of text says what it is and moves on."""
    dialog, _ = make_dialog(qtbot, CATEGORIES[1])

    assert dialog.type_box is None
    assert "Money out" in " ".join(texts(dialog, "FieldStatic"))


def test_editing_explains_why_the_kind_is_fixed(qtbot) -> None:
    dialog, _ = make_dialog(qtbot, CATEGORIES[1])

    assert "cannot change" in dialog.subtitle.text()


def test_a_new_category_sends_its_kind_and_colour(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("Skydiving")
    dialog.choose_colour(PALETTE[3])

    dialog.submit()

    assert saved == [
        {"name": "Skydiving", "category_type": "expense", "color": PALETTE[3]}
    ]


def test_an_edit_never_sends_the_kind(qtbot) -> None:
    """It would be a request the server has to refuse, and one nobody meant."""
    dialog, saved = make_dialog(qtbot, CATEGORIES[1])
    dialog.name_field.input.setText("Groceries")

    dialog.submit()

    assert saved == [{"name": "Groceries", "color": "#c0392b"}]


def test_the_existing_colour_starts_selected(qtbot) -> None:
    dialog, _ = make_dialog(qtbot, CATEGORIES[1])

    assert dialog.colour() == "#c0392b"


def test_only_one_colour_is_ever_selected(qtbot) -> None:
    """Qt checkable buttons are independent, so every colour ever clicked would
    otherwise stay looking chosen."""
    dialog, _ = make_dialog(qtbot)

    dialog.choose_colour(PALETTE[2])
    dialog.choose_colour(PALETTE[5])

    chosen = [colour for colour, swatch in dialog._swatches.items() if swatch.isChecked()]
    assert chosen == [PALETTE[5]]


def test_a_blank_name_is_reported_before_a_round_trip(qtbot) -> None:
    """Feedback, not enforcement — the server checks this too (ADR-019)."""
    dialog, saved = make_dialog(qtbot)

    dialog.submit()

    assert saved == []
    assert "needs a name" in dialog.banner.text()


def test_a_name_of_only_spaces_is_not_a_name(qtbot) -> None:
    dialog, saved = make_dialog(qtbot)
    dialog.name_field.input.setText("    ")

    dialog.submit()

    assert saved == []


def test_a_refusal_from_the_server_is_shown_and_keeps_the_dialog_open(qtbot) -> None:
    def refuse(payload: dict[str, Any]) -> None:
        raise ApiError("A category with that name already exists for this type.")

    dialog = CategoryDialog(save=refuse)
    qtbot.addWidget(dialog)
    dialog.name_field.input.setText("Food")

    dialog.submit()

    assert "already exists" in dialog.banner.text()
    assert dialog.result() != CategoryDialog.DialogCode.Accepted


# ─── Painted, not merely present ──────────────────────────────────────────


def test_the_selected_swatch_is_visibly_selected(qtbot) -> None:
    """Selection is the only thing distinguishing fifteen identical circles,
    and it is drawn by a border rule that no geometry test would catch."""
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet())
    try:
        dialog, _ = make_dialog(qtbot)
        dialog.choose_colour(PALETTE[0])
        dialog.show()
        image = dialog._swatches[PALETTE[0]].grab().toImage()
        corner = image.pixelColor(1, image.height() // 2)
    finally:
        app.setStyleSheet(previous)

    assert corner == QColor("#0f1419"), "the chosen colour has no ring around it"


def test_the_add_button_is_actually_painted(qtbot) -> None:
    """ADR-022, again: a dialog-wide QWidget rule would paint it in nothing."""
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet())
    try:
        dialog, _ = make_dialog(qtbot)
        dialog.show()
        image = dialog.save_button.grab().toImage()
        fill = image.pixelColor(6, image.height() // 2)
    finally:
        app.setStyleSheet(previous)

    assert fill == QColor("#1a56c4"), "the primary button is painted in nothing"
