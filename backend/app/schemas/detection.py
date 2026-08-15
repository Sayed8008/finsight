"""Response models for subscription detection.

Every candidate carries its evidence. A confidence level without the charges it
was derived from cannot be checked, and an unverifiable guess about someone's
money is not worth offering (ADR-007).
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict

from app.core.money import MoneyOut
from app.models.enums import BillingCycle
from app.services.recurrence import Confidence


class CandidateResponse(BaseModel):
    """A possible subscription, with everything needed to judge it."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    amount: MoneyOut
    billing_cycle: BillingCycle
    confidence: Confidence
    #: The sentence the user checks the guess against — "4 charges of 499.00,
    #: 30±1 days apart". This is the confidence, in the form that can be
    #: verified.
    evidence: str
    occurrences: int
    first_seen: date_type
    last_seen: date_type
    median_interval_days: int
    interval_spread_days: int
    #: When the next charge would fall if the pattern holds. A starting point
    #: for the user to confirm, never a fact.
    next_expected: date_type
    #: The transactions this was built from, so the interface can show its work.
    transaction_ids: list[int]
    #: What these charges were mostly filed under, offered as a suggestion.
    category_id: int | None


class DetectionResponse(BaseModel):
    """What detection found, most believable first."""

    #: The window searched, so "nothing found" can be told apart from "nothing
    #: was looked at".
    searched_from: date_type
    searched_to: date_type
    candidates: list[CandidateResponse]
