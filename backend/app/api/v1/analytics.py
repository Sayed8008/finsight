"""Analytics endpoints: how things moved, and against what.

Two routes, because they answer two different questions and a screen may want
one without the other. That is the opposite call from the dashboard, which is
deliberately one payload — there, five sections are always shown together.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import CurrentUser, SessionDep
from app.schemas.analytics import ComparisonResponse, TrendResponse
from app.services.analytics_service import (
    DEFAULT_TREND_MONTHS,
    MAX_TREND_MONTHS,
    AnalyticsService,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

TrendMonths = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_TREND_MONTHS,
        description="How many calendar months to include, counting back from the current one.",
    ),
]
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
    "/trend",
    response_model=TrendResponse,
    summary="Income and expense per month",
)
def read_trend(
    current_user: CurrentUser,
    session: SessionDep,
    months: TrendMonths = DEFAULT_TREND_MONTHS,
    as_of: AsOf = None,
) -> TrendResponse:
    """Monthly totals across the last N months, including the current one.

    Months with no transactions come back as zeroes rather than being left
    out. A chart that skips an empty March puts February beside April and makes
    two months of change look like one.
    """
    trend = AnalyticsService(session).trend(current_user.id, months=months, today=as_of)
    return TrendResponse.model_validate(trend)


@router.get(
    "/comparison",
    response_model=ComparisonResponse,
    summary="This period against the one before it",
    responses={422: {"description": "The period ends before it starts"}},
)
def read_comparison(
    current_user: CurrentUser,
    session: SessionDep,
    period_start: PeriodStart = None,
    period_end: PeriodEnd = None,
    as_of: AsOf = None,
) -> ComparisonResponse:
    """Compare a period with the one immediately before it.

    The comparison window is derived rather than asked for: the same length,
    ending the day before. Accepting four dates would let a caller compare a
    month against a fortnight and read the result as a 50% saving.

    Categories from *either* period are listed, biggest movement first. Showing
    only the current period's would hide the most useful finding available —
    something the user stopped spending on.
    """
    comparison = AnalyticsService(session).compare(
        current_user.id,
        start=period_start,
        end=period_end,
        today=as_of,
    )
    return ComparisonResponse.model_validate(comparison)
