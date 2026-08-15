"""Reviewing detected subscriptions before any of them exist.

The screen where ADR-007's central constraint is enforced in the interface:
**detection proposes, the user decides**. Nothing here is created until someone
presses Track on a specific candidate, and every candidate shows the evidence
it was built from so that pressing Track is a judgement rather than a leap of
faith.

Deliberately not a "Track all" button. Accepting eight guesses at once is
exactly the action nobody would take carefully, and the one most likely to put
something wrong into a monthly commitment total.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api.client import ApiError
from client.api.dto import Candidate, Detection
from client.widgets.forms import MessageBanner

logger = logging.getLogger(__name__)


class DetectionDialog(QDialog):
    """A list of candidates, each tracked or ignored on its own."""

    def __init__(
        self,
        detection: Detection,
        *,
        track: Callable[[Candidate], object],
        currency: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._detection = detection
        self._track = track
        self._currency = currency
        #: Names accepted during this review. Kept separate from the hidden
        #: ones below: both disappear from the list, but only these were
        #: actually created, and the caller refreshes on the strength of it.
        self.tracked: list[str] = []
        #: Names dismissed during this review. Dropped from the list, created
        #: nowhere, remembered nowhere once this dialog closes.
        self.hidden: list[str] = []

        self.setWindowTitle("Subscriptions found")
        self.setObjectName("DetectionDialog")
        self.setModal(True)
        self.setMinimumSize(620, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())

        self.banner = MessageBanner()
        layout.addWidget(self.banner)

        layout.addWidget(self._build_list(), stretch=1)
        layout.addWidget(self._build_buttons())

        self._render()

    # ─── Construction ─────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("FormRow")
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        self.title_label = QLabel("")
        self.title_label.setObjectName("AuthTitle")
        box.addWidget(self.title_label)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("AuthSubtitle")
        self.subtitle_label.setWordWrap(True)
        box.addWidget(self.subtitle_label)

        return panel

    def _build_list(self) -> QWidget:
        self._holder = QWidget()
        self._holder.setObjectName("CardHolder")
        self._holder_layout = QVBoxLayout(self._holder)
        self._holder_layout.setContentsMargins(0, 0, 0, 0)
        self._holder_layout.setSpacing(10)
        self._holder_layout.addStretch(1)

        area = QScrollArea()
        area.setObjectName("CardScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(self._holder)
        return area

    def _build_buttons(self) -> QWidget:
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        close.setObjectName("SecondaryButton")
        close.setText("Done")
        buttons.rejected.connect(self.accept)
        # `accept`, not `reject`: the user may have tracked something, and the
        # caller needs to refresh either way.
        buttons.accepted.connect(self.accept)
        return buttons

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render(self) -> None:
        self._clear()
        remaining = self.remaining_candidates()

        window = (
            f"{self._detection.searched_from:%d %b %Y} to {self._detection.searched_to:%d %b %Y}"
        )

        if not remaining:
            self.title_label.setText(
                "Nothing new found" if not self.tracked else "That is everything"
            )
            self.subtitle_label.setText(
                f"Searched {window}. Detection only proposes charges that repeat on a "
                "regular schedule, so an irregular bill will not appear here."
            )
            return

        count = len(remaining)
        self.title_label.setText(f"{count} possible subscription{'s' if count != 1 else ''} found")
        self.subtitle_label.setText(
            f"Searched {window}. Nothing is added until you choose it — each one "
            "shows the charges it was found from."
        )

        for candidate in remaining:
            self._holder_layout.insertWidget(self._holder_layout.count() - 1, self._card(candidate))

    def remaining_candidates(self) -> tuple[Candidate, ...]:
        """Candidates neither accepted nor dismissed in this review."""
        decided = set(self.tracked) | set(self.hidden)
        return tuple(
            candidate for candidate in self._detection.candidates if candidate.name not in decided
        )

    def _clear(self) -> None:
        for index in reversed(range(self._holder_layout.count())):
            widget = self._holder_layout.itemAt(index).widget()
            if widget is not None:
                self._holder_layout.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

    def _card(self, candidate: Candidate) -> QWidget:
        card = QFrame()
        card.setObjectName("CandidateCard")
        card.setProperty("confidence", candidate.confidence)

        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)

        name = QLabel(candidate.name)
        name.setObjectName("CandidateName")
        header.addWidget(name)

        badge = QLabel(candidate.confidence_label)
        badge.setObjectName("CandidateBadge")
        badge.setProperty("confidence", candidate.confidence)
        header.addWidget(badge)

        header.addStretch(1)

        cost = QLabel(f"{self._money(candidate.amount)} {candidate.cycle_label.lower()}")
        cost.setObjectName("CandidateCost")
        header.addWidget(cost)
        box.addLayout(header)

        evidence = QLabel(candidate.evidence)
        evidence.setObjectName("CandidateEvidence")
        evidence.setWordWrap(True)
        box.addWidget(evidence)

        footer = QHBoxLayout()
        footer.setSpacing(8)

        seen = QLabel(
            f"First seen {candidate.first_seen:%d %b %Y} · "
            f"last {candidate.last_seen:%d %b %Y} · "
            f"next expected {candidate.next_expected:%d %b %Y}"
        )
        seen.setObjectName("CandidateSeen")
        footer.addWidget(seen)
        footer.addStretch(1)

        ignore = QPushButton("Not a subscription")
        ignore.setObjectName("SecondaryButton")
        ignore.setCursor(Qt.CursorShape.PointingHandCursor)
        ignore.setToolTip("Hide this suggestion for now")
        ignore.clicked.connect(lambda _=False, item=candidate: self.ignore(item))
        footer.addWidget(ignore)

        accept = QPushButton("Track it")
        accept.setObjectName("PrimaryButton")
        accept.setCursor(Qt.CursorShape.PointingHandCursor)
        accept.clicked.connect(lambda _=False, item=candidate: self.accept_candidate(item))
        footer.addWidget(accept)

        box.addLayout(footer)
        return card

    # ─── Actions ──────────────────────────────────────────────────────────

    def accept_candidate(self, candidate: Candidate) -> None:
        """Create this one, and only this one.

        A failure here removes nothing else from the list: the other candidates
        are still worth reviewing, and losing them because one save failed
        would mean running detection again.
        """
        try:
            self._track(candidate)
        except ApiError as exc:
            logger.warning("Could not track %s: %s", candidate.name, exc.message)
            self.banner.show_error(f"Could not track {candidate.name}: {exc.message}")
            return

        self.banner.show_info(f"{candidate.name} is now being tracked.")
        self.tracked.append(candidate.name)
        self._render()

    def ignore(self, candidate: Candidate) -> None:
        """Hide a suggestion for this review only.

        Not persisted. A permanent "never suggest this" list is a real feature
        and a bigger one — it needs its own table and a way to undo. Saying so
        is better than pretending the button does more than it does.
        """
        self.hidden.append(candidate.name)
        self.banner.show_info(f"{candidate.name} hidden for now.")
        self._render()

    def _money(self, value: Decimal) -> str:
        return f"{value:,.2f} {self._currency}".strip()

    @property
    def tracked_anything(self) -> bool:
        """Whether anything was actually created, as opposed to dismissed."""
        return bool(self.tracked)
