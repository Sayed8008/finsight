"""Fixtures and environment setup for desktop client tests.

Qt needs a display to create widgets. On a machine with no graphical session
(a CI runner, or a plain SSH session) it must be told to render offscreen,
otherwise every GUI test aborts with "could not connect to display".
"""

from __future__ import annotations

import os


def _select_qt_platform() -> None:
    """Use offscreen rendering when there is no display available.

    An explicit QT_QPA_PLATFORM set by the developer is always respected.
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


_select_qt_platform()

import pytest  # noqa: E402  (must follow the platform selection above)


@pytest.fixture
def answer_confirmation():
    """Press a button in the next confirmation dialog that opens.

    Returns a callable: `answer_confirmation(action, "Yes")` runs `action` and
    clicks Yes in the `QMessageBox` it opens, returning the dialog's text so a
    test can check the user was asked about the right record.

    Every confirmation in this application is modal and blocks inside
    `QMessageBox.question`, so the click has to be queued first and delivered
    from the event loop once the dialog is up.

    Tests use this rather than monkeypatching `QMessageBox.question`, because
    the bug these exist to catch *was* in that function's return value: a stub
    returning a `StandardButton` member would have made the broken `is`
    comparison pass and reported a working delete that deleted nothing.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    def answer(action, button: str = "Yes") -> str:
        standard = getattr(QMessageBox.StandardButton, button)
        seen: list[str] = []

        def click() -> None:
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QMessageBox) and widget.isVisible():
                    seen.append(widget.text())
                    widget.button(standard).click()
                    return

        QTimer.singleShot(0, click)
        action()

        assert seen, "no confirmation dialog appeared"
        return seen[0]

    return answer
