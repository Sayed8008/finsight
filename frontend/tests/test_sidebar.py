"""Tests for the sidebar navigation widget."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QPushButton

from client.main import load_stylesheet
from client.widgets.sidebar import NAV_ITEMS, Sidebar

pytestmark = pytest.mark.gui


def test_every_nav_item_is_visible(qtbot) -> None:
    """Regression: the list was sized by its layout and clipped the last item.

    Placed in a layout with a stretch beneath it, QListWidget was given a
    height smaller than its contents, scrolling "Settings" out of view.
    """
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    last_row = len(NAV_ITEMS) - 1
    last_item_bottom = sidebar._list.visualItemRect(sidebar._list.item(last_row)).bottom()

    assert last_item_bottom <= sidebar._list.viewport().height()


def test_navigation_emits_the_selected_key(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    with qtbot.waitSignal(sidebar.navigated) as blocker:
        sidebar._list.setCurrentRow(2)

    assert blocker.args == [NAV_ITEMS[2].key]


def test_dashboard_is_selected_by_default(qtbot) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    assert sidebar.current_key() == "dashboard"


@pytest.mark.parametrize(
    ("online", "expected"),
    [(True, "Connected"), (False, "Backend offline")],
)
def test_backend_status_text(qtbot, online: bool, expected: str) -> None:
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    sidebar.set_backend_status(online=online)

    assert sidebar._status.text() == expected


# ─── Sign out is an action, and looks like one ────────────────────────────
#
# Reported from manual testing as "visually poor / does not appear to sign out".
# It was a bare blue label directly beneath the email — indistinguishable from
# the two lines of account text above it, and nothing about it said it could be
# pressed.


def test_sign_out_is_a_button(qtbot) -> None:
    bar = Sidebar()
    qtbot.addWidget(bar)

    buttons = bar.findChildren(QPushButton, "SignOutButton")

    assert len(buttons) == 1
    assert buttons[0].text() == "Sign out"


def test_sign_out_asks_the_shell_rather_than_acting(qtbot) -> None:
    """Ending a session is the shell's job, not a widget's."""
    bar = Sidebar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.sign_out_requested, timeout=500):
        bar._sign_out_button.click()


def test_sign_out_is_drawn_as_a_control(qtbot) -> None:
    """A border is the whole difference between a label and something that can
    be pressed, and only the pixels distinguish them (ADR-022, ADR-024)."""
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(load_stylesheet())
    try:
        bar = Sidebar()
        qtbot.addWidget(bar)
        bar.set_user("Md. Abu Sayed", "sayed@example.com")
        bar.show()
        image = bar._sign_out_button.grab().toImage()
        edge = image.pixelColor(0, image.height() // 2)
    finally:
        app.setStyleSheet(previous)

    assert edge == QColor("#cdd2d9"), "the sign out control has no visible border"
