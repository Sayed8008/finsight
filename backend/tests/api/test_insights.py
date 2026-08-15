"""End-to-end tests for the insights endpoint.

The rules themselves are covered exhaustively as pure functions in
`tests/unit/test_insight_rules.py`. What these check is the part that only real
data can answer: that the snapshot is assembled from the right rows, scoped to
the right user, and that a rule fires from an actual budget and an actual
transaction rather than from a hand-built fixture.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import Account, QueryCounter

INSIGHTS = "/api/v1/insights"
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
    day: str = "2026-03-10",
    category: str = "Food",
    kind: str = "expense",
) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": amount,
            "transaction_type": kind,
            "category_id": category_id(client, account, category),
            "date": day,
            "description": "test",
        },
        headers=account.headers,
    )
    assert response.status_code == 201, response.text


def set_budget(
    client: TestClient, account: Account, *, category: str = "Food", amount: str = "1000.00"
) -> None:
    response = client.post(
        BUDGETS,
        json={
            "category_id": category_id(client, account, category),
            "amount": amount,
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
        },
        headers=account.headers,
        params=MARCH,
    )
    assert response.status_code == 201, response.text


def track(client: TestClient, account: Account, *, name: str, start: str) -> None:
    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": name,
            "amount": "499.00",
            "billing_cycle": "monthly",
            "start_date": start,
        },
        headers=account.headers,
        params=MARCH,
    )
    assert response.status_code == 201, response.text


def insights(client: TestClient, account: Account, **params: object) -> dict:
    response = client.get(INSIGHTS, headers=account.headers, params={**MARCH, **params})
    assert response.status_code == 200, response.text
    return response.json()


def codes(body: dict) -> list[str]:
    return [insight["code"] for insight in body["insights"]]


# ─── Shape ────────────────────────────────────────────────────────────────


def test_the_response_describes_the_period_and_the_findings(
    client: TestClient, account: Account
) -> None:
    body = insights(client, account)

    assert set(body) == {
        "period_start",
        "period_end",
        "insights",
        "needs_attention",
        "counts",
    }
    assert body["period_start"] == "2026-03-01"
    assert body["period_end"] == "2026-03-31"


def test_an_untouched_account_gets_the_empty_period_notice(
    client: TestClient, account: Account
) -> None:
    """An empty screen is indistinguishable from something being broken."""
    body = insights(client, account)

    assert codes(body) == ["nothing_recorded"]
    assert body["needs_attention"] == 0


def test_insights_require_authentication(client: TestClient) -> None:
    assert client.get(INSIGHTS).status_code == 401


def test_a_backwards_period_is_rejected(client: TestClient, account: Account) -> None:
    response = client.get(
        INSIGHTS,
        headers=account.headers,
        params={"period_start": "2026-06-01", "period_end": "2026-01-01"},
    )

    assert response.status_code == 422


# ─── Rules firing from real data ──────────────────────────────────────────


def test_an_exceeded_budget_produces_a_critical_insight(
    client: TestClient, account: Account
) -> None:
    set_budget(client, account, amount="1000.00")
    record(client, account, amount="1500.00")

    body = insights(client, account)

    assert "budget_exceeded" in codes(body)
    exceeded = next(i for i in body["insights"] if i["code"] == "budget_exceeded")
    assert exceeded["severity"] == "critical"
    assert "1,500.00" in exceeded["detail"]
    assert exceeded["category_id"] == category_id(client, account, "Food")


def test_a_nearly_spent_budget_produces_a_warning(client: TestClient, account: Account) -> None:
    set_budget(client, account, amount="1000.00")
    record(client, account, amount="850.00")

    assert "budget_nearly_spent" in codes(insights(client, account))


def test_spending_more_than_earning_is_reported(client: TestClient, account: Account) -> None:
    record(client, account, amount="1000.00", category="Salary", kind="income")
    record(client, account, amount="2500.00")

    body = insights(client, account)

    assert "spent_more_than_earned" in codes(body)
    assert body["counts"]["critical"] >= 1


def test_an_overdue_subscription_is_reported(client: TestClient, account: Account) -> None:
    """Started on the 10th, monthly, evaluated on the 15th of a later month."""
    track(client, account, name="Spotify", start="2026-01-10")
    record(client, account, amount="10.00")

    body = insights(client, account, as_of="2026-04-20")

    overdue = [i for i in body["insights"] if i["code"] == "subscription_overdue"]
    assert overdue
    assert overdue[0]["subscription_id"] is not None


def test_a_renewal_due_soon_is_reported(client: TestClient, account: Account) -> None:
    track(client, account, name="Netflix", start="2026-03-18")
    record(client, account, amount="10.00")

    body = insights(client, account)

    assert "renewal_due_soon" in codes(body)


def test_a_paused_subscription_produces_nothing(client: TestClient, account: Account) -> None:
    """Not being charged, so it can be neither overdue nor due soon."""
    track(client, account, name="Gym", start="2026-03-18")
    subscription = client.get(SUBSCRIPTIONS, headers=account.headers, params=MARCH).json()[0]
    client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}", json={"status": "paused"}, headers=account.headers
    )
    record(client, account, amount="10.00")

    body = insights(client, account)

    assert "renewal_due_soon" not in codes(body)


def test_a_category_rise_is_reported_against_the_previous_period(
    client: TestClient, account: Account
) -> None:
    record(client, account, amount="1000.00", day="2026-02-10")
    record(client, account, amount="3000.00", day="2026-03-10")

    body = insights(client, account)

    rose = [i for i in body["insights"] if i["code"] == "category_rose"]
    assert rose
    assert "3,000.00" in rose[0]["detail"]
    assert "1,000.00" in rose[0]["detail"]


def test_a_category_fall_is_reported_as_good_news(client: TestClient, account: Account) -> None:
    record(client, account, amount="3000.00", day="2026-02-10")
    record(client, account, amount="500.00", day="2026-03-10")

    body = insights(client, account)

    fell = [i for i in body["insights"] if i["code"] == "category_fell"]
    assert fell
    assert fell[0]["severity"] == "good"


def test_heavy_subscriptions_are_reported(client: TestClient, account: Account) -> None:
    track(client, account, name="Netflix", start="2026-03-20")
    record(client, account, amount="1000.00")

    assert "subscriptions_are_heavy" in codes(insights(client, account))


# ─── Ordering and counts ──────────────────────────────────────────────────


def test_the_worst_news_comes_first(client: TestClient, account: Account) -> None:
    set_budget(client, account, amount="1000.00")
    record(client, account, amount="1500.00")  # budget exceeded, critical
    track(client, account, name="Netflix", start="2026-03-18")  # renews soon, info

    body = insights(client, account)
    severities = [insight["severity"] for insight in body["insights"]]

    assert severities == sorted(severities, key=["critical", "warning", "info", "good"].index)


def test_counts_and_needs_attention_agree_with_the_list(
    client: TestClient, account: Account
) -> None:
    set_budget(client, account, amount="1000.00")
    record(client, account, amount="1500.00")

    body = insights(client, account)
    counts = body["counts"]

    assert sum(counts.values()) == len(body["insights"])
    assert body["needs_attention"] == counts["critical"] + counts["warning"]


def test_the_same_data_produces_the_same_order(client: TestClient, account: Account) -> None:
    """A list that reshuffles between refreshes reads as broken."""
    set_budget(client, account, category="Food", amount="1000.00")
    set_budget(client, account, category="Rent", amount="1000.00")
    record(client, account, amount="1500.00", category="Food")
    record(client, account, amount="1500.00", category="Rent")

    first = codes(insights(client, account))
    second = codes(insights(client, account))

    assert first == second


def test_every_insight_explains_itself(client: TestClient, account: Account) -> None:
    """The property the whole feature rests on, checked against real data."""
    set_budget(client, account, amount="1000.00")
    record(client, account, amount="1500.00")
    record(client, account, amount="200.00", day="2026-02-10", category="Transport")
    track(client, account, name="Netflix", start="2026-03-18")

    body = insights(client, account)

    assert body["insights"]
    for insight in body["insights"]:
        assert insight["title"].strip()
        assert len(insight["detail"]) > 20
        assert any(character.isdigit() for character in insight["detail"])


# ─── Scoping and cost ─────────────────────────────────────────────────────


def test_another_users_data_produces_no_insights(
    client: TestClient, account: Account, other_account: Account
) -> None:
    set_budget(client, other_account, amount="1000.00")
    record(client, other_account, amount="5000.00")

    assert codes(insights(client, account)) == ["nothing_recorded"]


def test_a_budget_from_another_period_is_not_judged_now(
    client: TestClient, account: Account
) -> None:
    """It would be a permanent complaint no action could clear."""
    set_budget(client, account, amount="1000.00")
    record(client, account, amount="1500.00")

    body = insights(client, account, as_of="2026-08-15")

    assert "budget_exceeded" not in codes(body)


def test_the_cost_does_not_grow_with_the_data(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    """Rules are pure functions over one snapshot, so more rows must not mean
    more queries — a rule that reached for a session would break this.

    One budget against five, not zero against five: an account with no budgets
    at all skips the spend aggregate entirely, so comparing those two would be
    measuring an early return rather than the claim.
    """
    set_budget(client, account, category="Food", amount="1000.00")
    record(client, account, amount="1500.00", category="Food")
    query_counter.reset()
    client.get(INSIGHTS, headers=account.headers, params=MARCH)
    with_one = len(query_counter.selects)

    for category in ("Rent", "Transport", "Shopping", "Bills", "Healthcare"):
        set_budget(client, account, category=category, amount="1000.00")
        record(client, account, amount="1500.00", category=category)
    query_counter.reset()
    body = client.get(INSIGHTS, headers=account.headers, params=MARCH).json()
    with_many = len(query_counter.selects)

    assert len(body["insights"]) > 1
    assert with_one == with_many


def test_the_endpoint_gathers_its_snapshot_only_once(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    """It reports the period as well as the findings, and an earlier version
    fetched the snapshot for each — doubling every query behind the screen."""
    set_budget(client, account, amount="1000.00")
    record(client, account, amount="1500.00")

    query_counter.reset()
    client.get(INSIGHTS, headers=account.headers, params=MARCH)
    endpoint_queries = len(query_counter.selects)

    query_counter.reset()
    from app.services.insight_service import InsightService

    session = client.app.dependency_overrides[list(client.app.dependency_overrides)[0]]()
    InsightService(session).snapshot(account.id, today=None)
    snapshot_queries = len(query_counter.selects)

    # The endpoint also resolves the user from its token, so it is allowed one
    # more than a bare snapshot — but not twice as many.
    assert endpoint_queries <= snapshot_queries + 2
