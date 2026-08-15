"""End-to-end tests for the budget endpoints.

What matters most here:

  * **spend is computed, never stored** — changing a transaction must change
    the budget's figures on the next read, with nothing to invalidate;
  * **only expenses in the period, in that category, for that user** count;
  * **budgets for one category may not overlap**, which the schema's unique
    constraint does not cover;
  * the cost of listing budgets does not grow with the number of budgets.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import Account, QueryCounter

BUDGETS = "/api/v1/budgets"
CATEGORIES = "/api/v1/categories"
TRANSACTIONS = "/api/v1/transactions"

MARCH = {"period_start": "2026-03-01", "period_end": "2026-03-31"}
APRIL = {"period_start": "2026-04-01", "period_end": "2026-04-30"}

# A day inside March, so `is_current` and `days_remaining` do not depend on
# when the suite happens to run.
MID_MARCH = {"as_of": "2026-03-15"}


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(category["id"] for category in body if category["name"] == name)


def set_budget(
    client: TestClient,
    account: Account,
    *,
    category: str = "Food",
    amount: str = "5000.00",
    **overrides,
) -> dict:
    payload = {
        "category_id": category_id(client, account, category),
        "amount": amount,
        **MARCH,
        **overrides,
    }
    response = client.post(BUDGETS, json=payload, headers=account.headers, params=MID_MARCH)
    assert response.status_code == 201, response.text
    return response.json()


def spend(
    client: TestClient,
    account: Account,
    *,
    amount: str,
    category: str = "Food",
    day: str = "2026-03-10",
    kind: str = "expense",
) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": amount,
            "transaction_type": kind,
            "category_id": category_id(client, account, category),
            "date": day,
            "description": "test spending",
        },
        headers=account.headers,
    )
    assert response.status_code == 201, response.text


def fetch(client: TestClient, account: Account, budget_id: int) -> dict:
    response = client.get(f"{BUDGETS}/{budget_id}", headers=account.headers, params=MID_MARCH)
    assert response.status_code == 200, response.text
    return response.json()


# ─── Creating ─────────────────────────────────────────────────────────────


def test_setting_a_budget(client: TestClient, account: Account) -> None:
    body = set_budget(client, account)

    assert body["amount"] == "5000.00"
    assert body["category"]["name"] == "Food"
    assert body["period_start"] == "2026-03-01"
    assert body["spent"] == "0.00"
    assert body["remaining"] == "5000.00"
    assert body["status"] == "healthy"


def test_the_category_is_embedded(client: TestClient, account: Account) -> None:
    body = set_budget(client, account)

    assert body["category"]["category_type"] == "expense"
    assert body["category"]["color"] is not None


def test_a_budget_cannot_be_set_on_an_income_category(client: TestClient, account: Account) -> None:
    """ "Spend no more than X on Salary" is not a sentence anyone means."""
    response = client.post(
        BUDGETS,
        json={"category_id": category_id(client, account, "Salary"), "amount": "100.00", **MARCH},
        headers=account.headers,
    )

    assert response.status_code == 422
    assert "expense category" in response.json()["detail"]


def test_a_budget_cannot_use_a_deactivated_category(client: TestClient, account: Account) -> None:
    food = category_id(client, account, "Food")
    client.patch(f"{CATEGORIES}/{food}", json={"is_active": False}, headers=account.headers)

    response = client.post(
        BUDGETS, json={"category_id": food, "amount": "100.00", **MARCH}, headers=account.headers
    )

    assert response.status_code == 422
    assert "deactivated" in response.json()["detail"]


def test_another_users_category_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = category_id(client, other_account, "Food")

    response = client.post(
        BUDGETS, json={"category_id": theirs, "amount": "100.00", **MARCH}, headers=account.headers
    )

    assert response.status_code == 404


def test_a_zero_or_negative_amount_is_rejected(client: TestClient, account: Account) -> None:
    food = category_id(client, account, "Food")

    for amount in ("0.00", "-500.00"):
        response = client.post(
            BUDGETS, json={"category_id": food, "amount": amount, **MARCH}, headers=account.headers
        )
        assert response.status_code == 422


def test_a_backwards_period_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        BUDGETS,
        json={
            "category_id": category_id(client, account, "Food"),
            "amount": "100.00",
            "period_start": "2026-03-31",
            "period_end": "2026-03-01",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_a_single_day_budget_is_allowed(client: TestClient, account: Account) -> None:
    """A period is inclusive at both ends, so start == end is one valid day."""
    body = set_budget(client, account, period_start="2026-03-05", period_end="2026-03-05")

    assert body["period_start"] == body["period_end"] == "2026-03-05"


# ─── Overlap ──────────────────────────────────────────────────────────────


def test_two_budgets_for_one_category_may_not_overlap(client: TestClient, account: Account) -> None:
    """Otherwise "how much is left for Food?" has two answers."""
    set_budget(client, account)

    response = client.post(
        BUDGETS,
        json={
            "category_id": category_id(client, account, "Food"),
            "amount": "1000.00",
            "period_start": "2026-03-15",
            "period_end": "2026-04-15",
        },
        headers=account.headers,
    )

    assert response.status_code == 409
    assert "overlap" in response.json()["detail"].lower()


def test_a_period_entirely_inside_another_is_an_overlap(
    client: TestClient, account: Account
) -> None:
    """The case a naive start-to-start comparison misses."""
    set_budget(client, account)

    response = client.post(
        BUDGETS,
        json={
            "category_id": category_id(client, account, "Food"),
            "amount": "1000.00",
            "period_start": "2026-03-10",
            "period_end": "2026-03-20",
        },
        headers=account.headers,
    )

    assert response.status_code == 409


def test_a_period_enclosing_another_is_an_overlap(client: TestClient, account: Account) -> None:
    set_budget(client, account, period_start="2026-03-10", period_end="2026-03-20")

    response = client.post(
        BUDGETS,
        json={"category_id": category_id(client, account, "Food"), "amount": "1000.00", **MARCH},
        headers=account.headers,
    )

    assert response.status_code == 409


def test_touching_periods_do_not_overlap(client: TestClient, account: Account) -> None:
    """31 March and 1 April are adjacent, not overlapping."""
    set_budget(client, account)

    response = client.post(
        BUDGETS,
        json={"category_id": category_id(client, account, "Food"), "amount": "1000.00", **APRIL},
        headers=account.headers,
    )

    assert response.status_code == 201


def test_different_categories_may_share_a_period(client: TestClient, account: Account) -> None:
    set_budget(client, account, category="Food")

    assert set_budget(client, account, category="Transport")["category"]["name"] == "Transport"


def test_two_users_may_budget_the_same_category_and_period(
    client: TestClient, account: Account, other_account: Account
) -> None:
    set_budget(client, account)

    assert set_budget(client, other_account)["amount"] == "5000.00"


def test_a_budget_does_not_overlap_itself_when_edited(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)

    response = client.patch(
        f"{BUDGETS}/{budget['id']}", json={"amount": "6000.00"}, headers=account.headers
    )

    assert response.status_code == 200
    assert response.json()["amount"] == "6000.00"


def test_editing_a_period_onto_another_budget_is_rejected(
    client: TestClient, account: Account
) -> None:
    set_budget(client, account)
    april = set_budget(client, account, **APRIL)

    response = client.patch(
        f"{BUDGETS}/{april['id']}",
        json={"period_start": "2026-03-15"},
        headers=account.headers,
    )

    assert response.status_code == 409


# ─── Spend is computed, not stored ────────────────────────────────────────


def test_spending_is_reflected_without_touching_the_budget(
    client: TestClient, account: Account
) -> None:
    """Nothing invalidates a cache here, because there is no cache (ADR-015)."""
    budget = set_budget(client, account)
    spend(client, account, amount="1250.50")

    body = fetch(client, account, budget["id"])

    assert body["spent"] == "1250.50"
    assert body["remaining"] == "3749.50"
    assert body["percentage_used"] == "25.01"


def test_deleting_a_transaction_lowers_the_spend_again(
    client: TestClient, account: Account
) -> None:
    budget = set_budget(client, account)
    spend(client, account, amount="1000.00")
    transaction = client.get(TRANSACTIONS, headers=account.headers).json()["items"][0]

    client.delete(f"{TRANSACTIONS}/{transaction['id']}", headers=account.headers)

    assert fetch(client, account, budget["id"])["spent"] == "0.00"


def test_editing_a_transactions_amount_changes_the_spend(
    client: TestClient, account: Account
) -> None:
    budget = set_budget(client, account)
    spend(client, account, amount="1000.00")
    transaction = client.get(TRANSACTIONS, headers=account.headers).json()["items"][0]

    client.patch(
        f"{TRANSACTIONS}/{transaction['id']}", json={"amount": "2500.00"}, headers=account.headers
    )

    assert fetch(client, account, budget["id"])["spent"] == "2500.00"


def test_spending_outside_the_period_is_not_counted(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)
    spend(client, account, amount="900.00", day="2026-02-28")
    spend(client, account, amount="900.00", day="2026-04-01")

    assert fetch(client, account, budget["id"])["spent"] == "0.00"


def test_the_period_includes_both_end_days(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)
    spend(client, account, amount="100.00", day="2026-03-01")
    spend(client, account, amount="200.00", day="2026-03-31")

    assert fetch(client, account, budget["id"])["spent"] == "300.00"


def test_another_categorys_spending_is_not_counted(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account, category="Food")
    spend(client, account, amount="900.00", category="Transport")

    assert fetch(client, account, budget["id"])["spent"] == "0.00"


def test_income_in_the_same_category_is_not_counted(client: TestClient, account: Account) -> None:
    """A refund recorded as income is not spending, and must not reduce it."""
    budget = set_budget(client, account)
    spend(client, account, amount="500.00")
    spend(client, account, amount="200.00", category="Salary", kind="income")

    assert fetch(client, account, budget["id"])["spent"] == "500.00"


def test_another_users_spending_is_not_counted(
    client: TestClient, account: Account, other_account: Account
) -> None:
    budget = set_budget(client, account)
    spend(client, other_account, amount="4000.00")

    assert fetch(client, account, budget["id"])["spent"] == "0.00"


def test_many_transactions_sum_exactly(client: TestClient, account: Account) -> None:
    """Ten lots of 0.10 is 1.00 — with floats it would not be (ADR-003)."""
    budget = set_budget(client, account, amount="1.00")
    for _ in range(10):
        spend(client, account, amount="0.10")

    body = fetch(client, account, budget["id"])

    assert body["spent"] == "1.00"
    assert body["remaining"] == "0.00"
    assert body["status"] == "exceeded"


# ─── Status ───────────────────────────────────────────────────────────────


def test_status_turns_amber_at_eighty_percent(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account, amount="1000.00")
    spend(client, account, amount="800.00")

    body = fetch(client, account, budget["id"])

    assert body["percentage_used"] == "80.00"
    assert body["status"] == "warning"


def test_status_is_exceeded_when_overspent_and_remaining_goes_negative(
    client: TestClient, account: Account
) -> None:
    budget = set_budget(client, account, amount="1000.00")
    spend(client, account, amount="1250.00")

    body = fetch(client, account, budget["id"])

    assert body["status"] == "exceeded"
    assert body["remaining"] == "-250.00"
    assert body["percentage_used"] == "125.00"


# ─── Amounts on the wire ──────────────────────────────────────────────────


def test_every_figure_is_a_json_string(client: TestClient, account: Account) -> None:
    """Checked as raw text: parsed JSON would compare equal either way (ADR-003)."""
    budget = set_budget(client, account, amount="1000.00")
    spend(client, account, amount="250.00")

    raw = client.get(f"{BUDGETS}/{budget['id']}", headers=account.headers).text.replace(" ", "")

    for field, value in (
        ("amount", "1000.00"),
        ("spent", "250.00"),
        ("remaining", "750.00"),
        ("percentage_used", "25.00"),
    ):
        assert f'"{field}":"{value}"' in raw


# ─── The reference day ────────────────────────────────────────────────────


def test_a_running_budget_reports_days_remaining(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)

    body = fetch(client, account, budget["id"])

    assert body["is_current"] is True
    # 15 March to 31 March inclusive.
    assert body["days_remaining"] == 17


def test_a_finished_budget_has_no_days_remaining(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)

    body = client.get(
        f"{BUDGETS}/{budget['id']}", headers=account.headers, params={"as_of": "2026-06-01"}
    ).json()

    assert body["is_current"] is False
    assert body["days_remaining"] is None


def test_a_budget_that_has_not_started_has_no_days_remaining(
    client: TestClient, account: Account
) -> None:
    """ "12 days remaining" on a budget starting next month reads as time to spend."""
    budget = set_budget(client, account)

    body = client.get(
        f"{BUDGETS}/{budget['id']}", headers=account.headers, params={"as_of": "2026-01-01"}
    ).json()

    assert body["is_current"] is False
    assert body["days_remaining"] is None


def test_the_last_day_of_a_budget_still_counts_as_current(
    client: TestClient, account: Account
) -> None:
    budget = set_budget(client, account)

    body = client.get(
        f"{BUDGETS}/{budget['id']}", headers=account.headers, params={"as_of": "2026-03-31"}
    ).json()

    assert body["is_current"] is True
    assert body["days_remaining"] == 1


# ─── Listing ──────────────────────────────────────────────────────────────


def test_listing_returns_every_budget(client: TestClient, account: Account) -> None:
    set_budget(client, account, category="Food")
    set_budget(client, account, category="Transport")

    body = client.get(BUDGETS, headers=account.headers, params=MID_MARCH).json()

    assert len(body) == 2


def test_listing_is_newest_period_first(client: TestClient, account: Account) -> None:
    set_budget(client, account, **MARCH)
    set_budget(client, account, **APRIL)

    body = client.get(BUDGETS, headers=account.headers, params=MID_MARCH).json()

    assert [b["period_start"] for b in body] == ["2026-04-01", "2026-03-01"]


def test_current_only_hides_other_periods(client: TestClient, account: Account) -> None:
    set_budget(client, account, **MARCH)
    set_budget(client, account, **APRIL)

    body = client.get(
        BUDGETS, headers=account.headers, params={**MID_MARCH, "current_only": True}
    ).json()

    assert [b["period_start"] for b in body] == ["2026-03-01"]


def test_listing_can_be_filtered_by_category(client: TestClient, account: Account) -> None:
    set_budget(client, account, category="Food")
    set_budget(client, account, category="Transport")
    food = category_id(client, account, "Food")

    body = client.get(
        BUDGETS, headers=account.headers, params={**MID_MARCH, "category_id": food}
    ).json()

    assert len(body) == 1
    assert body[0]["category"]["name"] == "Food"


def test_listing_shows_only_your_own_budgets(
    client: TestClient, account: Account, other_account: Account
) -> None:
    set_budget(client, other_account)

    assert client.get(BUDGETS, headers=account.headers).json() == []


def test_listing_requires_authentication(client: TestClient) -> None:
    assert client.get(BUDGETS).status_code == 401


def test_listing_budgets_costs_the_same_however_many_there_are(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    """The N+1 check. Each budget has its own period, so the obvious
    implementation is a SUM per budget — this asserts it is not that.
    """
    set_budget(client, account, category="Food")
    query_counter.reset()
    client.get(BUDGETS, headers=account.headers, params=MID_MARCH)
    with_one = len(query_counter.selects)

    for category in ("Transport", "Education", "Shopping", "Bills"):
        set_budget(client, account, category=category)
    query_counter.reset()
    body = client.get(BUDGETS, headers=account.headers, params=MID_MARCH).json()
    with_five = len(query_counter.selects)

    assert len(body) == 5
    assert with_one == with_five


def test_each_budget_gets_its_own_periods_spend(client: TestClient, account: Account) -> None:
    """One aggregate query serves budgets covering different date ranges."""
    march = set_budget(client, account, **MARCH)
    april = set_budget(client, account, **APRIL)
    spend(client, account, amount="100.00", day="2026-03-10")
    spend(client, account, amount="700.00", day="2026-04-10")

    body = {b["id"]: b["spent"] for b in client.get(BUDGETS, headers=account.headers).json()}

    assert body[march["id"]] == "100.00"
    assert body[april["id"]] == "700.00"


# ─── Editing and deleting ─────────────────────────────────────────────────


def test_changing_the_amount_recomputes_the_figures(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account, amount="1000.00")
    spend(client, account, amount="800.00")

    body = client.patch(
        f"{BUDGETS}/{budget['id']}",
        json={"amount": "2000.00"},
        headers=account.headers,
        params=MID_MARCH,
    ).json()

    assert body["percentage_used"] == "40.00"
    assert body["status"] == "healthy"


def test_a_partial_update_leaves_other_fields_alone(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)

    body = client.patch(
        f"{BUDGETS}/{budget['id']}", json={"amount": "7500.00"}, headers=account.headers
    ).json()

    assert body["period_start"] == "2026-03-01"
    assert body["category"]["name"] == "Food"


def test_moving_one_end_of_the_period_past_the_other_is_rejected(
    client: TestClient, account: Account
) -> None:
    """The schema cannot catch this — it only sees the one field that was sent."""
    budget = set_budget(client, account)

    response = client.patch(
        f"{BUDGETS}/{budget['id']}",
        json={"period_start": "2026-05-01"},
        headers=account.headers,
    )

    assert response.status_code == 422


def test_a_budget_can_be_moved_to_another_expense_category(
    client: TestClient, account: Account
) -> None:
    budget = set_budget(client, account, category="Food")

    body = client.patch(
        f"{BUDGETS}/{budget['id']}",
        json={"category_id": category_id(client, account, "Transport")},
        headers=account.headers,
    ).json()

    assert body["category"]["name"] == "Transport"


def test_a_budget_cannot_be_moved_to_an_income_category(
    client: TestClient, account: Account
) -> None:
    budget = set_budget(client, account)

    response = client.patch(
        f"{BUDGETS}/{budget['id']}",
        json={"category_id": category_id(client, account, "Salary")},
        headers=account.headers,
    )

    assert response.status_code == 422


def test_deleting_a_budget(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)

    response = client.delete(f"{BUDGETS}/{budget['id']}", headers=account.headers)

    assert response.status_code == 204
    assert client.get(BUDGETS, headers=account.headers).json() == []


def test_deleting_a_budget_keeps_the_transactions(client: TestClient, account: Account) -> None:
    """A budget is a plan; deleting it must not touch what actually happened."""
    budget = set_budget(client, account)
    spend(client, account, amount="500.00")

    client.delete(f"{BUDGETS}/{budget['id']}", headers=account.headers)

    assert client.get(TRANSACTIONS, headers=account.headers).json()["total"] == 1


def test_deleting_twice_is_a_404(client: TestClient, account: Account) -> None:
    budget = set_budget(client, account)
    client.delete(f"{BUDGETS}/{budget['id']}", headers=account.headers)

    assert client.delete(f"{BUDGETS}/{budget['id']}", headers=account.headers).status_code == 404


# ─── One user's data is invisible to another ──────────────────────────────


def test_reading_another_users_budget_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = set_budget(client, other_account)

    assert client.get(f"{BUDGETS}/{theirs['id']}", headers=account.headers).status_code == 404


def test_editing_another_users_budget_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = set_budget(client, other_account)

    response = client.patch(
        f"{BUDGETS}/{theirs['id']}", json={"amount": "1.00"}, headers=account.headers
    )

    assert response.status_code == 404


def test_deleting_another_users_budget_is_a_404_and_leaves_it_alone(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = set_budget(client, other_account)

    assert client.delete(f"{BUDGETS}/{theirs['id']}", headers=account.headers).status_code == 404
    assert client.get(f"{BUDGETS}/{theirs['id']}", headers=other_account.headers).status_code == 200


def test_a_nonexistent_budget_is_a_404(client: TestClient, account: Account) -> None:
    assert client.get(f"{BUDGETS}/999999", headers=account.headers).status_code == 404
