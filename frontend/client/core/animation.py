"""The application's motion language, in one place.

Every transition in FinSight comes from here, so that the whole interface moves
the same way rather than each screen inventing its own timing. Three durations
and one easing curve cover everything; a widget that wants something else needs
a reason.

Three rules keep the polish from becoming a problem.

**Nothing blocks.** Every animation is a Qt property animation driven by the
event loop. Nothing sleeps, nothing calls `processEvents`, and a widget stays
clickable while it moves. An animation the user has to wait out is a delay
wearing a costume, and a confirmation dialog that fades in slowly is worse than
one that appears.

**Nothing runs forever.** Every animation here is a one-shot with a fixed
duration, started by a change the user caused. There is no idle motion, no
pulsing and no looping — on a desktop finance application those read as
distraction, and they cost battery for the whole time the window is open.

**They are off under test.** A half-finished fade means a widget grabbed at 40%
opacity and an assertion that fails once in every twenty runs. Layout defects
here are found by rendering and looking (ADR-012), which only works if what is
rendered is settled. `conftest` sets `FINSIGHT_NO_ANIMATIONS`, and offscreen
rendering disables them too — the switch is explicit rather than inferred from
the platform, because this project's own tests run against a real display on a
developer machine and would otherwise animate exactly where it hurts most.

**On Qt stylesheets.** Qt's stylesheet engine has no `transition` property, so
hover and press states change instantly however they are written. Rather than
animate a colour per button — a graphics effect on every control, for a change
nobody perceives as gradual anyway — buttons get complete `:hover` and
`:pressed` rules in the sheet, and the animation budget is spent where movement
is actually visible: pages arriving, the sidebar indicator travelling, charts
drawing themselves, and panels updating.
"""

from __future__ import annotations

import os

from PySide6.QtCharts import QChart
from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

#: Immediate feedback on something the user just did — a chip arriving, a
#: banner appearing. Short enough to read as a response rather than a movement.
FAST_MS = 150

#: The normal transition: a panel redrawing, a card updating, a dialog opening.
NORMAL_MS = 220

#: A whole content area changing to a different screen. The largest change on
#: screen and the only one the eye needs to follow, so it gets the longest.
VIEW_MS = 280

#: How long a chart takes to draw itself. Longer than a UI transition on
#: purpose: this one *is* the content, and a bar growing to its value is worth
#: watching. Still under a third of a second.
CHART_MS = 420

#: One curve everywhere. Out, not in-out: a change should appear to arrive
#: quickly and settle, rather than easing in from nothing and reading as slow
#: to start.
EASING = QEasingCurve.Type.OutCubic

#: How far a sliding element travels. Small deliberately — this is a hint of
#: direction, not a journey across the panel.
SLIDE_PX = 10

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


def fade_in(widget: QWidget, duration_ms: int = NORMAL_MS) -> QPropertyAnimation | None:
    """Fade `widget` from transparent to opaque, returning the animation.

    The opacity effect is removed when the fade finishes. Leaving one attached
    is not free: every subsequent repaint of that widget is routed through an
    offscreen pixmap, which on a chart is the difference between a redraw
    nobody notices and one they do.

    Returns None when animations are disabled or the widget is hidden, so a
    caller can tell "ran" from "skipped" without inspecting the environment.
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
    animation.setEasingCurve(EASING)
    animation.finished.connect(lambda: _clear_effect(widget))
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def slide_fade_in(
    widget: QWidget,
    duration_ms: int = NORMAL_MS,
    *,
    offset: int = SLIDE_PX,
    delay_ms: int = 0,
) -> QParallelAnimationGroup | None:
    """Fade `widget` in while it rises the last few pixels into place.

    The two run in parallel rather than in sequence: a fade that finishes
    before the movement starts reads as two separate events.

    `delay_ms` staggers a row of cards, which is the one place a small delay
    earns its keep — four tiles arriving together read as one block, while
    forty milliseconds apart reads as a list being laid out. The delay is part
    of the same animation rather than a timer, so nothing is left pending if
    the widget goes away first.
    """
    if not animations_enabled() or not widget.isVisible():
        return None

    end = widget.geometry()
    if not end.isValid():
        return None
    start = QRect(end)
    start.moveTopLeft(end.topLeft() + QPoint(0, offset))

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    group = QParallelAnimationGroup(widget)

    fade = QPropertyAnimation(effect, b"opacity", group)
    fade.setDuration(duration_ms)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(EASING)
    group.addAnimation(fade)

    move = QPropertyAnimation(widget, b"geometry", group)
    move.setDuration(duration_ms)
    move.setStartValue(start)
    move.setEndValue(end)
    move.setEasingCurve(EASING)
    group.addAnimation(move)

    group.finished.connect(lambda: _clear_effect(widget))
    if delay_ms:
        # A paused start plus a single-shot timer would leave a timer pending
        # if the widget were destroyed; `QPauseAnimation` inside the group is
        # owned by it and dies with it. Expressed as a start delay on both
        # children, which is the same thing with one fewer object.
        fade.setDuration(duration_ms + delay_ms)
        fade.setKeyValueAt(delay_ms / (duration_ms + delay_ms), 0.0)
        move.setDuration(duration_ms + delay_ms)
        move.setKeyValueAt(delay_ms / (duration_ms + delay_ms), start)

    group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
    return group


def stagger_in(widgets: list[QWidget], duration_ms: int = NORMAL_MS, *, step_ms: int = 40) -> None:
    """Bring a row of cards in one after another, briefly.

    Capped rather than multiplied out: eight tiles at 40ms apart would take
    almost a third of a second before the last one appeared, which stops being
    a flourish and starts being a wait.
    """
    for index, widget in enumerate(widgets):
        slide_fade_in(widget, duration_ms, delay_ms=min(index * step_ms, 120))


def configure_chart(chart: QChart) -> None:
    """Give a chart its drawing animation, or none under test.

    QtCharts animates the *series* — bars grow to their values, a line draws
    itself — without touching the chart's series or axis lists. That matters
    here: this application has twice shipped a chart that accumulated series or
    axis labels across redraws, so the animation had to be one that changes
    nothing about the lifecycle. `SeriesAnimations` is exactly that, which is
    why it is used rather than anything hand-rolled.
    """
    if not animations_enabled():
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        return

    chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
    chart.setAnimationDuration(CHART_MS)
    chart.setAnimationEasingCurve(QEasingCurve(EASING))


def animate_geometry(
    widget: QWidget, end: QRect, duration_ms: int = NORMAL_MS
) -> QPropertyAnimation | None:
    """Move `widget` to `end`, or put it there at once when disabled.

    Used by the sidebar indicator, which is the one element in the application
    that travels rather than appears.
    """
    if not animations_enabled():
        widget.setGeometry(end)
        return None

    animation = QPropertyAnimation(widget, b"geometry", widget)
    animation.setDuration(duration_ms)
    animation.setStartValue(widget.geometry())
    animation.setEndValue(end)
    animation.setEasingCurve(EASING)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def _clear_effect(widget: QWidget) -> None:
    """Detach the opacity effect a fade attached.

    `setGraphicsEffect(None)` deletes the effect Qt owns, leaving the widget
    exactly as it was before. Guarded because a widget can be destroyed while
    its own animation is still finishing.
    """
    try:
        widget.setGraphicsEffect(None)
    except RuntimeError:
        # The widget went away first; nothing to detach.
        pass
