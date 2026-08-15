"""Tests for reviewing detected subscriptions.

The constraint ADR-007 rests on is an interface constraint as much as a service
one: **nothing is created until the user picks a specific candidate**. These
check that, that the evidence is shown rather than summarised away, and that
dismissing something is not quietly the same as accepting it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QFrame, QLabel

from client.api.client import ApiError
from client.api.dto import Candidate, Detection
from client.widgets.detection_dialog import DetectionDialog

pytestmark = pytest.mark.gui


def candidate(
    name: str = "Netflix",
    amount: str = "499.00",
    confidence: str = "high",
    evidence: str = "5 charges of 499.00, exactly 30 days apart.",
    cycle: str = "monthly",
    category_id: int | None = 5,
) -> Candidate:
    return Candidate(
        name=name,
        amount=Decimal(amount),
        billing_cycle=cycle,
        confidence=confidence,
        evidence=evidence,
        occurrences=5,
        first_seen=date(2026, 1, 5),
        last_seen=date(2026, 5, 5),
        median_interval_days=30,
        interval_spread_days=0,
        next_expected=date(2026, 6, 4),
        transaction_ids=(1, 2, 3, 4, 5),
        category_id=category_id,
    )


def detection(*candidates: Candidate) -> Detection:
    return Detection(
        searched_from=date(2025, 6, 15),
        searched_to=date(2026, 6, 15),
        candidates=candidates,
    )


def make(qtbot, *candidates: Candidate, track=None):
    created: list[Candidate] = []

    def default_track(item: Candidate) -> None:
        created.append(item)

    dialog = DetectionDialog(detection(*candidates), track=track or default_track, currency="BDT")
    qtbot.addWidget(dialog)
    return dialog, created


def cards(dialog: DetectionDialog) -> list[QFrame]:
    return dialog.findChildren(QFrame, "CandidateCard")


def texts(dialog: DetectionDialog, name: str) -> list[str]:
    return [label.text() for label in dialog.findChildren(QLabel, name)]


# ─── Nothing happens without being asked ──────────────────────────────────


def test_opening_the_dialog_creates_nothing(qtbot) -> None:
    """ADR-007's central constraint, at the point the user sees it."""
    dialog, created = make(qtbot, candidate(), candidate(name="Spotify"))

    assert len(cards(dialog)) == 2
    assert created == []
    assert dialog.tracked_anything is False


def test_tracking_one_candidate_creates_only_that_one(qtbot) -> None:
    dialog, created = make(qtbot, candidate(), candidate(name="Spotify"))

    dialog.accept_candidate(dialog.remaining_candidates()[0])

    assert [item.name for item in created] == ["Netflix"]
    assert dialog.tracked == ["Netflix"]


def test_a_tracked_candidate_leaves_the_list(qtbot) -> None:
    dialog, _ = make(qtbot, candidate(), candidate(name="Spotify"))

    dialog.accept_candidate(dialog.remaining_candidates()[0])

    assert [item.name for item in dialog.remaining_candidates()] == ["Spotify"]
    assert len(cards(dialog)) == 1


def test_dismissing_is_not_the_same_as_tracking(qtbot) -> None:
    """Both remove the row; only one of them created anything."""
    dialog, created = make(qtbot, candidate())

    dialog.ignore(dialog.remaining_candidates()[0])

    assert created == []
    assert dialog.tracked == []
    assert dialog.hidden == ["Netflix"]
    assert dialog.tracked_anything is False


def test_a_failure_keeps_the_other_candidates(qtbot) -> None:
    """Losing the whole list because one save failed would mean running
    detection again for no reason."""

    def refuse(item: Candidate) -> None:
        raise ApiError("A subscription with that name already exists.")

    dialog, _ = make(qtbot, candidate(), candidate(name="Spotify"), track=refuse)

    dialog.accept_candidate(dialog.remaining_candidates()[0])

    assert "already exists" in dialog.banner.text()
    assert len(dialog.remaining_candidates()) == 2


# ─── Showing its work ─────────────────────────────────────────────────────


def test_the_evidence_is_shown_in_full(qtbot) -> None:
    """It is the reason the user can judge the guess at all."""
    written = "4 charges of about 1,999.00, 30±2 days apart."
    dialog, _ = make(qtbot, candidate(evidence=written))

    assert texts(dialog, "CandidateEvidence") == [written]


def test_confidence_is_shown_in_words_not_a_percentage(qtbot) -> None:
    dialog, _ = make(qtbot, candidate(confidence="high"))

    assert texts(dialog, "CandidateBadge") == ["Very likely"]


def test_confidence_is_on_the_card_as_a_property_too(qtbot) -> None:
    dialog, _ = make(qtbot, candidate(confidence="medium"))

    assert cards(dialog)[0].property("confidence") == "medium"


def test_the_dates_it_was_built_from_are_shown(qtbot) -> None:
    dialog, _ = make(qtbot, candidate())

    seen = texts(dialog, "CandidateSeen")[0]
    assert "05 Jan 2026" in seen
    assert "05 May 2026" in seen
    assert "04 Jun 2026" in seen


def test_the_window_searched_is_named(qtbot) -> None:
    """ "Nothing found" and "nothing was looked at" are different answers."""
    dialog, _ = make(qtbot)

    assert "15 Jun 2025" in dialog.subtitle_label.text()
    assert dialog.title_label.text() == "Nothing new found"


def test_the_header_counts_what_was_found(qtbot) -> None:
    dialog, _ = make(qtbot, candidate(), candidate(name="Spotify"))

    assert dialog.title_label.text() == "2 possible subscriptions found"


def test_the_header_is_singular_for_one(qtbot) -> None:
    dialog, _ = make(qtbot, candidate())

    assert dialog.title_label.text() == "1 possible subscription found"


def test_clearing_the_list_by_tracking_says_so_differently(qtbot) -> None:
    dialog, _ = make(qtbot, candidate())

    dialog.accept_candidate(dialog.remaining_candidates()[0])

    assert dialog.title_label.text() == "That is everything"


# ─── What tracking actually sends ─────────────────────────────────────────


def test_the_subscription_is_anchored_on_the_first_charge(qtbot) -> None:
    """Not the last: the server derives the schedule from the anchor
    (ADR-025), so anchoring on the earliest charge keeps the day it has always
    used."""
    payload = candidate().as_subscription()

    assert payload["start_date"] == "2026-01-05"


def test_the_payload_carries_the_detected_details(qtbot) -> None:
    payload = candidate().as_subscription()

    assert payload["name"] == "Netflix"
    assert payload["amount"] == "499.00"
    assert payload["billing_cycle"] == "monthly"
    assert payload["category_id"] == 5


def test_the_evidence_is_kept_in_the_notes(qtbot) -> None:
    """Six months on, "why is this here?" has an answer."""
    payload = candidate().as_subscription()

    assert "Detected from transaction history" in payload["notes"]
    assert "5 charges" in payload["notes"]


def test_a_candidate_with_no_category_sends_none(qtbot) -> None:
    payload = candidate(category_id=None).as_subscription()

    assert payload["category_id"] is None
