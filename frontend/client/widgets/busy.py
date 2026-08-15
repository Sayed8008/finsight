"""Saying that the application is working, when it is about to stop responding.

Every request in this client is synchronous (ADR-002's counterpart on this side
of the wire): the call blocks until it returns. Against localhost that is a few
milliseconds and imperceptible, which is why it has never mattered. Import and
export are the first requests bounded by *file size* rather than page size, so
they are the first that can take long enough to look like a hang.

The honest fix would be a worker thread. That is a real change — every view
would need to handle a reply arriving after the user had moved on — and it is
not what this phase is for. What this does instead is tell the truth: the
window is about to freeze, here is why, and here is a cursor that says so.

**The order matters, and is the whole trick.** A blocked event loop paints
nothing, so a message set immediately before a blocking call would appear only
once the call had finished — which is worse than useless, since it would say
"Working…" at the exact moment the work was over. `processEvents()` is called
once, deliberately, to flush that paint before the loop stops turning.

**Which is also why the triggering controls are disabled.** `processEvents()`
delivers whatever is queued, including a second click on the button that
started this. Handing that to the same handler again would run two imports.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget

#: What to say when the caller has nothing more specific.
DEFAULT_MESSAGE = "Working…"


@contextmanager
def working(
    *,
    banner: object | None = None,
    message: str = DEFAULT_MESSAGE,
    disable: Sequence[QWidget] = (),
) -> Iterator[None]:
    """Show that a blocking call is in progress, and restore afterwards.

    `banner` is anything with `show_info` — a `MessageBanner` in practice, left
    untyped so this module does not have to import the widget it decorates.

    Restoration happens in a `finally`, because the interesting case is the one
    where the request raises: a wait cursor left on screen after a failed
    request is a window that looks permanently busy.
    """
    QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

    for widget in disable:
        widget.setEnabled(False)

    if banner is not None and hasattr(banner, "show_info"):
        banner.show_info(message)

    # Once, and before the work. See the module docstring: this is the only
    # reason any of the above is visible at all.
    QApplication.processEvents()

    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()
        for widget in disable:
            widget.setEnabled(True)


def is_busy() -> bool:
    """Whether a wait cursor is currently in force.

    Exists for tests. Asserting on `QApplication.overrideCursor()` directly
    works, but reads as Qt trivia rather than as "the window said it was
    working", which is the thing being checked.
    """
    return QApplication.overrideCursor() is not None
