"""End-to-end tests for the category endpoints.

The isolation tests at the bottom are the important ones: every endpoint that
takes a category id is handed another account's id and must answer 404. One
missing `WHERE user_id = ?` is all it takes to expose someone else's data, and
that mistake is invisible when tests only ever use a single account.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.default_categories import DEFAULT_CATEGORIES
from tests.conftest import Account

CATEGORIES = "/api/v1/categories"

NEW_CATEGORY = {"name": "Gym", "category_type": "expense", "color": "#3366ff"}


def create(client: TestClient, account: Account, **overrides: object) -> dict:
    response = client.post(CATEGORIES, json={**NEW_CATEGORY, **overrides}, headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()


def names(payload: list[dict]) -> set[str]:
    return {category["name"] for category in payload}


# ─── Listing ──────────────────────────────────────────────────────────────


def test_listing_returns_the_seeded_defaults(client: TestClient, account: Account) -> None:
    response = client.get(CATEGORIES, headers=account.headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(DEFAULT_CATEGORIES)
    assert names(body) == {default.name for default in DEFAULT_CATEGORIES}


def test_listing_requires_authentication(client: TestClient) -> None:
    assert client.get(CATEGORIES).status_code == 401


def test_listing_never_exposes_the_user_id(client: TestClient, account: Account) -> None:
    """A caller only ever sees their own rows, so the column is noise at best."""
    body = client.get(CATEGORIES, headers=account.headers).json()

    assert "user_id" not in body[0]


def test_listing_groups_income_before_expense(client: TestClient, account: Account) -> None:
    """Ordering by an ENUM column sorts by *declaration* order in MySQL.

    `CategoryType` declares INCOME first, so income categories come first —
    not alphabetically, where "expense" would win. That is the behaviour
    relied on, so it is asserted rather than assumed. An unordered SELECT, by
    contrast, may return rows differently on any given day.
    """
    body = client.get(CATEGORIES, headers=account.headers).json()

    types = [category["category_type"] for category in body]
    assert types == sorted(types, key=["income", "expense"].index)


def test_listing_is_sorted_by_name_within_each_type(client: TestClient, account: Account) -> None:
    body = client.get(CATEGORIES, headers=account.headers).json()

    for category_type in ("income", "expense"):
        group = [c["name"] for c in body if c["category_type"] == category_type]
        assert group == sorted(group)


def test_listing_can_be_filtered_to_one_type(client: TestClient, account: Account) -> None:
    body = client.get(
        CATEGORIES, params={"category_type": "income"}, headers=account.headers
    ).json()

    assert body
    assert {category["category_type"] for category in body} == {"income"}


def test_an_unknown_type_filter_is_rejected(client: TestClient, account: Account) -> None:
    response = client.get(CATEGORIES, params={"category_type": "savings"}, headers=account.headers)

    assert response.status_code == 422


def test_deactivated_categories_are_hidden_by_default(client: TestClient, account: Account) -> None:
    """The pickers that call this endpoint must not offer a retired category."""
    category = create(client, account)
    client.patch(
        f"{CATEGORIES}/{category['id']}", json={"is_active": False}, headers=account.headers
    )

    visible = client.get(CATEGORIES, headers=account.headers).json()

    assert "Gym" not in names(visible)


def test_deactivated_categories_can_be_asked_for(client: TestClient, account: Account) -> None:
    category = create(client, account)
    client.patch(
        f"{CATEGORIES}/{category['id']}", json={"is_active": False}, headers=account.headers
    )

    body = client.get(CATEGORIES, params={"include_inactive": True}, headers=account.headers).json()

    assert "Gym" in names(body)


# ─── Creating ─────────────────────────────────────────────────────────────


def test_creating_a_category(client: TestClient, account: Account) -> None:
    body = create(client, account)

    assert body["name"] == "Gym"
    assert body["category_type"] == "expense"
    assert body["color"] == "#3366ff"
    assert body["is_active"] is True


def test_a_created_category_appears_in_the_list(client: TestClient, account: Account) -> None:
    create(client, account)

    assert "Gym" in names(client.get(CATEGORIES, headers=account.headers).json())


def test_a_duplicate_name_within_a_type_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        CATEGORIES, json={**NEW_CATEGORY, "name": "Food"}, headers=account.headers
    )

    assert response.status_code == 409


def test_a_duplicate_name_is_matched_case_insensitively(
    client: TestClient, account: Account
) -> None:
    response = client.post(
        CATEGORIES, json={**NEW_CATEGORY, "name": "food"}, headers=account.headers
    )

    assert response.status_code == 409


def test_the_same_name_may_exist_once_per_type(client: TestClient, account: Account) -> None:
    """ "Other" is a seeded expense category; an income "Other" is legitimate."""
    response = client.post(
        CATEGORIES,
        json={"name": "Other", "category_type": "income"},
        headers=account.headers,
    )

    assert response.status_code == 201


def test_two_users_may_each_have_a_category_of_the_same_name(
    client: TestClient, account: Account, other_account: Account
) -> None:
    """Uniqueness is per user; categories are not shared (ADR-006)."""
    create(client, account)

    assert create(client, other_account)["name"] == "Gym"


def test_a_blank_name_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        CATEGORIES, json={**NEW_CATEGORY, "name": "   "}, headers=account.headers
    )

    assert response.status_code == 422


def test_surrounding_and_repeated_whitespace_is_collapsed(
    client: TestClient, account: Account
) -> None:
    """Otherwise "Gym  Fees" and "Gym Fees" could both exist."""
    assert create(client, account, name="  Gym   Fees  ")["name"] == "Gym Fees"


def test_a_malformed_colour_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        CATEGORIES, json={**NEW_CATEGORY, "color": "blue"}, headers=account.headers
    )

    assert response.status_code == 422


def test_a_colour_is_stored_lowercased(client: TestClient, account: Account) -> None:
    assert create(client, account, color="#33AAFF")["color"] == "#33aaff"


def test_colour_is_optional(client: TestClient, account: Account) -> None:
    response = client.post(
        CATEGORIES, json={"name": "Gym", "category_type": "expense"}, headers=account.headers
    )

    assert response.status_code == 201
    assert response.json()["color"] is None


def test_creating_requires_authentication(client: TestClient) -> None:
    assert client.post(CATEGORIES, json=NEW_CATEGORY).status_code == 401


# ─── Updating ─────────────────────────────────────────────────────────────


def test_renaming_a_category(client: TestClient, account: Account) -> None:
    category = create(client, account)

    response = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"name": "Fitness"}, headers=account.headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Fitness"


def test_a_partial_update_leaves_omitted_fields_alone(client: TestClient, account: Account) -> None:
    """This is what separates PATCH from PUT: absent means "do not touch"."""
    category = create(client, account)

    body = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"name": "Fitness"}, headers=account.headers
    ).json()

    assert body["color"] == "#3366ff"


def test_an_explicit_null_clears_a_field(client: TestClient, account: Account) -> None:
    category = create(client, account)

    body = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"color": None}, headers=account.headers
    ).json()

    assert body["color"] is None


def test_renaming_onto_an_existing_name_is_rejected(client: TestClient, account: Account) -> None:
    category = create(client, account)

    response = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"name": "Food"}, headers=account.headers
    )

    assert response.status_code == 409


def test_a_category_may_keep_its_own_name(client: TestClient, account: Account) -> None:
    """Renaming "Gym" to "Gym" must not collide with itself."""
    category = create(client, account)

    response = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"name": "Gym"}, headers=account.headers
    )

    assert response.status_code == 200


def test_a_category_may_be_recased(client: TestClient, account: Account) -> None:
    category = create(client, account)

    response = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"name": "GYM"}, headers=account.headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "GYM"


def test_renaming_may_reuse_a_name_from_the_other_type(
    client: TestClient, account: Account
) -> None:
    category = create(client, account, category_type="income", name="Bonus")

    response = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"name": "Food"}, headers=account.headers
    )

    assert response.status_code == 200


def test_the_type_cannot_be_changed(client: TestClient, account: Account) -> None:
    """Flipping a type would invalidate every transaction filed under it."""
    category = create(client, account)

    body = client.patch(
        f"{CATEGORIES}/{category['id']}",
        json={"category_type": "income"},
        headers=account.headers,
    ).json()

    assert body["category_type"] == "expense"


def test_deactivating_and_restoring_a_category(client: TestClient, account: Account) -> None:
    category = create(client, account)

    deactivated = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"is_active": False}, headers=account.headers
    )
    assert deactivated.json()["is_active"] is False

    restored = client.patch(
        f"{CATEGORIES}/{category['id']}", json={"is_active": True}, headers=account.headers
    )
    assert restored.json()["is_active"] is True


def test_an_empty_patch_body_is_accepted_and_changes_nothing(
    client: TestClient, account: Account
) -> None:
    category = create(client, account)

    response = client.patch(f"{CATEGORIES}/{category['id']}", json={}, headers=account.headers)

    assert response.status_code == 200
    assert response.json() == category


def test_updating_requires_authentication(client: TestClient, account: Account) -> None:
    category = create(client, account)

    assert (
        client.patch(f"{CATEGORIES}/{category['id']}", json={"name": "Fitness"}).status_code == 401
    )


# ─── One user's data is invisible to another ──────────────────────────────


def test_reading_another_users_category_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    """404 rather than 403 — a 403 would confirm the row exists."""
    theirs = create(client, other_account)

    response = client.get(f"{CATEGORIES}/{theirs['id']}", headers=account.headers)

    assert response.status_code == 404


def test_updating_another_users_category_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = create(client, other_account)

    response = client.patch(
        f"{CATEGORIES}/{theirs['id']}", json={"name": "Hijacked"}, headers=account.headers
    )

    assert response.status_code == 404


def test_a_failed_cross_user_update_changes_nothing(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = create(client, other_account)

    client.patch(f"{CATEGORIES}/{theirs['id']}", json={"name": "Hijacked"}, headers=account.headers)

    unchanged = client.get(f"{CATEGORIES}/{theirs['id']}", headers=other_account.headers).json()
    assert unchanged["name"] == "Gym"


def test_listing_shows_only_your_own_categories(
    client: TestClient, account: Account, other_account: Account
) -> None:
    create(client, other_account, name="Their Private Category")

    mine = client.get(CATEGORIES, headers=account.headers).json()

    assert "Their Private Category" not in names(mine)


def test_a_nonexistent_category_is_a_404(client: TestClient, account: Account) -> None:
    assert client.get(f"{CATEGORIES}/999999", headers=account.headers).status_code == 404
