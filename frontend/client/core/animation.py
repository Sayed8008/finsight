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
    QPauseAnimation,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

# ─── Durations ────────────────────────────────────────────────────────────
#
# Not one number. How long a movement should take depends on how much of the
# screen it covers and on whether it *is* the content or merely delivers it:
# a chip arriving is feedback and should be over before it is noticed, while a
# line drawing twelve months of savings is the thing the user came to look at
# and deserves to be watched.
#
# The first version of this used 420ms for every chart, which was too quick to
# read as motion at all — the chart appeared to blink into its final state.
# Smooth is not the same as fast.

#: Immediate feedback on something the user just did — a chip arriving, a
#: banner appearing, a marker moving one row.
FAST_MS = 180

#: The normal transition: a panel redrawing, a dialog opening.
NORMAL_MS = 240

#: A whole content area changing to a different screen.
VIEW_MS = 340

#: A card arriving. Longer than a dialog because several of them stagger, and
#: the last one should still feel deliberate rather than late.
CARD_MS = 320

#: A budget bar filling to its share. Long enough to be unmistakably *drawn*
#: rather than set — this is a figure about the user's own money, and watching
#: it fill is the point.
PROGRESS_MS = 640

#: A bar chart building itself. Scaled by bar count in `bar_chart_ms`, because
#: six bars and twenty-four bars are not the same amount of movement.
BAR_BASE_MS = 620
BAR_PER_ITEM_MS = 16
BAR_MAX_MS = 900

#: A line drawing itself, likewise scaled by how many points it has.
LINE_BASE_MS = 760
LINE_PER_ITEM_MS = 22
LINE_MAX_MS = 1200

#: How long after the line reaches a point before its marker settles in. The
#: markers are a separate series precisely so they can land *after* the line
#: rather than travelling with it.
POINT_SETTLE_MS = 260

#: One curve for anything that arrives and stays: quick to start, settling at
#: the end. Out, not in-out — easing in from nothing reads as slow to begin.
EASING = QEasingCurve.Type.OutCubic

#: For things that *fill* rather than appear: a budget bar, a growing chart
#: series. Quintic holds its speed longer before settling, which reads as
#: deliberate travel rather than a spring.
FILL_EASING = QEasingCurve.Type.OutQuint

#: For a marker landing. A very slight overshoot — a few per cent, not a
#: bounce — is what separates "placed" from "dropped in".
SETTLE_EASING = QEasingCurve.Type.OutBack

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


#: Attribute holding the animation currently running on a widget, so a second
#: one can stop it first. Without this, starting a new fade replaces the
#: opacity effect the running animation is driving — Qt then logs
#: "Changing state of an animation without target" for every orphaned
#: animation, and the two fades fight over the same widget.
_RUNNING = "_finsight_running_animation"


def _stop_running(widget: QWidget) -> None:
    """Stop and forget any animation already running on `widget`."""
    existing = getattr(widget, _RUNNING, None)
    if existing is None:
        return
    try:
        existing.stop()
    except RuntimeError:
        pass  # already deleted by DeleteWhenStopped
    setattr(widget, _RUNNING, None)


def _remember(widget: QWidget, animation) -> None:
    setattr(widget, _RUNNING, animation)


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

    _stop_running(widget)
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration_ms)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(EASING)
    animation.finished.connect(lambda: _clear_effect(widget))
    _remember(widget, animation)
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

    _stop_running(widget)
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

    # The stagger is a real pause in front of the pair, for the reason given
    # in `delayed`: a key value would be placed against eased progress and the
    # hold would be over long before the wall clock said so.
    runnable = delayed(group, delay_ms, widget) if delay_ms else group
    _remember(widget, runnable)
    runnable.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
    return group


def stagger_in(widgets: list[QWidget], duration_ms: int = CARD_MS, *, step_ms: int = 55) -> None:
    """Bring a row of cards in one after another, briefly.

    Capped rather than multiplied out: eight tiles at 40ms apart would take
    almost a third of a second before the last one appeared, which stops being
    a flourish and starts being a wait.
    """
    for index, widget in enumerate(widgets):
        slide_fade_in(widget, duration_ms, delay_ms=min(index * step_ms, 165))


