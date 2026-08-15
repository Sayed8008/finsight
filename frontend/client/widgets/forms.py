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


class LabelledWidget(QWidget):
    """Any input, with a caption above it.

    `FormField` builds its own `QLineEdit`; this wraps something already built —
    a combo box, a date editor — so that a form mixing input types still has one
    consistent label style and spacing rather than each row inventing its own.
    """

    def __init__(self, label: str, widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Named so the stylesheet can make this container transparent by id.
        # The tempting alternative — `#Dialog QWidget { background: transparent }`
        # — also matches every button inside it, and being more specific than
        # `#PrimaryButton` it wins, leaving the primary button painted in
        # nothing. See ADR-022.
        self.setObjectName("FormRow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        caption = QLabel(label)
        caption.setObjectName("FieldLabel")
        layout.addWidget(caption)

        self.widget = widget
        layout.addWidget(widget)


#: Methods offered before the account has any history of its own.
#:
#: `payment_method` is free text in the database, deliberately — it becomes a
#: table only if it earns one (see docs/DATABASE.md) — and the API reports the
#: distinct values a user has actually recorded. That is the right answer for
#: the *filter* bar, where offering a method nobody has used would return an
#: empty list, and the wrong one for a *form*: a new account has recorded
#: nothing, so the picker offered nothing, and the first transaction anyone
#: ever adds had an empty dropdown.
#:
#: These are suggestions, not a vocabulary. The field stays editable and the
#: server still accepts any string, so nothing here can stop somebody
#: recording a method that was not thought of.
SUGGESTED_PAYMENT_METHODS: tuple[str, ...] = (
    "Cash",
    "bKash",
    "Nagad",
    "Card",
    "Bank transfer",
)


def payment_method_options(known: list[str] | None = None) -> list[str]:
    """What to offer in a payment-method picker.

    The account's own methods first, because a value somebody has already used
    is more likely to be the one they want than a suggestion. Suggestions
    follow, minus anything already listed — matched case-insensitively, so an
    account that records "cash" is not offered "Cash" a second line below.
    """
    options = list(known or [])
    seen = {method.strip().lower() for method in options}

    for suggestion in SUGGESTED_PAYMENT_METHODS:
        if suggestion.lower() not in seen:
            options.append(suggestion)
            seen.add(suggestion.lower())

    return options


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
