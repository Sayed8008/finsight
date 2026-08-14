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
