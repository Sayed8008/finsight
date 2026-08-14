"""Category endpoints.

Every handler receives `current_user` — a `User` object resolved from the
access token, not an id read from the request — and passes `current_user.id`
to the service. There is no user id anywhere in these URLs or bodies, so
there is nothing for a caller to tamper with in order to reach another
account's data.

There is no DELETE. A category is retired by `PATCH {"is_active": false}`;
see ADR-020 for why.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.v1.deps import CurrentUser, SessionDep
from app.models.enums import CategoryType
from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from app.services.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get(
    "",
    response_model=list[CategoryResponse],
    summary="List categories",
)
def list_categories(
    current_user: CurrentUser,
    session: SessionDep,
    category_type: CategoryType | None = Query(
        default=None,
        description="Return only income or only expense categories.",
    ),
    include_inactive: bool = Query(
        default=False,
        description="Include deactivated categories. Off by default, so the "
        "form pickers that call this endpoint cannot offer a retired category.",
    ),
) -> list[CategoryResponse]:
    """This user's categories, ordered by type then name.

    Not paginated: a user has a few dozen categories, and the client loads the
    whole list once per view to label transaction rows without a query per row.
    """
    categories = CategoryService(session).list_categories(
        current_user.id,
        category_type=category_type,
        include_inactive=include_inactive,
    )
    return [CategoryResponse.model_validate(category) for category in categories]


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    responses={409: {"description": "A category with that name and type exists"}},
)
def create_category(
    payload: CategoryCreate,
    current_user: CurrentUser,
    session: SessionDep,
) -> CategoryResponse:
    """Add a category alongside the defaults seeded at registration."""
    category = CategoryService(session).create(
        current_user.id,
        name=payload.name,
        category_type=payload.category_type,
        color=payload.color,
        icon=payload.icon,
    )
    return CategoryResponse.model_validate(category)


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Get one category",
    responses={404: {"description": "No such category for this user"}},
)
def read_category(
    category_id: int,
    current_user: CurrentUser,
    session: SessionDep,
) -> CategoryResponse:
    """One category.

    Another user's category id answers 404, not 403 — a 403 would confirm the
    row exists.
    """
    category = CategoryService(session).get(current_user.id, category_id)
    return CategoryResponse.model_validate(category)


@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Rename, recolour, deactivate or restore a category",
    responses={
        404: {"description": "No such category for this user"},
        409: {"description": "Another category already has that name"},
    },
)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    current_user: CurrentUser,
    session: SessionDep,
) -> CategoryResponse:
    """Apply a partial update.

    `exclude_unset=True` is what makes this a PATCH: only the fields the
    client actually sent are passed on, so omitting `color` leaves the colour
    alone instead of clearing it. Sending `"color": null` explicitly does
    clear it.
    """
    category = CategoryService(session).update(
        current_user.id,
        category_id,
        payload.model_dump(exclude_unset=True),
    )
    return CategoryResponse.model_validate(category)
