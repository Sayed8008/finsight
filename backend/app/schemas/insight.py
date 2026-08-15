"""Response models for insights.

Nothing here is stored. Insights are recomputed on every read (ADR-015),
because an insight is a statement about *now* — one cached yesterday describes
yesterday and would be quietly wrong.
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict

from app.services.insight_rules import Severity


class InsightResponse(BaseModel):
    """One finding, and the explanation for it."""

    model_config = ConfigDict(from_attributes=True)

    #: Stable across wording changes, so a client can key on it.
    code: str
    severity: Severity
    title: str
    #: Always names the figures involved. This is the feature — an insight that
    #: cannot say why it fired is worse than no insight.
    detail: str
    #: Present when the finding is about a particular category or
    #: subscription, so the interface can link onward to it.
    category_id: int | None
    subscription_id: int | None


class InsightsResponse(BaseModel):
    """Everything the rules found for a period, most urgent first."""

    period_start: date_type
    period_end: date_type
    insights: list[InsightResponse]
    #: Critical plus warning. What a badge would show.
    needs_attention: int
    #: How many of each severity, for a summary line.
    counts: dict[Severity, int]
