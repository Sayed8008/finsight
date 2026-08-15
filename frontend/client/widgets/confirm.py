"""Asking the user to confirm something destructive.

One function, because the obvious way to write this by hand is wrong. Qt's
`QMessageBox.question` is typed as returning a `StandardButton`, but PySide6
hands back a plain `int`:

    >>> answer = QMessageBox.question(...)   # user presses Yes
    >>> answer
    16384
    >>> answer is QMessageBox.StandardButton.Yes
    False                                   # an int is never an enum member
    >>> answer == QMessageBox.StandardButton.Yes
    True

Every confirmation in this application had been written with `is`, so all of
them silently did nothing — sign-out, deleting a transaction, deleting a
budget, retiring a category, deleting a subscription and marking one renewed.
Each looked correct in review, and an identity check against an enum is exactly
the sort of thing that reads as more precise than `==` rather than less.

Returning a `bool` is what stops it happening again: there is no enum left at
the call site to compare against, correctly or otherwise.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm(parent: QWidget | None, title: str, question: str) -> bool:
    """Ask `question`, returning True only if the user chose Yes.

    Cancel is the default, so that pressing Enter or Escape out of a dialog
    someone opened by accident leaves their data alone.
    """
    answer = QMessageBox.question(
        parent,
        title,
        question,
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
        QMessageBox.StandardButton.Cancel,
    )
    return answer == QMessageBox.StandardButton.Yes
