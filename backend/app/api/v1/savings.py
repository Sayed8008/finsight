"""Savings journey endpoint: what each completed month kept.

One route. The screen shows a summary, a chart, badges and sentences that all
describe the same history, so splitting them would mean four requests that
could disagree with each other — the same reasoning as the dashboard.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import CurrentUser, SessionDep
from app.schemas.savings import SavingsJourneyResponse
from app.services.savings_service import (
    ALL_TIME,
    DEFAULT_SAVINGS_MONTHS,
    MAX_SAVINGS_MONTHS,
    SavingsService,
)

router = APIRouter(prefix="/savings", tags=["savings"])

SavingsMonths = Annotated[
    int,
    Query(
        ge=ALL_TIME,
        le=MAX_SAVINGS_MONTHS,
        description=(
            "How many completed months to include, counting back from the last "
            f"completed one. {ALL_TIME} means the whole history."
        ),
    ),
]
AsOf = Annotated[
    date_type | None,
    Query(description="Day to evaluate against, defaulting to today."),
]


@router.get(
    "",
    response_model=SavingsJourneyResponse,
    summary="Monthly savings history",
)
def read_savings(
    current_user: CurrentUser,
    session: SessionDep,
    months: SavingsMonths = DEFAULT_SAVINGS_MONTHS,
    as_of: AsOf = None,
) -> SavingsJourneyResponse:
    """Completed months only, oldest first.

    The month in progress is excluded: on the 3rd it shows a salary and almost
    no spending, and on the 30th the reverse, so including it would make "are
    you improving?" depend on the day the screen was opened.

    Nothing here is stored. Each month is recomputed from the same aggregate
    the trend chart uses, so a CSV import or an edited transaction is reflected
    immediately rather than leaving a stale snapshot behind (ADR-015).

    Scoped to the signed-in user by `current_user`, like every other route —
    there is no path or query parameter that names a user, so one account's
    history cannot be requested from another's session.
    """
    journey = SavingsService(session).journey(
        current_user.id, months=months, today=as_of
    )
    return SavingsJourneyResponse.model_validate(journey)
