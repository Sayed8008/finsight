"""Placeholder page shown for sections that are not built yet.

This doubles as the basis for the real empty states in later phases: a title,
an explanatory line, and nothing else competing for attention.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderView(QWidget):
    """Centred title and message for an unbuilt section."""

    def __init__(self, title: str, message: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaceholderView")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("PlaceholderTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        body = QLabel(message)
        body.setObjectName("PlaceholderMessage")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        # Qt stylesheets do not support `max-width`, so the wrap width has to
        # be set here. Without it the text wraps to the width of the title.
        body.setMaximumWidth(440)
        layout.addWidget(body, alignment=Qt.AlignmentFlag.AlignCenter)
