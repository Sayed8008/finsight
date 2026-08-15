"""Subscription endpoints.

`next_billing_date` appears in every response and in no request body. It is
derived from the start date and the cycle, so accepting it would allow a
subscription whose three fields disagree. `POST /{id}/renew` is how it moves.

`/summary` is declared before `/{subscription_id}`, for the same reason
`/payment-methods` is on the transactions router: FastAPI matches in
declaration order, and the other way round "summary" would be handed to the
`int` path parameter and rejected.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.models.enums import SubscriptionStatus
from app.schemas.subscription import (
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionSummary,
    SubscriptionUpdate,
)
from app.services.subscription_service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

MAX_LOOKAHEAD_DAYS = 366

StatusFilter = Annotated[
    SubscriptionStatus | None,
    Query(description="Only active, paused or cancelled subscriptions."),
]
CategoryFilter = Annotated[int | None, Query(gt=0, description="Only this category.")]
DueWithin = Annotated[
    int | None,
    Query(
        ge=0,
        le=MAX_LOOKAHEAD_DAYS,
        description="Only subscriptions renewing within this many days.",
    ),
]
AsOf = Annotated[
    date_type | None,
    Query(
        description="Day to evaluate against, defaulting to today. Determines "
        "`days_until_renewal` and `is_due_soon`.",
    ),
]


@router.get(
    "/summary",
    response_model=SubscriptionSummary,
    summary="Total recurring commitment",
)
def read_summary(
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> SubscriptionSummary:
    """What the user is committed to each month and each year.

    Paused and cancelled subscriptions are counted but excluded from the
    totals: a paused subscription is not being charged, so including it would
    overstate what is actually paid.
    """
    commitment = SubscriptionService(session).summary(current_user.id, today=as_of)
    return SubscriptionSummary.model_validate(commitment, from_attributes=True)


@router.get(
    "",
    response_model=list[SubscriptionResponse],
    summary="List subscriptions",
)
def list_subscriptions(
    current_user: CurrentUser,
    session: SessionDep,
    subscription_status: StatusFilter = None,
    category_id: CategoryFilter = None,
    due_within_days: DueWithin = None,
    as_of: AsOf = None,
) -> list[SubscriptionResponse]:
    """This user's subscriptions, soonest renewal first.

    `due_within_days` answers "what is coming up". Combined with
    `subscription_status=active` it is served by the
    `(user_id, status, next_billing_date)` index.
    """
    views = SubscriptionService(session).list_subscriptions(
        current_user.id,
        status=subscription_status,
        category_id=category_id,
        due_within_days=due_within_days,
        today=as_of,
    )
    return [SubscriptionResponse.model_validate(view) for view in views]


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Track a subscription",
    responses={404: {"description": "No such category for this user"}},
)
def create_subscription(
    payload: SubscriptionCreate,
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> SubscriptionResponse:
    """Start tracking a recurring payment.

    FinSight records subscriptions; it never contacts a payment provider and
    never charges anything.
    """
    view = SubscriptionService(session).create(current_user.id, payload.model_dump(), today=as_of)
    return SubscriptionResponse.model_validate(view)


@router.get(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    summary="Get one subscription",
    responses={404: {"description": "No such subscription for this user"}},
)
def read_subscription(
    subscription_id: int,
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> SubscriptionResponse:
    view = SubscriptionService(session).get(current_user.id, subscription_id, today=as_of)
    return SubscriptionResponse.model_validate(view)


@router.patch(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    summary="Edit a subscription",
    responses={
        404: {"description": "No such subscription, or no such category, for this user"},
        422: {"description": "The resulting dates would be invalid"},
    },
)
def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> SubscriptionResponse:
    """Apply a partial update.

    Changing the start date or the cycle recomputes `next_billing_date`,
    because leaving it alone would describe a schedule the subscription's own
    anchor and cycle contradict.
    """
    view = SubscriptionService(session).update(
        current_user.id,
        subscription_id,
        payload.model_dump(exclude_unset=True),
        today=as_of,
    )
    return SubscriptionResponse.model_validate(view)


@router.post(
    "/{subscription_id}/renew",
    response_model=SubscriptionResponse,
    summary="Record a charge and move to the next one",
    responses={
        404: {"description": "No such subscription for this user"},
        422: {"description": "The subscription is cancelled"},
    },
)
def renew_subscription(
    subscription_id: int,
    current_user: CurrentUser,
    session: SessionDep,
    as_of: AsOf = None,
) -> SubscriptionResponse:
    """Advance to the next billing date.

    The new date is computed from the original start date, not by adding a
    cycle to the current one — stepping from a clamped date is how a
    subscription billing on the 31st quietly slips to the 28th and stays there.

    A subscription that passes its own end date is cancelled instead of being
    given a charge that will never happen.
    """
    view = SubscriptionService(session).renew(current_user.id, subscription_id, today=as_of)
    return SubscriptionResponse.model_validate(view)


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a subscription",
    responses={404: {"description": "No such subscription for this user"}},
)
def delete_subscription(
    subscription_id: int,
    current_user: CurrentUser,
    session: SessionDep,
) -> None:
    """Delete outright.

    Distinct from cancelling, which keeps the record and its history. Deleting
    is for something tracked by mistake.
    """
    SubscriptionService(session).delete(current_user.id, subscription_id)
    return None
