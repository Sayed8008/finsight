"""End-to-end tests for the transaction endpoints.

Three groups matter most:

  * the type/category rule — an expense must not be filed under an income
    category, because every later total trusts that pair;
  * the wire format — amounts must arrive as JSON *strings* (ADR-003). This is
    asserted against the raw response text, not the parsed body, because
    `json.loads` would turn a number back into something that compares equal
    to the string's value and hide the very thing being checked;
  * isolation — every endpoint taking an id is handed another account's id and
    must answer 404.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import Account

TRANSACTIONS = "/api/v1/transactions"
CATEGORIES = "/api/v1/categories"


def category_id(client: TestClient, account: Account, name: str) -> int:
    """The id of one of the categories seeded at registration."""
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(category["id"] for category in body if category["name"] == name)


def expense(client: TestClient, account: Account, **overrides: object) -> dict:
    payload = {
        "amount": "250.00",
        "transaction_type": "expense",
        "category_id": category_id(client, account, "Food"),
        "date": "2026-03-15",
        "description": "Lunch at campus",
        "payment_method": "cash",
    }
    response = client.post(TRANSACTIONS, json={**payload, **overrides}, headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()


def income(client: TestClient, account: Account, **overrides: object) -> dict:
    payload = {
        "amount": "45000.00",
        "transaction_type": "income",
        "category_id": category_id(client, account, "Salary"),
        "date": "2026-03-01",
        "description": "March salary",
        "payment_method": "bank",
    }
    response = client.post(TRANSACTIONS, json={**payload, **overrides}, headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()


# ─── Creating ─────────────────────────────────────────────────────────────


def test_recording_an_expense(client: TestClient, account: Account) -> None:
    body = expense(client, account)

    assert body["amount"] == "250.00"
    assert body["transaction_type"] == "expense"
    assert body["description"] == "Lunch at campus"
    assert body["category"]["name"] == "Food"


def test_the_category_is_embedded_not_just_referenced(client: TestClient, account: Account) -> None:
    """The table shows a name and colour per row; an id alone would need a lookup."""
    body = expense(client, account)

    assert set(body["category"]) == {"id", "name", "category_type", "color"}
    assert body["category"]["color"] is not None


def test_creating_requires_authentication(client: TestClient, account: Account) -> None:
    payload = {
        "amount": "250.00",
        "transaction_type": "expense",
        "category_id": category_id(client, account, "Food"),
        "date": "2026-03-15",
    }

    assert client.post(TRANSACTIONS, json=payload).status_code == 401


def test_a_description_is_optional(client: TestClient, account: Account) -> None:
    assert expense(client, account, description=None)["description"] is None


def test_a_whitespace_only_description_becomes_null(client: TestClient, account: Account) -> None:
    """Three spaces is not data; normalising at the boundary spares everything downstream."""
    assert expense(client, account, description="   ")["description"] is None


def test_a_zero_amount_is_rejected(client: TestClient, account: Account) -> None:
    """Direction is carried by the type, so an amount of zero means nothing."""
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "0.00",
            "transaction_type": "expense",
            "category_id": category_id(client, account, "Food"),
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_a_negative_amount_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "-250.00",
            "transaction_type": "expense",
            "category_id": category_id(client, account, "Food"),
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_more_than_two_decimal_places_is_rejected(client: TestClient, account: Account) -> None:
    """Better a 422 than a silent truncation by DECIMAL(14,2)."""
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "250.005",
            "transaction_type": "expense",
            "category_id": category_id(client, account, "Food"),
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_a_malformed_date_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "250.00",
            "transaction_type": "expense",
            "category_id": category_id(client, account, "Food"),
            "date": "15-03-2026",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


# ─── The type/category rule ───────────────────────────────────────────────


def test_an_expense_cannot_use_an_income_category(client: TestClient, account: Account) -> None:
    """Every later total — dashboard, budgets, analytics — trusts this pair."""
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "250.00",
            "transaction_type": "expense",
            "category_id": category_id(client, account, "Salary"),
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 422
    assert "expense category" in response.json()["detail"]


def test_income_cannot_use_an_expense_category(client: TestClient, account: Account) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "250.00",
            "transaction_type": "income",
            "category_id": category_id(client, account, "Food"),
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_changing_the_type_alone_cannot_break_the_pair(
    client: TestClient, account: Account
) -> None:
    """The check runs against the result of the change, not the field that was sent."""
    transaction = expense(client, account)

    response = client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={"transaction_type": "income"},
        headers=account.headers,
    )

    assert response.status_code == 422


def test_changing_the_category_alone_cannot_break_the_pair(
    client: TestClient, account: Account
) -> None:
    transaction = expense(client, account)

    response = client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={"category_id": category_id(client, account, "Salary")},
        headers=account.headers,
    )

    assert response.status_code == 422


def test_changing_both_together_is_allowed(client: TestClient, account: Account) -> None:
    """An expense mis-recorded as income must be correctable in one request."""
    transaction = expense(client, account)

    response = client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={
            "transaction_type": "income",
            "category_id": category_id(client, account, "Salary"),
        },
        headers=account.headers,
    )

    assert response.status_code == 200
    assert response.json()["category"]["name"] == "Salary"


# ─── Categories that are missing or retired ───────────────────────────────


def test_an_unknown_category_is_a_404(client: TestClient, account: Account) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "250.00",
            "transaction_type": "expense",
            "category_id": 999999,
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 404


def test_another_users_category_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    """A transaction must not become a way to enumerate someone else's categories."""
    theirs = category_id(client, other_account, "Food")

    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "250.00",
            "transaction_type": "expense",
            "category_id": theirs,
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 404


