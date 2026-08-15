"""Short transitions, and the two rules that keep them from becoming a problem.

**They never block.** Every animation here is a Qt property animation driven by
the event loop. Nothing sleeps, nothing calls `processEvents`, and a widget
stays clickable while it fades — an animation that has to finish before the
user may act is a delay wearing a costume.

**They are off under test.** A half-finished fade means a widget grabbed at 40%
opacity and an assertion that fails once in every twenty runs. Layout defects
here are found by rendering and looking (ADR-012), which only works if what is
rendered is settled. `conftest` sets `FINSIGHT_NO_ANIMATIONS`, and offscreen
rendering disables them too — the switch is explicit rather than inferred from
the platform, because this project's own tests run against a real display on a
developer machine and would otherwise animate exactly where it hurts most.

The durations are short on purpose. Anything past about 200ms on a desktop
application stops reading as polish and starts reading as lag.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

#: A content area changing to a different screen. The longest here, because it
#: is the largest change on screen and the only one the eye needs to follow.
PAGE_MS = 160

#: A panel redrawing with new figures — a filter changed, a refresh landed.
PANEL_MS = 130

#: A small element arriving, such as a badge.
CHIP_MS = 120


#: Set by the test suite. Any non-empty value turns transitions off.
DISABLE_ENV = "FINSIGHT_NO_ANIMATIONS"


def animations_enabled() -> bool:
    """Whether transitions should actually run.

    False under test and offscreen, so what is asserted against is a finished
    widget rather than whatever opacity the animation happened to be at.
    """
    if os.environ.get(DISABLE_ENV):
        return False
    return os.environ.get("QT_QPA_PLATFORM") != "offscreen"


def fade_in(widget: QWidget, duration_ms: int = PANEL_MS) -> QPropertyAnimation | None:
    """Fade `widget` from transparent to opaque, returning the animation.

    The opacity effect is removed when the fade finishes. Leaving one attached
    is not free: every subsequent repaint of that widget is routed through an
    offscreen pixmap, which on a chart is the difference between a redraw
    nobody notices and one they do.

    Returns None when animations are disabled, so a caller can tell the
    difference between "ran" and "skipped" without inspecting the environment.
    """
    if not animations_enabled() or not widget.isVisible():
        return None

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration_ms)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    # Out, not in-out: the change should appear to arrive quickly and settle,
    # rather than easing in from nothing and reading as slow to start.
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def done() -> None:
        # `setGraphicsEffect(None)` deletes the effect Qt owns, so the widget
        # is left exactly as it was before the fade.
        widget.setGraphicsEffect(None)

    animation.finished.connect(done)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation
