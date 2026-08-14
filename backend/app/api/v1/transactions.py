"""Transaction endpoints.

Filters arrive as query parameters and are declared individually rather than
as one opaque object, so that `/docs` lists each with its own description and
constraints — the interactive documentation is the API's specification here.
They are then collected into a `TransactionFilters` value object, which is what
the repository takes (ADR-021).

As with categories, no handler accepts a user id. Every one receives
`current_user`, resolved from the access token, and passes `current_user.id`
inward. There is nothing in a URL or body for a caller to change in order to
reach another account's rows.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.core.money import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from app.models.enums import TransactionType
from app.repositories.transaction_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SortDirection,
    SortField,
    TransactionFilters,
)
from app.schemas.common import Page
from app.schemas.transaction import (
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Filter parameters, annotated once each. Bounds live here as well as in the
# repository's own validation: this way a bad request is rejected before any
# query is built, and `/docs` shows the limits.
DateFrom = Annotated[date_type | None, Query(description="Earliest date to include (inclusive).")]
DateTo = Annotated[date_type | None, Query(description="Latest date to include (inclusive).")]
TypeFilter = Annotated[TransactionType | None, Query(description="Only income, or only expenses.")]
CategoryFilter = Annotated[int | None, Query(gt=0, description="Only this category.")]
MethodFilter = Annotated[
    str | None,
    Query(
        max_length=50,
        description="Exact payment method. `GET /transactions/payment-methods` "
        "lists the values in use.",
    ),
]
AmountMin = Annotated[
    Decimal | None,
    Query(ge=0, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES),
]
AmountMax = Annotated[
    Decimal | None,
    Query(ge=0, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES),
]
Search = Annotated[
    str | None,
    Query(max_length=255, description="Case-insensitive substring of the description."),
]
PageNumber = Annotated[int, Query(ge=1, description="1-based page number.")]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page.")]


# `/payment-methods` is declared before `/{transaction_id}` deliberately.
# FastAPI matches routes in declaration order, and the other way round
# "payment-methods" would be handed to the `int` path parameter and rejected
# as invalid rather than reaching this handler.
@router.get(
    "/payment-methods",
    response_model=list[str],
    summary="Payment methods in use",
)
def list_payment_methods(current_user: CurrentUser, session: SessionDep) -> list[str]:
    """The distinct payment methods this user has recorded.

    `payment_method` is free text rather than a table, so this is what lets the
    filter bar offer the values actually in use instead of asking the user to
    remember how they spelled "bKash" last time.
    """
    return TransactionService(session).payment_methods(current_user.id)


@router.get(
    "",
    response_model=Page[TransactionResponse],
    summary="List transactions",
    responses={422: {"description": "A filter or page parameter is out of range"}},
)
def list_transactions(
    current_user: CurrentUser,
    session: SessionDep,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    transaction_type: TypeFilter = None,
    category_id: CategoryFilter = None,
    payment_method: MethodFilter = None,
    amount_min: AmountMin = None,
    amount_max: AmountMax = None,
    search: Search = None,
    page: PageNumber = 1,
    page_size: PageSize = DEFAULT_PAGE_SIZE,
    sort_by: SortField = SortField.DATE,
    order: SortDirection = SortDirection.DESC,
) -> Page[TransactionResponse]:
    """One page of transactions, newest first unless told otherwise.

    Every filter is optional and they combine. Filtering, sorting and paging
    all happen in SQL, so `total` describes the whole matching set rather than
    the page (ADR-021).
    """
    filters = TransactionFilters(
        date_from=date_from,
        date_to=date_to,
        transaction_type=transaction_type,
        category_id=category_id,
        payment_method=payment_method,
        amount_min=amount_min,
        amount_max=amount_max,
        search=search,
    )

    rows, total = TransactionService(session).list_transactions(
        current_user.id,
        filters,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        direction=order,
    )

    return Page[TransactionResponse](
        items=[TransactionResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a transaction",
    responses={
        404: {"description": "No such category for this user"},
        422: {"description": "The category's type does not match, or it is deactivated"},
    },
)
def create_transaction(
    payload: TransactionCreate,
    current_user: CurrentUser,
    session: SessionDep,
) -> TransactionResponse:
    """Record an income or expense."""
    transaction = TransactionService(session).create(current_user.id, payload.model_dump())
    return TransactionResponse.model_validate(transaction)


@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get one transaction",
    responses={404: {"description": "No such transaction for this user"}},
)
def read_transaction(
    transaction_id: int,
    current_user: CurrentUser,
    session: SessionDep,
) -> TransactionResponse:
    transaction = TransactionService(session).get(current_user.id, transaction_id)
    return TransactionResponse.model_validate(transaction)


@router.patch(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Edit a transaction",
    responses={
        404: {"description": "No such transaction, or no such category, for this user"},
        422: {"description": "The resulting type and category would disagree"},
    },
)
def update_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    current_user: CurrentUser,
    session: SessionDep,
) -> TransactionResponse:
    """Change one or more fields.

    `exclude_unset=True` keeps this a PATCH: an omitted field is left alone
    rather than overwritten with null.
    """
    transaction = TransactionService(session).update(
        current_user.id,
        transaction_id,
        payload.model_dump(exclude_unset=True),
    )
    return TransactionResponse.model_validate(transaction)


@router.delete(
    "/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a transaction",
    responses={404: {"description": "No such transaction for this user"}},
)
def delete_transaction(
    transaction_id: int,
    current_user: CurrentUser,
    session: SessionDep,
) -> None:
    """Delete a transaction permanently.

    A real delete, unlike a category (ADR-020): nothing references a
    transaction, so there is nothing to orphan.
    """
    TransactionService(session).delete(current_user.id, transaction_id)
    return None