def delayed(animation, delay_ms: int, parent) -> QSequentialAnimationGroup:
    """Hold `animation` for `delay_ms`, then run it.

    A `QPauseAnimation` in sequence, not a key value at the start of the same
    animation. Key values are placed against *eased* progress, and every curve
    here is an "out" curve that covers most of its distance early — so a hold
    written as a key value at 75% of the timeline was over in about a third of
    the wall clock. Caught by watching the markers appear at 300ms into a
    1,024ms line rather than after it.

    Not a `QTimer` either: the group is parented, so a card destroyed by a
    reload takes its pending animation with it instead of firing into a
    deleted widget.
    """
    group = QSequentialAnimationGroup(parent)
    group.addAnimation(QPauseAnimation(delay_ms, group))
    group.addAnimation(animation)
    return group


def bar_chart_ms(item_count: int) -> int:
    """How long a bar chart of this size should take to build.

    Scaled by the number of bars rather than fixed: six bars finishing in the
    time twenty-four need would look sluggish, and twenty-four finishing in the
    time six need would look like a flash. Capped so a long span never becomes
    a wait.
    """
    return min(BAR_BASE_MS + BAR_PER_ITEM_MS * max(item_count, 0), BAR_MAX_MS)


def line_chart_ms(item_count: int) -> int:
    """How long a line of this many points should take to draw itself.

    Longer than the equivalent bar chart on purpose. A bar chart is read by
    comparing heights, which the eye can do the instant the bars are there; a
    line is read by following its shape, and drawing it at the pace a reader
    follows it is what makes the shape legible rather than decorative.
    """
    return min(LINE_BASE_MS + LINE_PER_ITEM_MS * max(item_count, 0), LINE_MAX_MS)


def configure_bar_chart(chart: QChart, item_count: int) -> None:
    """Bars grow into their values, with a firm settle.

    QtCharts animates the *series* — the bars grow from the axis — without
    touching the chart's series or axis lists. That matters here: this
    application has twice shipped a chart that accumulated series or axis
    labels across redraws, so the animation had to be one that changes nothing
    about the lifecycle.

    `OutQuint` rather than the interface's usual `OutCubic`: a bar filling
    should hold its speed and then settle, which reads as a quantity being
    measured out. The gentler cubic makes it look like it is merely appearing.
    """
    _apply(chart, bar_chart_ms(item_count), FILL_EASING)


def configure_line_chart(chart: QChart, item_count: int) -> None:
    """The line draws itself, slowly enough to be followed.

    Its markers are a separate scatter series, faded in afterwards by the
    chart widget — see `SavingsChart._rebuild`. Splitting them is what lets
    the points *settle onto* a line that has already arrived, rather than
    every dot travelling along with it.
    """
    _apply(chart, line_chart_ms(item_count), EASING)


def _apply(chart: QChart, duration_ms: int, easing: QEasingCurve.Type) -> None:
    if not animations_enabled():
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        return
    chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
    chart.setAnimationDuration(duration_ms)
    chart.setAnimationEasingCurve(QEasingCurve(easing))


def fill_progress(
    bar, value: int, *, duration_ms: int = PROGRESS_MS, delay_ms: int = 0
) -> QPropertyAnimation | None:
    """Grow a progress bar from empty to `value`.

    A budget bar that is simply *set* tells the user a number. One that fills
    shows them the month being spent, which is the same figure read as a
    movement — and it is the one animation here that people asked for by
    describing what they wanted to feel, rather than what they wanted to see.

    Disabled, the value is set directly: the bar must be right whether or not
    it moved.
    """
    target = max(bar.minimum(), min(value, bar.maximum()))
    if not animations_enabled():
        bar.setValue(target)
        return None

    bar.setValue(bar.minimum())
    animation = QPropertyAnimation(bar, b"value", bar)
    animation.setDuration(duration_ms)
    animation.setStartValue(bar.minimum())
    animation.setEndValue(target)
    animation.setEasingCurve(FILL_EASING)

    runnable = delayed(animation, delay_ms, bar) if delay_ms else animation
    runnable.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


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
