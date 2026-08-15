"""The dashboard endpoint.

One route, one payload. The screen it serves shows totals, a spending
breakdown, recent activity, budget health and subscription commitment — five
things that would otherwise be five requests, arriving at five different
moments and disagreeing with each other while they load.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import CurrentUser, SessionDep
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

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
    response_model=DashboardResponse,
    summary="Everything the first screen needs",
    responses={422: {"description": "The period ends before it starts"}},
)
def read_dashboard(
    current_user: CurrentUser,
    session: SessionDep,
    period_start: PeriodStart = None,
    period_end: PeriodEnd = None,
    as_of: AsOf = None,
) -> DashboardResponse:
    """Summarise a period, defaulting to the current month.

    "This month" is the default because it is the period the user is inside —
    last month is history, and the year to date answers a different question.

    Budget health counts only budgets running on the reference day: one that
    ended last month cannot need attention, and counting it would leave the
    dashboard permanently amber.
    """
    dashboard = DashboardService(session).build(
        current_user.id,
        start=period_start,
        end=period_end,
        today=as_of,
    )
    return DashboardResponse.model_validate(dashboard)
