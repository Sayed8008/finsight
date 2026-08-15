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
    CHIP_MS,
    DISABLE_ENV,
    PAGE_MS,
    PANEL_MS,
    animations_enabled,
    fade_in,
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
    """Past about 200ms on a desktop application a transition reads as lag."""
    for duration in (PAGE_MS, PANEL_MS, CHIP_MS):
        assert 0 < duration <= 200
