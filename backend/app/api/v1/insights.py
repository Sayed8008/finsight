"""The insights endpoint.

One route. The rules run on every request rather than against anything stored
(ADR-015): an insight describes the present, and a cached one describes the
moment it was cached.

ADR-008 applies here too — there is no separate reminders subsystem. "Renewal
in 2 days" is an insight rule, and anywhere the application nags the user is a
rendering of this endpoint rather than a second set of thresholds.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import CurrentUser, SessionDep
from app.schemas.insight import InsightResponse, InsightsResponse
from app.services.insight_service import InsightService

router = APIRouter(prefix="/insights", tags=["insights"])

PeriodStart = Annotated[
    date_type | None,
    Query(description="Start of the period. Defaults to the first of this month."),
]
PeriodEnd = Annotated[
    date_type | None,
    Query(description="End of the period, inclusive. Defaults to the last of this month."),
]
AsOf = Annotated[
    date_type | None,
    Query(description="Day to evaluate against, defaulting to today."),
]


@router.get(
    "",
    response_model=InsightsResponse,
    summary="What is worth knowing right now",
    responses={422: {"description": "The period ends before it starts"}},
)
def read_insights(
    current_user: CurrentUser,
    session: SessionDep,
    period_start: PeriodStart = None,
    period_end: PeriodEnd = None,
    as_of: AsOf = None,
) -> InsightsResponse:
    """Evaluate every rule against this user's current position.

    Ordered by severity, then by size within a severity, so the largest problem
    of the most urgent kind is first. The order is fully determined by the
    data — a list that reshuffles between refreshes reads as broken.

    Every insight carries its own explanation, naming the figures it found and
    what it compared them against.
    """
    service = InsightService(session)
    # One snapshot, used for both the findings and the period they describe.
    # Calling `snapshot()` and then `report()` gathers it twice and doubles
    # every query behind this endpoint — which is what a query-counting test
    # caught here.
    snapshot = service.snapshot(current_user.id, start=period_start, end=period_end, today=as_of)
    report = service.evaluate(snapshot)

    return InsightsResponse(
        period_start=snapshot.period_start,
        period_end=snapshot.period_end,
        insights=[InsightResponse.model_validate(insight) for insight in report.insights],
        needs_attention=report.needs_attention,
        counts=report.counts,
    )