def test_a_deactivated_category_accepts_no_new_transactions(
    client: TestClient, account: Account
) -> None:
    food = category_id(client, account, "Food")
    client.patch(f"{CATEGORIES}/{food}", json={"is_active": False}, headers=account.headers)

    response = client.post(
        TRANSACTIONS,
        json={
            "amount": "250.00",
            "transaction_type": "expense",
            "category_id": food,
            "date": "2026-03-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 422
    assert "deactivated" in response.json()["detail"]


def test_an_existing_transaction_survives_its_category_being_retired(
    client: TestClient, account: Account
) -> None:
    """Deactivating a category must not freeze the history already filed under it."""
    transaction = expense(client, account)
    food = category_id(client, account, "Food")
    client.patch(f"{CATEGORIES}/{food}", json={"is_active": False}, headers=account.headers)

    response = client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={"amount": "300.00"},
        headers=account.headers,
    )

    assert response.status_code == 200
    assert response.json()["amount"] == "300.00"


# ─── Money on the wire ────────────────────────────────────────────────────


def test_an_amount_is_a_json_string_not_a_number(client: TestClient, account: Account) -> None:
    """A JSON number is an IEEE double, which is what Decimal exists to avoid.

    Checked against the raw text: the parsed body would compare equal either
    way, so only the bytes reveal whether quotes were sent.
    """
    transaction = expense(client, account, amount="1234.50")

    raw = client.get(f"{TRANSACTIONS}/{transaction['id']}", headers=account.headers).text

    assert '"amount":"1234.50"' in raw.replace(" ", "")


def test_a_whole_amount_keeps_its_decimal_places(client: TestClient, account: Account) -> None:
    assert expense(client, account, amount="250")["amount"] == "250.00"


def test_a_large_amount_is_not_rendered_in_scientific_notation(
    client: TestClient, account: Account
) -> None:
    body = expense(client, account, amount="999999999999.99")

    assert body["amount"] == "999999999999.99"
    assert "E" not in body["amount"]


def test_amounts_survive_a_round_trip_unchanged(client: TestClient, account: Account) -> None:
    for amount in ("0.01", "0.10", "9.99", "1000.00", "12345.67"):
        assert expense(client, account, amount=amount)["amount"] == amount


# ─── Listing, filtering and paging ────────────────────────────────────────


def test_the_list_comes_back_as_a_page(client: TestClient, account: Account) -> None:
    expense(client, account)

    body = client.get(TRANSACTIONS, headers=account.headers).json()

    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    assert body["total"] == 1
    assert body["pages"] == 1


def test_an_empty_list_reports_zero_pages(client: TestClient, account: Account) -> None:
    body = client.get(TRANSACTIONS, headers=account.headers).json()

    assert body == {"items": [], "total": 0, "page": 1, "page_size": 25, "pages": 0}


def test_the_page_count_covers_every_row(client: TestClient, account: Account) -> None:
    for day in range(1, 6):
        expense(client, account, date=f"2026-03-0{day}")

    body = client.get(TRANSACTIONS, params={"page_size": 2}, headers=account.headers).json()

    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2


def test_the_total_describes_the_filtered_set_not_the_page(
    client: TestClient, account: Account
) -> None:
    for day in range(1, 6):
        expense(client, account, date=f"2026-03-0{day}")
    income(client, account)

    body = client.get(
        TRANSACTIONS,
        params={"transaction_type": "expense", "page_size": 2},
        headers=account.headers,
    ).json()

    assert body["total"] == 5
    assert len(body["items"]) == 2


def test_filtering_by_date_range(client: TestClient, account: Account) -> None:
    expense(client, account, date="2026-01-15")
    expense(client, account, date="2026-03-15")

    body = client.get(
        TRANSACTIONS,
        params={"date_from": "2026-03-01", "date_to": "2026-03-31"},
        headers=account.headers,
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["date"] == "2026-03-15"


def test_filtering_by_search_term(client: TestClient, account: Account) -> None:
    expense(client, account, description="Lunch at campus")
    expense(client, account, description="Bus fare")

    body = client.get(TRANSACTIONS, params={"search": "lunch"}, headers=account.headers).json()

    assert body["total"] == 1


def test_sorting_by_amount(client: TestClient, account: Account) -> None:
    for amount in ("75.25", "1200.50", "250.00"):
        expense(client, account, amount=amount)

    body = client.get(
        TRANSACTIONS,
        params={"sort_by": "amount", "order": "asc"},
        headers=account.headers,
    ).json()

    assert [item["amount"] for item in body["items"]] == ["75.25", "250.00", "1200.50"]


def test_an_unknown_sort_field_is_rejected(client: TestClient, account: Account) -> None:
    """A sort column has to be one of a known set — it reaches an ORDER BY clause."""
    response = client.get(TRANSACTIONS, params={"sort_by": "user_id"}, headers=account.headers)

    assert response.status_code == 422


def test_a_reversed_date_range_is_rejected(client: TestClient, account: Account) -> None:
    """Silently returning nothing would look like missing data."""
    response = client.get(
        TRANSACTIONS,
        params={"date_from": "2026-06-01", "date_to": "2026-01-01"},
        headers=account.headers,
    )

    assert response.status_code == 422


def test_a_reversed_amount_range_is_rejected(client: TestClient, account: Account) -> None:
    response = client.get(
        TRANSACTIONS,
        params={"amount_min": "500.00", "amount_max": "100.00"},
        headers=account.headers,
    )

    assert response.status_code == 422


def test_page_zero_is_rejected(client: TestClient, account: Account) -> None:
    assert client.get(TRANSACTIONS, params={"page": 0}, headers=account.headers).status_code == 422


def test_an_oversized_page_is_rejected(client: TestClient, account: Account) -> None:
    """Without a ceiling, `page_size=1000000` is a way to make the server work hard."""
    response = client.get(TRANSACTIONS, params={"page_size": 100000}, headers=account.headers)

    assert response.status_code == 422


def test_listing_requires_authentication(client: TestClient) -> None:
    assert client.get(TRANSACTIONS).status_code == 401


def test_a_page_of_rows_costs_a_constant_number_of_queries(
    client: TestClient, account: Account, query_counter
) -> None:
    """The N+1 check at the HTTP boundary: cost must not grow with rows returned.

    Ten rows are fetched and compared against one row. If the category were
    lazily loaded, the difference would be nine extra SELECTs.
    """
    for day in range(10, 20):
        expense(client, account, date=f"2026-03-{day}")

    query_counter.reset()
    client.get(TRANSACTIONS, params={"page_size": 1}, headers=account.headers)
    one_row = len(query_counter.selects)

    query_counter.reset()
    body = client.get(TRANSACTIONS, params={"page_size": 10}, headers=account.headers).json()
    ten_rows = len(query_counter.selects)

    assert len(body["items"]) == 10
    assert one_row == ten_rows


# ─── Payment methods ──────────────────────────────────────────────────────


def test_payment_methods_lists_what_has_been_used(client: TestClient, account: Account) -> None:
    expense(client, account, payment_method="cash")
    expense(client, account, payment_method="bKash")
    expense(client, account, payment_method="cash")

    body = client.get(f"{TRANSACTIONS}/payment-methods", headers=account.headers).json()

    assert body == ["bKash", "cash"]


def test_payment_methods_is_not_mistaken_for_a_transaction_id(
    client: TestClient, account: Account
) -> None:
    """Route order matters: declared after `/{transaction_id}`, this would 422."""
    response = client.get(f"{TRANSACTIONS}/payment-methods", headers=account.headers)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_payment_methods_are_per_user(
    client: TestClient, account: Account, other_account: Account
) -> None:
    expense(client, other_account, payment_method="their-wallet")

    body = client.get(f"{TRANSACTIONS}/payment-methods", headers=account.headers).json()

    assert body == []


# ─── Editing and deleting ─────────────────────────────────────────────────


def test_editing_an_amount(client: TestClient, account: Account) -> None:
    transaction = expense(client, account)

    body = client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={"amount": "300.00"},
        headers=account.headers,
    ).json()

    assert body["amount"] == "300.00"


def test_a_partial_update_leaves_omitted_fields_alone(client: TestClient, account: Account) -> None:
    transaction = expense(client, account)

    body = client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={"amount": "300.00"},
        headers=account.headers,
    ).json()

    assert body["description"] == "Lunch at campus"
    assert body["payment_method"] == "cash"
    assert body["date"] == "2026-03-15"


