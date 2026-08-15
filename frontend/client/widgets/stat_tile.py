"""A single headline figure.

A stat tile, not a one-bar chart. When the data is one current value, the
number *is* the visualisation — drawing a bar of length one adds chrome and
communicates nothing the digits do not.

The tone is a status, not decoration: `positive` and `negative` are used only
where the sign carries meaning (money kept versus money lost), never to make a
row look varied.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

NEUTRAL = "neutral"
POSITIVE = "positive"
NEGATIVE = "negative"


class StatTile(QFrame):
    """A caption, a large value, and an optional line of context."""

    def __init__(
        self,
        caption: str,
        value: str = "—",
        *,
        detail: str = "",
        tone: str = NEUTRAL,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StatTile")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)

        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("StatCaption")
        layout.addWidget(self.caption_label)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setProperty("tone", tone)
        layout.addWidget(self.value_label)

        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("StatDetail")
        self.detail_label.setWordWrap(True)
        # Hidden rather than blank, so a tile without context is not taller
        # than it needs to be and a row of tiles still aligns.
        self.detail_label.setVisible(bool(detail))
        layout.addWidget(self.detail_label)

        layout.addStretch(1)
        self.setMinimumHeight(96)

    def set_value(self, value: str, *, tone: str = NEUTRAL, detail: str = "") -> None:
        """Replace the figure, its tone and its context line."""
        self.value_label.setText(value)
        self.value_label.setProperty("tone", tone)
        # Qt applies stylesheet rules at polish time; a property changed
        # afterwards needs an explicit refresh to take effect.
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)

        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))

    def set_caption(self, caption: str) -> None:
        self.caption_label.setText(caption)


class HeroTile(StatTile):
    """The one figure the dashboard leads with, at a larger size.

    Separate from `StatTile` only so the stylesheet can size it: a dashboard
    with six equally-loud numbers has no lead, and the eye has nowhere to land.
    """

    def __init__(self, caption: str, value: str = "—", **kwargs: object) -> None:
        super().__init__(caption, value, **kwargs)  # type: ignore[arg-type]
        self.setObjectName("HeroTile")
        self.value_label.setObjectName("HeroValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
