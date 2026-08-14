"""Tests for the sidebar navigation widget."""

from __future__ import annotations

import pytest

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