def test_an_explicit_null_clears_a_description(client: TestClient, account: Account) -> None:
    transaction = expense(client, account)

    body = client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={"description": None},
        headers=account.headers,
    ).json()

    assert body["description"] is None


def test_an_edit_is_visible_in_the_list(client: TestClient, account: Account) -> None:
    transaction = expense(client, account)
    client.patch(
        f"{TRANSACTIONS}/{transaction['id']}",
        json={"amount": "300.00"},
        headers=account.headers,
    )

    body = client.get(TRANSACTIONS, headers=account.headers).json()

    assert body["items"][0]["amount"] == "300.00"


def test_deleting_a_transaction(client: TestClient, account: Account) -> None:
    transaction = expense(client, account)

    response = client.delete(f"{TRANSACTIONS}/{transaction['id']}", headers=account.headers)

    assert response.status_code == 204
    assert client.get(TRANSACTIONS, headers=account.headers).json()["total"] == 0


def test_deleting_twice_is_a_404(client: TestClient, account: Account) -> None:
    transaction = expense(client, account)
    client.delete(f"{TRANSACTIONS}/{transaction['id']}", headers=account.headers)

    response = client.delete(f"{TRANSACTIONS}/{transaction['id']}", headers=account.headers)

    assert response.status_code == 404


def test_deleting_a_transaction_leaves_its_category_alone(
    client: TestClient, account: Account
) -> None:
    transaction = expense(client, account)

    client.delete(f"{TRANSACTIONS}/{transaction['id']}", headers=account.headers)

    assert "Food" in {
        category["name"] for category in client.get(CATEGORIES, headers=account.headers).json()
    }


