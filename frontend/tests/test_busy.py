"""Tests for saying the application is working.

Every request in this client is synchronous, so a slow one freezes the window.
The point of `working()` is to make sure the window has *said* so before it
stops responding, which is entirely a question of ordering — and ordering is
what these check, by observing the state from inside the blocking call.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from client.widgets.busy import DEFAULT_MESSAGE, is_busy, working
from client.widgets.forms import MessageBanner

pytestmark = pytest.mark.gui


def test_the_cursor_says_the_window_is_busy(qtbot) -> None:
    assert is_busy() is False

    with working():
        assert is_busy() is True

    assert is_busy() is False


def test_the_message_is_showing_before_the_work_starts(qtbot) -> None:
    """The whole trick. A blocked event loop paints nothing, so a message set
    immediately before a blocking call would appear once the call had
    finished — saying "Working…" at the moment the work was over."""
    banner = MessageBanner()
    qtbot.addWidget(banner)

    with working(banner=banner, message="Reading the file…"):
        assert banner.text() == "Reading the file…"
        assert banner.isVisible() is True


def test_a_default_message_is_offered(qtbot) -> None:
    banner = MessageBanner()
    qtbot.addWidget(banner)

    with working(banner=banner):
        assert banner.text() == DEFAULT_MESSAGE


def test_the_triggering_controls_cannot_be_used_twice(qtbot) -> None:
    """`processEvents` delivers whatever is queued, including a second click on
    the button that started this. Handing that to the same handler again would
    run two imports."""
    button = QPushButton("Import")
    qtbot.addWidget(button)

    with working(disable=(button,)):
        assert button.isEnabled() is False

    assert button.isEnabled() is True


def test_everything_is_restored_when_the_work_fails(qtbot) -> None:
    """The interesting case. A wait cursor left behind after a failed request
    is a window that looks permanently busy."""
    button = QPushButton("Export")
    qtbot.addWidget(button)

    with pytest.raises(RuntimeError), working(disable=(button,)):
        raise RuntimeError("the backend went away")

    assert is_busy() is False
    assert button.isEnabled() is True


def test_nesting_restores_one_level_at_a_time(qtbot) -> None:
    """Qt keeps a cursor stack, so an unbalanced restore would leave the
    window busy for the rest of the session."""
    with working():
        with working():
            assert is_busy() is True
        assert is_busy() is True

    assert is_busy() is False


def test_it_works_without_a_banner(qtbot) -> None:
    with working(banner=None):
        assert is_busy() is True


def test_the_window_is_busy_during_a_real_call(qtbot) -> None:
    """Observed from inside the call, which is the only place it is true."""
    seen: list[bool] = []

    def slow_request() -> str:
        seen.append(is_busy())
        return "done"

    with working():
        slow_request()

    assert seen == [True]


def test_the_application_is_left_as_it_was_found(qtbot) -> None:
    before = QApplication.overrideCursor()

    with working():
        pass

    assert QApplication.overrideCursor() == before
