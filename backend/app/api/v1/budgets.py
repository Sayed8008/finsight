"""Budget endpoints.

Each response carries the budget *and* what it computes to — spent, remaining,
percentage and status. That is the point of the endpoint: the arithmetic is
done where the data is, once, rather than by every client fetching transactions
and summing them.

As elsewhere, no handler takes a user id. Each receives `current_user`,
resolved from the token, so there is nothing in a URL or body to tamper with.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.schemas.budget import BudgetCreate, BudgetResponse, BudgetUpdate
from app.services.budget_service import BudgetService

router = APIRouter(prefix="/budgets", tags=["budgets"])

CategoryFilter = Annotated[int | None, Query(gt=0, description="Only budgets for this category.")]
CurrentOnly = Annotated[
    bool,
    Query(description="Only budgets whose period contains the reference day."),
]
AsOf = Annotated[
    date_type | None,
    Query(
        description="Day to evaluate against, defaulting to today. Determines "
        "`is_current`, `days_remaining`, and which budgets `current_only` keeps.",
    ),
]


@router.get(
    "",
    response_model=list[BudgetResponse],
    summary="List budgets with their utilisation",
)
def list_budgets(
    current_user: CurrentUser,
    session: SessionDep,
    category_id: CategoryFilter = None,
    current_only: CurrentOnly = False,
    as_of: AsOf = None,
) -> list[BudgetResponse]:
    """This user's budgets, newest period first.

    Not paginated: budgets are counted in tens, not thousands, and the screen
    shows them as cards rather than as a table.

    Two queries regardless of how many come back — one for the rows, one
    aggregate for the spend against all of them.
    """
    snapshots = BudgetService(session).list_budgets(
        current_user.id,
        category_id=category_id,
        current_only=current_only,
        today=as_of,
    )
    return [BudgetResponse.model_validate(snapshot) for snapshot in snapshots]


@router.post(
    "",
    response_model=BudgetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Set a budget",
    responses={
        404: {"description": "No such category for this user"},
        409: {"description": "A budget for that category already covers part of the period"},
        422: {"description": "The category is not an expense category, or is deactivated"},
    },
)
def create_budget(
    payload: BudgetCreate,
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> BudgetResponse:
    """Set a spending limit for one category over one period."""
    snapshot = BudgetService(session).create(current_user.id, payload.model_dump(), today=as_of)
    return BudgetResponse.model_validate(snapshot)


@router.get(
    "/{budget_id}",
    response_model=BudgetResponse,
    summary="Get one budget",
    responses={404: {"description": "No such budget for this user"}},
)
def read_budget(
    budget_id: int,
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> BudgetResponse:
    snapshot = BudgetService(session).get(current_user.id, budget_id, today=as_of)
    return BudgetResponse.model_validate(snapshot)


@router.patch(
    "/{budget_id}",
    response_model=BudgetResponse,
    summary="Change a budget's amount, period or category",
    responses={
        404: {"description": "No such budget, or no such category, for this user"},
        409: {"description": "The new period would overlap an existing budget"},
        422: {"description": "The resulting period or category would be invalid"},
    },
)
def update_budget(
    budget_id: int,
    payload: BudgetUpdate,
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> BudgetResponse:
    """Apply a partial update; omitted fields are left alone."""
    snapshot = BudgetService(session).update(
        current_user.id,
        budget_id,
        payload.model_dump(exclude_unset=True),
        today=as_of,
    )
    return BudgetResponse.model_validate(snapshot)


@router.delete(
    "/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a budget",
    responses={404: {"description": "No such budget for this user"}},
)
def delete_budget(
    budget_id: int,
    current_user: CurrentUser,
    session: SessionDep,
) -> None:
    """Delete a budget. A plan, not a record — nothing references it."""
    BudgetService(session).delete(current_user.id, budget_id)
    return None