# ─── One user's data is invisible to another ───────────────────────────────


def test_listing_shows_only_your_own_transactions(
    client: TestClient, account: Account, other_account: Account
) -> None:
    expense(client, other_account, description="Their private spending")
    expense(client, account, description="Mine")

    body = client.get(TRANSACTIONS, headers=account.headers).json()

    assert body["total"] == 1
    assert body["items"][0]["description"] == "Mine"


def test_reading_another_users_transaction_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = expense(client, other_account)

    response = client.get(f"{TRANSACTIONS}/{theirs['id']}", headers=account.headers)

    assert response.status_code == 404


def test_editing_another_users_transaction_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = expense(client, other_account)

    response = client.patch(
        f"{TRANSACTIONS}/{theirs['id']}", json={"amount": "1.00"}, headers=account.headers
    )

    assert response.status_code == 404


def test_deleting_another_users_transaction_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = expense(client, other_account)

    response = client.delete(f"{TRANSACTIONS}/{theirs['id']}", headers=account.headers)

    assert response.status_code == 404


def test_a_failed_cross_user_delete_leaves_the_row_intact(
    client: TestClient, account: Account, other_account: Account
) -> None:
    """A 404 must mean nothing happened, not merely that nothing was reported."""
    theirs = expense(client, other_account)

    client.delete(f"{TRANSACTIONS}/{theirs['id']}", headers=account.headers)

    still_there = client.get(f"{TRANSACTIONS}/{theirs['id']}", headers=other_account.headers)
    assert still_there.status_code == 200


def test_an_error_response_never_leaks_sql(client: TestClient, account: Account) -> None:
    """A database error quotes the failing statement; the client must not see it."""
    response = client.get(f"{TRANSACTIONS}/999999", headers=account.headers)

    body = json.dumps(response.json()).lower()
    assert "select" not in body
    assert "traceback" not in body
