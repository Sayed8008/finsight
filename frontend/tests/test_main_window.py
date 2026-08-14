"""Tests for the desktop client's main window.

These use pytest-qt, which provides the `qtbot` fixture: it creates the
QApplication, keeps widgets alive for the duration of a test, and cleans them
up afterwards.

The API client is replaced with a stub so these tests never require a running
backend — they verify interface behaviour, not networking.
"""

from __future__ import annotations

import pytest

from client.api.client import ApiUnavailableError
from client.views.main_window import MainWindow
from client.widgets.sidebar import NAV_ITEMS

pytestmark = pytest.mark.gui


class StubApiOnline:
    def health(self) -> dict[str, str]:
        return {"status": "ok", "service": "finsight-api", "version": "0.1.0"}


class StubApiOffline:
    def health(self) -> dict[str, str]:
        raise ApiUnavailableError("Cannot reach the FinSight backend. Is it running?")


def test_window_creates_a_page_for_every_nav_item(qtbot) -> None:
    window = MainWindow(StubApiOnline())
    qtbot.addWidget(window)

    assert window._pages.count() == len(NAV_ITEMS)


def test_navigation_switches_the_visible_page(qtbot) -> None:
    window = MainWindow(StubApiOnline())
    qtbot.addWidget(window)

    assert window._pages.currentIndex() == 0

    window._show_section("analytics")

    assert window._pages.currentIndex() == window._page_index["analytics"]


def test_backend_check_succeeds_when_api_responds(qtbot) -> None:
    window = MainWindow(StubApiOnline())
    qtbot.addWidget(window)

    assert window.check_backend() is True


def test_backend_check_fails_gracefully_when_api_is_down(qtbot) -> None:
    """An unreachable backend must not crash the client at startup."""
    window = MainWindow(StubApiOffline())
    qtbot.addWidget(window)

    assert window.check_backend() is False
