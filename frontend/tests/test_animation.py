"""Tests for the transition helper.

The requirement these defend is that polish must not cost reliability. An
animation that blocks, that leaves a widget half-transparent, or that makes a
button unclickable while it runs is worse than no animation — so those are the
properties asserted, not the visual effect.

The suite disables them, which is where the helper deliberately does
nothing. That is itself the behaviour under test: a fade caught mid-flight
would make every screenshot assertion in the suite intermittent.
"""

from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QPushButton, QWidget

from client.core.animation import (
    DISABLE_ENV,
    FAST_MS,
    NORMAL_MS,
    VIEW_MS,
    animations_enabled,
    bar_chart_ms,
    fade_in,
    line_chart_ms,
)

pytestmark = pytest.mark.gui


def test_animations_are_disabled_under_test() -> None:
    """Layout defects here are found by rendering and looking (ADR-012), which
    only works if what is rendered is settled rather than mid-fade.

    Set explicitly by `conftest` rather than inferred from the platform: this
    suite runs against a real display on a developer machine, so a
    platform-based check would leave them on exactly where it hurts most.
    """
    assert os.environ.get(DISABLE_ENV)
    assert animations_enabled() is False


def test_fading_a_widget_under_test_is_a_no_op(qtbot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    assert fade_in(widget) is None


def test_a_skipped_fade_leaves_no_effect_attached(qtbot) -> None:
    """A leftover opacity effect routes every later repaint through an
    offscreen pixmap, which on a chart is a redraw people notice."""
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    fade_in(widget)

    assert widget.graphicsEffect() is None


def test_fading_a_hidden_widget_does_nothing(qtbot) -> None:
    """Nothing to see, and attaching an effect to it would still cost."""
    widget = QWidget()
    qtbot.addWidget(widget)

    assert fade_in(widget) is None


def test_a_faded_widget_stays_interactive(qtbot) -> None:
    """The rule that matters: a transition must never gate the user."""
    button = QPushButton("Sign out")
    qtbot.addWidget(button)
    button.show()
    clicks: list[int] = []
    button.clicked.connect(lambda: clicks.append(1))

    fade_in(button)
    button.click()

    assert button.isEnabled()
    assert clicks == [1]


def test_the_durations_are_short_enough_to_read_as_polish() -> None:
    """Interface transitions stay in the 150-400ms band. Charts are longer
    and deliberately so — they are the content, not the delivery of it."""
    for duration in (FAST_MS, NORMAL_MS, VIEW_MS):
        assert 150 <= duration <= 400


# ─── The motion language is shared, not reinvented per screen ─────────────


def test_one_easing_curve_is_used_everywhere() -> None:
    """A consistent motion language means one curve, not one per widget."""
    from PySide6.QtCore import QEasingCurve

    from client.core.animation import EASING

    assert EASING == QEasingCurve.Type.OutCubic


def test_the_durations_are_ordered_by_how_much_moves() -> None:
    """Fast feedback, normal transition, larger view change — in that order."""
    assert FAST_MS < NORMAL_MS < VIEW_MS


def test_charts_are_told_not_to_animate_under_test(qtbot) -> None:
    """The accumulation bugs this application has shipped were both found by
    counting series and axes across redraws. That only works if a redraw has
    finished by the time it is counted."""
    from PySide6.QtCharts import QChart

    from client.core.animation import configure_bar_chart, configure_line_chart

    for configure in (configure_bar_chart, configure_line_chart):
        chart = QChart()
        configure(chart, 12)
        assert chart.animationOptions() == QChart.AnimationOption.NoAnimation


def test_each_chart_type_moves_differently() -> None:
    """A coherent motion system, not an identical one: a line is followed and
    a bar is compared, so they are not paced the same."""
    from client.core.animation import bar_chart_ms, line_chart_ms

    assert line_chart_ms(12) > bar_chart_ms(12)


def test_chart_durations_scale_with_how_much_is_drawn() -> None:
    """Six bars finishing in the time twenty-four need looks sluggish."""
    assert bar_chart_ms(24) > bar_chart_ms(6)
    assert line_chart_ms(24) > line_chart_ms(6)


def test_chart_durations_are_capped_so_a_long_span_is_never_a_wait() -> None:
    from client.core.animation import BAR_MAX_MS, LINE_MAX_MS

    assert bar_chart_ms(500) == BAR_MAX_MS
    assert line_chart_ms(500) == LINE_MAX_MS


def test_graph_motion_is_slow_enough_to_be_seen() -> None:
    """The complaint that prompted this: 420ms for every chart was too quick
    to register as motion at all."""
    assert bar_chart_ms(12) >= 600
    assert line_chart_ms(12) >= 700


def test_a_progress_bar_is_filled_even_with_animations_off(qtbot) -> None:
    """A bar left empty because nobody animated it would be a correctness bug
    caused by decoration."""
    from PySide6.QtWidgets import QProgressBar

    from client.core.animation import fill_progress

    bar = QProgressBar()
    qtbot.addWidget(bar)
    bar.setRange(0, 100)

    assert fill_progress(bar, 63) is None
    assert bar.value() == 63


def test_a_progress_fill_is_capped_to_the_bar_range(qtbot) -> None:
    from PySide6.QtWidgets import QProgressBar

    from client.core.animation import fill_progress

    bar = QProgressBar()
    qtbot.addWidget(bar)
    bar.setRange(0, 100)

    fill_progress(bar, 150)

    assert bar.value() == 100


def test_a_disabled_geometry_animation_still_moves_the_widget(qtbot) -> None:
    """Disabling the animation must not disable the *result*: the sidebar
    indicator has to end up on the selected item either way."""
    from PySide6.QtCore import QRect

    from client.core.animation import animate_geometry

    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    target = QRect(2, 120, 3, 20)

    assert animate_geometry(widget, target) is None
    assert widget.geometry() == target


def test_staggering_an_empty_row_is_harmless() -> None:
    from client.core.animation import stagger_in

    stagger_in([])


def test_a_skipped_slide_leaves_no_effect_attached(qtbot) -> None:
    from client.core.animation import slide_fade_in

    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    assert slide_fade_in(widget) is None
    assert widget.graphicsEffect() is None


def test_a_second_animation_stops_the_first(qtbot) -> None:
    """Starting a fade on a widget already fading replaces the opacity effect
    the running animation drives. Qt then logs "Changing state of an animation
    without target" for every orphan — 57 of them on one navigation sweep —
    and the two fades fight over the same widget.

    Found by watching the console during manual verification, not by a test
    failing, which is why one exists now.
    """
    from client.core.animation import _RUNNING, _stop_running

    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    # Simulated because animations are off under test: what is asserted is
    # that a running animation is tracked and stopped, not that it ran.
    class Fake:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    running = Fake()
    setattr(widget, _RUNNING, running)

    _stop_running(widget)

    assert running.stopped
    assert getattr(widget, _RUNNING) is None


def test_stopping_an_already_deleted_animation_is_harmless(qtbot) -> None:
    """`DeleteWhenStopped` may have removed it already; the guard must not
    raise on a widget being torn down."""
    from client.core.animation import _RUNNING, _stop_running

    widget = QWidget()
    qtbot.addWidget(widget)

    class Gone:
        def stop(self) -> None:
            raise RuntimeError("wrapped C/C++ object has been deleted")

    setattr(widget, _RUNNING, Gone())

    _stop_running(widget)  # must not raise
