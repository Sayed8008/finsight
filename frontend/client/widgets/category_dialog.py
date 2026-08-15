"""Creating and renaming a category.

Two rules from the server show up as interface decisions here, rather than as
errors the user discovers by hitting them:

  * **A category's type is fixed once it exists** (ADR-020). Flipping an expense
    category to income would silently invalidate every transaction filed under
    it. The chooser is therefore present when creating and absent when editing —
    not present and disabled, which invites the question "why not?", but gone,
    with the type stated as a fact beside the name.
  * **Names are unique within a type, case-insensitively.** The server decides;
    this only reports what it says, because the client cannot know about a
    category created in another window (ADR-019).

The colour is picked from a fixed set rather than typed or chosen from a native
colour wheel. The set is the measured one the default categories use (ADR-026):
a colour here always appears as a small swatch beside its own name, and a
free choice is a free choice to pick two that nobody can tell apart.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiError
from client.api.dto import EXPENSE, INCOME, Category
from client.core.animation import NORMAL_MS, fade_in
from client.widgets.forms import FormField, LabelledWidget, MessageBanner

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 80

#: The measured palette the seeded categories use (ADR-026). Offered as a
#: fixed set because these were validated as a sequence of swatches — each one
#: read beside its own name — and a free hex field is a free hand to pick two
#: nobody can distinguish.
PALETTE: tuple[str, ...] = (
    "#1a7f4b",
    "#0369a1",
    "#a06a1f",
    "#7a5cb8",
    "#00968a",
    "#c0392b",
    "#2b9ab5",
    "#d9782e",
    "#1a56c4",
    "#c43f8a",
    "#4d8b1f",
    "#8a4fbd",
    "#b06a12",
    "#e0457b",
    "#8b939c",
)

SWATCHES_PER_ROW = 8

TYPE_CHOICES: tuple[tuple[str, str], ...] = (
    ("Money out (expense)", EXPENSE),
    ("Money in (income)", INCOME),
)

TYPE_NAMES = {INCOME: "Money in (income)", EXPENSE: "Money out (expense)"}


class CategoryDialog(QDialog):
    """Add a category, or rename and recolour an existing one."""

    def __init__(
        self,
        *,
        save: Callable[[dict[str, Any]], object],
        category: Category | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._save = save
        self._category = category
        self._colour = category.color if category and category.color else PALETTE[0]
        self._swatches: dict[str, QPushButton] = {}

        editing = category is not None
        self.setWindowTitle("Edit category" if editing else "Add category")
        self.setObjectName("CategoryDialog")
        self.setModal(True)
        #: Set once so re-showing a dialog does not fade it again.
        self._faded_in = False
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)

        layout.addWidget(self._build_header(editing))

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        self.name_field = FormField("Name", placeholder="Groceries")
        self.name_field.input.setMaxLength(MAX_NAME_LENGTH)
        if category is not None:
            self.name_field.input.setText(category.name)
        layout.addWidget(self.name_field)

        layout.addWidget(self._build_type_row(editing))
        layout.addWidget(self._build_palette())
        layout.addWidget(self._build_buttons(editing))

        self.name_field.input.setFocus()

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self, editing: bool) -> QWidget:
        panel = QWidget()
        panel.setObjectName("FormRow")
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        title = QLabel("Edit category" if editing else "Add category")
        title.setObjectName("AuthTitle")
        box.addWidget(title)

        self.subtitle = QLabel(
            "The kind cannot change once a category exists — an expense filed "
            "under an income category would break every total that trusts the pair."
            if editing
            else "Choose whether this groups money coming in or going out. That cannot "
            "be changed later."
        )
        self.subtitle.setObjectName("AuthSubtitle")
        self.subtitle.setWordWrap(True)
        box.addWidget(self.subtitle)

        return panel

    def _build_type_row(self, editing: bool) -> QWidget:
        """The type chooser, or a statement of it.

        Absent rather than disabled when editing. A greyed-out control asks
        "why can I not change this?" and answers nothing; a plain line of text
        says what the category is and moves on.
        """
        if editing and self._category is not None:
            self.type_box = None
            label = QLabel(TYPE_NAMES.get(self._category.category_type, "—"))
            label.setObjectName("FieldStatic")
            return LabelledWidget("Kind", label)

        self.type_box = QComboBox()
        self.type_box.setObjectName("FieldSelect")
        for text, value in TYPE_CHOICES:
            self.type_box.addItem(text, value)
        return LabelledWidget("Kind", self.type_box)

    def _build_palette(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("FormRow")
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        caption = QLabel("Colour")
        caption.setObjectName("FieldLabel")
        box.addWidget(caption)

        grid = QGridLayout()
        grid.setSpacing(6)
        for index, colour in enumerate(PALETTE):
            swatch = QPushButton()
            swatch.setObjectName("ColourSwatch")
            swatch.setCheckable(True)
            swatch.setFixedSize(26, 26)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip(colour)
            # The fill is data, not styling, so it is set per widget rather
            # than in the stylesheet — the same reason the category swatches on
            # the analytics rows are.
            swatch.setStyleSheet(f"background-color: {colour};")
            swatch.clicked.connect(lambda _=False, value=colour: self.choose_colour(value))
            grid.addWidget(swatch, index // SWATCHES_PER_ROW, index % SWATCHES_PER_ROW)
            self._swatches[colour] = swatch

        grid.setColumnStretch(SWATCHES_PER_ROW, 1)

        inner = QWidget()
        inner.setObjectName("FormRow")
        inner.setLayout(grid)
        box.addWidget(inner)

        self.choose_colour(self._colour)
        return holder

    def _build_buttons(self, editing: bool) -> QWidget:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )

        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setText("Save changes" if editing else "Add category")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)

        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setObjectName("SecondaryButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)

        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        return buttons

    # ─── State ────────────────────────────────────────────────────────────

    def choose_colour(self, colour: str) -> None:
        """Select one swatch, and only one.

        Qt checkable buttons are independent, so the previous one has to be
        unchecked explicitly — left alone, every colour ever clicked stays
        looking chosen.
        """
        self._colour = colour
        for value, swatch in self._swatches.items():
            swatch.setChecked(value == colour)

    def colour(self) -> str:
        return self._colour

    def category_type(self) -> str:
        if self.type_box is not None:
            return str(self.type_box.currentData())
        return self._category.category_type if self._category else EXPENSE

    def payload(self) -> dict[str, Any]:
        """What will be sent.

        An edit sends only name and colour. Sending the type as well would be a
        request the server has to refuse, and a request nobody meant to make.
        """
        name = self.name_field.text().strip()
        if self._category is not None:
            return {"name": name, "color": self._colour}
        return {"name": name, "category_type": self.category_type(), "color": self._colour}

    # ─── Submitting ───────────────────────────────────────────────────────

    def validate(self) -> str | None:
        """The first thing wrong with the form, or None.

        Feedback, not enforcement: every rule here is also enforced by the
        server, which is the only authority (ADR-019). This exists so a blank
        name is reported instantly rather than after a round trip.
        """
        name = self.name_field.text().strip()
        if not name:
            return "A category needs a name."
        if len(name) > MAX_NAME_LENGTH:
            return f"A name is at most {MAX_NAME_LENGTH} characters."
        return None

    def submit(self) -> None:
        problem = self.validate()
        if problem:
            self.banner.show_error(problem)
            return

        try:
            self._save(self.payload())
        except ApiError as exc:
            logger.warning("Could not save category: %s", exc.message)
            self.banner.show_error(exc.message)
            return

        self.accept()

    def showEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        """Fade the dialog in the first time it is shown.

        `showEvent` rather than `__init__`: a widget has no geometry until it
        is shown, and the fade must run inside `exec`'s own event loop. Guarded
        so a dialog raised again is not re-faded, which would read as a flicker
        rather than as an opening.
        """
        super().showEvent(event)
        if not self._faded_in:
            self._faded_in = True
            fade_in(self, NORMAL_MS)
