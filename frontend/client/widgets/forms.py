"""Small reusable form components.

Built once here so that every form in the application has the same spacing,
the same label placement and the same way of reporting a problem — rather
than each screen inventing its own.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget


class FormField(QWidget):
    """A labelled text input."""

    def __init__(
        self,
        label: str,
        *,
        placeholder: str = "",
        password: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        caption = QLabel(label)
        caption.setObjectName("FieldLabel")
        layout.addWidget(caption)

        self.input = QLineEdit()
        self.input.setObjectName("FieldInput")
        self.input.setPlaceholderText(placeholder)
        if password:
            self.input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.input)

    def text(self) -> str:
        return self.input.text()

    def clear(self) -> None:
        self.input.clear()

    def set_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)


class MessageBanner(QLabel):
    """An inline message above a form.

    Hidden when empty, so it takes no vertical space and the form does not
    shift as messages appear and disappear.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MessageBanner")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def show_error(self, message: str) -> None:
        self._show(message, "error")

    def show_info(self, message: str) -> None:
        self._show(message, "info")

    def _show(self, message: str, level: str) -> None:
        self.setText(message)
        self.setProperty("level", level)
        # Qt applies stylesheet rules at polish time; a property changed after
        # that needs an explicit refresh to take effect.
        self.style().unpolish(self)
        self.style().polish(self)
        self.setVisible(bool(message))

    def clear_message(self) -> None:
        self.setText("")
        self.hide()
