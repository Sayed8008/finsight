"""End-to-end tests for the dashboard endpoint.

The dashboard reads from every other feature, so what these check is
composition: that the totals, the breakdown, the recent list, the budget counts
and the subscription commitment all describe the same period and the same user
— and that the whole thing is one request whose cost does not grow with the
data behind it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import Account, QueryCounter

DASHBOARD = "/api/v1/dashboard"
CATEGORIES = "/api/v1/categories"
TRANSACTIONS = "/api/v1/transactions"
BUDGETS = "/api/v1/budgets"
SUBSCRIPTIONS = "/api/v1/subscriptions"

MARCH = {"as_of": "2026-03-15"}


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(c["id"] for c in body if c["name"] == name)


def record(
    client: TestClient,
    account: Account,
    *,
    amount: str,
    category: str = "Food",
    kind: str = "expense",
    day: str = "2026-03-10",
    description: str = "test",
) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": amount,
            "transaction_type": kind,
            "category_id": category_id(client, account, category),
            "date": day,
            "description": description,
        },
        headers=account.headers,
    )
    assert response.status_code == 201, response.text


def dashboard(client: TestClient, account: Account, **params: object) -> dict:
    response = client.get(DASHBOARD, headers=account.headers, params={**MARCH, **params})
    assert response.status_code == 200, response.text
    return response.json()


# ─── The period ───────────────────────────────────────────────────────────


def test_the_default_period_is_the_current_month(client: TestClient, account: Account) -> None:
    body = dashboard(client, account)

    assert body["period_start"] == "2026-03-01"
    assert body["period_end"] == "2026-03-31"


def test_february_gets_its_real_length(client: TestClient, account: Account) -> None:
    body = dashboard(client, account, as_of="2026-02-10")

    assert body["period_end"] == "2026-02-28"


def test_a_leap_february_gets_twenty_nine_days(client: TestClient, account: Account) -> None:
    body = dashboard(client, account, as_of="2028-02-10")

    assert body["period_end"] == "2028-02-29"


def test_an_explicit_period_is_used(client: TestClient, account: Account) -> None:
    body = dashboard(client, account, period_start="2026-01-01", period_end="2026-03-31")

    assert body["period_start"] == "2026-01-01"
    assert body["period_end"] == "2026-03-31"


def test_a_backwards_period_is_rejected(client: TestClient, account: Account) -> None:
    response = client.get(
        DASHBOARD,
        headers=account.headers,
        params={"period_start": "2026-06-01", "period_end": "2026-01-01"},
    )

    assert response.status_code == 422


# ─── Totals ───────────────────────────────────────────────────────────────


def test_totals_separate_income_from_expense(client: TestClient, account: Account) -> None:
    record(client, account, amount="45000.00", category="Salary", kind="income")
    record(client, account, amount="1200.00")
    record(client, account, amount="800.00", category="Transport")

    body = dashboard(client, account)["totals"]

    assert body["income"] == "45000.00"
    assert body["expense"] == "2000.00"
    assert body["net"] == "43000.00"
    assert body["transaction_count"] == 3


def test_net_goes_negative_when_more_went_out(client: TestClient, account: Account) -> None:
    """The month a user most needs to see, so it is not clamped at zero."""
    record(client, account, amount="1000.00", category="Salary", kind="income")
    record(client, account, amount="2500.00")

    assert dashboard(client, account)["totals"]["net"] == "-1500.00"


def test_transactions_outside_the_period_are_excluded(client: TestClient, account: Account) -> None:
    record(client, account, amount="900.00", day="2026-02-28")
    record(client, account, amount="100.00", day="2026-03-05")

    assert dashboard(client, account)["totals"]["expense"] == "100.00"


def test_an_empty_month_is_zeroes_not_an_error(client: TestClient, account: Account) -> None:
    body = dashboard(client, account)

    assert body["totals"] == {
        "income": "0.00",
        "expense": "0.00",
        "net": "0.00",
        "transaction_count": 0,
    }
    assert body["spending"] == []


def test_totals_are_json_strings(client: TestClient, account: Account) -> None:
    record(client, account, amount="1234.50")

    raw = client.get(DASHBOARD, headers=account.headers, params=MARCH).text.replace(" ", "")

    assert '"expense":"1234.50"' in raw


def test_another_users_transactions_are_not_counted(
    client: TestClient, account: Account, other_account: Account
) -> None:
    record(client, other_account, amount="9999.00")

    assert dashboard(client, account)["totals"]["expense"] == "0.00"


# ─── Spending breakdown ───────────────────────────────────────────────────


def test_spending_is_broken_down_by_category_largest_first(
    client: TestClient, account: Account
) -> None:
    record(client, account, amount="300.00", category="Food")
    record(client, account, amount="900.00", category="Rent")
    record(client, account, amount="600.00", category="Transport")

    body = dashboard(client, account)["spending"]

    assert [row["name"] for row in body] == ["Rent", "Transport", "Food"]
    assert [row["total"] for row in body] == ["900.00", "600.00", "300.00"]


def test_shares_are_percentages_of_the_period(client: TestClient, account: Account) -> None:
    record(client, account, amount="750.00", category="Food")
    record(client, account, amount="250.00", category="Rent")

    body = dashboard(client, account)["spending"]

    assert body[0]["percentage"] == "75.00"
    assert body[1]["percentage"] == "25.00"


def test_income_is_not_part_of_the_spending_breakdown(client: TestClient, account: Account) -> None:
    """Mixing the two would make every share meaningless."""
    record(client, account, amount="45000.00", category="Salary", kind="income")
    record(client, account, amount="500.00", category="Food")

    body = dashboard(client, account)["spending"]

    assert [row["name"] for row in body] == ["Food"]
    assert body[0]["percentage"] == "100.00"


def test_the_breakdown_carries_the_category_colour(client: TestClient, account: Account) -> None:
    record(client, account, amount="500.00", category="Food")

    row = dashboard(client, account)["spending"][0]

    assert row["color"] is not None
    assert row["category_id"] is not None


def test_the_tail_is_folded_into_one_other_row(client: TestClient, account: Account) -> None:
    """Past about seven classes adjacent ones stop being tellable apart (ADR-026)."""
    spends = [
        ("Rent", "1000.00"),
        ("Food", "900.00"),
        ("Transport", "800.00"),
        ("Shopping", "700.00"),
        ("Bills", "600.00"),
        ("Healthcare", "500.00"),
        ("Education", "400.00"),
        ("Entertainment", "300.00"),
    ]
    for category, amount in spends:
        record(client, account, amount=amount, category=category)

    body = dashboard(client, account)["spending"]

    # Six named categories, plus one folded row.
    assert len(body) == 7
    assert body[-1]["name"] == "Other categories"
    assert body[-1]["category_id"] is None
    # Education 400 + Entertainment 300.
    assert body[-1]["total"] == "700.00"


def test_the_shares_still_add_up_to_a_hundred_after_folding(
    client: TestClient, account: Account
) -> None:
    """Percentages are of the whole period, not rescaled to the visible rows."""
    for category, amount in (
        ("Rent", "1000.00"),
        ("Food", "900.00"),
        ("Transport", "800.00"),
        ("Shopping", "700.00"),
        ("Bills", "600.00"),
        ("Healthcare", "500.00"),
        ("Education", "400.00"),
    ):
        record(client, account, amount=amount, category=category)

    body = dashboard(client, account)["spending"]
    total = sum(float(row["percentage"]) for row in body)

    assert abs(total - 100.0) < 0.05


def test_no_other_row_when_nothing_was_left_out(client: TestClient, account: Account) -> None:
    record(client, account, amount="500.00", category="Food")
    record(client, account, amount="300.00", category="Rent")

    body = dashboard(client, account)["spending"]

    assert [row["name"] for row in body] == ["Food", "Rent"]


# ─── Recent activity ──────────────────────────────────────────────────────


def test_recent_activity_is_the_newest_few(client: TestClient, account: Account) -> None:
    for day in range(1, 9):
        record(client, account, amount="10.00", day=f"2026-03-0{day}", description=f"day {day}")

    body = dashboard(client, account)["recent"]

    assert len(body) == 5
    assert body[0]["description"] == "day 8"


def test_recent_activity_ignores_the_period(client: TestClient, account: Account) -> None:
    """ "What did I just do" is not a question about the selected month."""
    record(client, account, amount="10.00", day="2026-01-05", description="january")

    body = dashboard(client, account)["recent"]

    assert [row["description"] for row in body] == ["january"]


def test_recent_activity_is_per_user(
    client: TestClient, account: Account, other_account: Account
) -> None:
    record(client, other_account, amount="10.00", description="theirs")

    assert dashboard(client, account)["recent"] == []


# ─── Budget health ────────────────────────────────────────────────────────


def set_budget(client: TestClient, account: Account, category: str, amount: str) -> None:
    response = client.post(
        BUDGETS,
        json={
            "category_id": category_id(client, account, category),
            "amount": amount,
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
        },
        headers=account.headers,
    )
    assert response.status_code == 201, response.text


def test_budget_health_counts_by_status(client: TestClient, account: Account) -> None:
    set_budget(client, account, "Food", "1000.00")
    set_budget(client, account, "Transport", "1000.00")
    set_budget(client, account, "Rent", "1000.00")
    record(client, account, amount="100.00", category="Food")  # healthy
    record(client, account, amount="850.00", category="Transport")  # warning
    record(client, account, amount="1200.00", category="Rent")  # exceeded

    body = dashboard(client, account)["budgets"]

    assert body == {
        "total": 3,
        "on_track": 1,
        "warning": 1,
        "exceeded": 1,
        "needs_attention": 2,
    }


def test_budgets_outside_the_reference_day_are_not_counted(
    client: TestClient, account: Account
) -> None:
    """A budget that ended would otherwise leave the dashboard permanently amber."""
    set_budget(client, account, "Food", "1000.00")
    record(client, account, amount="1200.00", category="Food")

    body = dashboard(client, account, as_of="2026-06-15")["budgets"]

    assert body["total"] == 0
    assert body["needs_attention"] == 0


def test_no_budgets_is_zeroes(client: TestClient, account: Account) -> None:
    assert dashboard(client, account)["budgets"]["total"] == 0


# ─── Subscription commitment ──────────────────────────────────────────────


def test_the_dashboard_carries_the_subscription_commitment(
    client: TestClient, account: Account
) -> None:
    client.post(
        SUBSCRIPTIONS,
        json={
            "name": "Netflix",
            "amount": "499.00",
            "billing_cycle": "monthly",
            "start_date": "2026-01-10",
        },
        headers=account.headers,
        params=MARCH,
    )

    body = dashboard(client, account)["subscriptions"]

    assert body["active_count"] == 1
    assert body["monthly_total"] == "499.00"
    assert body["next_renewal"]["name"] == "Netflix"


def test_no_subscriptions_is_zeroes(client: TestClient, account: Account) -> None:
    body = dashboard(client, account)["subscriptions"]

    assert body["active_count"] == 0
    assert body["monthly_total"] == "0.00"
    assert body["next_renewal"] is None


# ─── Shape and cost ───────────────────────────────────────────────────────


def test_the_dashboard_is_one_request_with_every_section(
    client: TestClient, account: Account
) -> None:
    body = dashboard(client, account)

    assert set(body) == {
        "period_start",
        "period_end",
        "totals",
        "spending",
        "recent",
        "budgets",
        "subscriptions",
    }


def test_the_dashboard_requires_authentication(client: TestClient) -> None:
    assert client.get(DASHBOARD).status_code == 401


def test_the_dashboard_cost_does_not_grow_with_the_data(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    """It aggregates; it must not fetch rows and count them in Python."""
    record(client, account, amount="100.00")
    query_counter.reset()
    client.get(DASHBOARD, headers=account.headers, params=MARCH)
    with_one = len(query_counter.selects)

    for category in ("Rent", "Transport", "Shopping", "Bills", "Healthcare"):
        for _ in range(4):
            record(client, account, amount="50.00", category=category)
    query_counter.reset()
    client.get(DASHBOARD, headers=account.headers, params=MARCH)
    with_many = len(query_counter.selects)

    assert with_one == with_many
