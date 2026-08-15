"""End-to-end tests for subscription detection.

The algorithm is covered exhaustively as pure functions in
`tests/unit/test_recurrence.py`. What only real data can answer is here: that
the right rows are gathered, that already-tracked subscriptions are filtered
out, and — the constraint ADR-007 is built on — that **detection creates
nothing**.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.conftest import Account, QueryCounter

DETECT = "/api/v1/subscriptions/detect"
SUBSCRIPTIONS = "/api/v1/subscriptions"
CATEGORIES = "/api/v1/categories"
TRANSACTIONS = "/api/v1/transactions"

TODAY = {"as_of": "2026-06-15"}
FIRST_CHARGE = date(2026, 1, 5)


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(c["id"] for c in body if c["name"] == name)


def record(
    client: TestClient,
    account: Account,
    *,
    day: date,
    amount: str = "499.00",
    description: str = "NETFLIX.COM",
    category: str = "Subscriptions",
    kind: str = "expense",
) -> None:
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": amount,
            "transaction_type": kind,
            "category_id": category_id(client, account, category),
            "date": day.isoformat(),
            "description": description,
        },
        headers=account.headers,
    )
    assert response.status_code == 201, response.text


def record_monthly(
    client: TestClient,
    account: Account,
    *,
    count: int = 5,
    amount: str = "499.00",
    description: str = "NETFLIX.COM",
    start: date = FIRST_CHARGE,
) -> None:
    for index in range(count):
        record(
            client,
            account,
            day=start + timedelta(days=30 * index),
            amount=amount,
            description=description,
        )


def detect(client: TestClient, account: Account, **params: object) -> dict:
    response = client.post(DETECT, headers=account.headers, params={**TODAY, **params})
    assert response.status_code == 200, response.text
    return response.json()


def names(body: dict) -> list[str]:
    return [candidate["name"] for candidate in body["candidates"]]


# ─── Shape ────────────────────────────────────────────────────────────────


def test_the_response_names_the_window_it_searched(client: TestClient, account: Account) -> None:
    """ "Nothing found" and "nothing was looked at" are different answers."""
    body = detect(client, account, lookback_days=90)

    assert body["searched_to"] == "2026-06-15"
    assert body["searched_from"] == "2026-03-17"
    assert body["candidates"] == []


def test_detection_requires_authentication(client: TestClient) -> None:
    assert client.post(DETECT).status_code == 401


def test_an_absurd_lookback_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(DETECT, headers=account.headers, params={"lookback_days": 99999})

    assert response.status_code == 422


# ─── Finding things ───────────────────────────────────────────────────────


def test_a_monthly_subscription_is_found_in_ordinary_history(
    client: TestClient, account: Account
) -> None:
    record_monthly(client, account, count=5)

    body = detect(client, account)

    assert names(body) == ["Netflix"]
    candidate = body["candidates"][0]
    assert candidate["amount"] == "499.00"
    assert candidate["billing_cycle"] == "monthly"
    assert candidate["occurrences"] == 5


def test_a_candidate_carries_the_evidence_for_itself(client: TestClient, account: Account) -> None:
    """The constraint from ADR-007: a guess about money must be checkable."""
    record_monthly(client, account, count=4)

    candidate = detect(client, account)["candidates"][0]

    assert "4 charges" in candidate["evidence"]
    assert "499.00" in candidate["evidence"]
    assert len(candidate["transaction_ids"]) == 4


def test_the_transaction_ids_point_at_real_rows(client: TestClient, account: Account) -> None:
    """So the interface can show its work rather than asking to be trusted."""
    record_monthly(client, account, count=4)

    candidate = detect(client, account)["candidates"][0]

    for transaction_id in candidate["transaction_ids"]:
        response = client.get(f"{TRANSACTIONS}/{transaction_id}", headers=account.headers)
        assert response.status_code == 200


def test_the_suggested_category_comes_from_the_charges(
    client: TestClient, account: Account
) -> None:
    record_monthly(client, account, count=4)

    candidate = detect(client, account)["candidates"][0]

    assert candidate["category_id"] == category_id(client, account, "Subscriptions")


def test_the_next_charge_is_projected(client: TestClient, account: Account) -> None:
    record_monthly(client, account, count=4)

    candidate = detect(client, account)["candidates"][0]

    assert candidate["next_expected"] > candidate["last_seen"]


def test_a_price_rise_is_still_one_subscription(client: TestClient, account: Account) -> None:
    record_monthly(client, account, count=3, amount="499.00")
    record_monthly(
        client, account, count=3, amount="549.00", start=FIRST_CHARGE + timedelta(days=90)
    )

    body = detect(client, account)

    assert names(body) == ["Netflix"]
    assert body["candidates"][0]["occurrences"] == 6


def test_two_merchants_are_two_candidates(client: TestClient, account: Account) -> None:
    record_monthly(client, account, count=4, description="NETFLIX.COM", amount="499.00")
    record_monthly(client, account, count=4, description="SPOTIFY", amount="199.00")

    assert sorted(names(detect(client, account))) == ["Netflix", "Spotify"]


# ─── Staying quiet ────────────────────────────────────────────────────────


def test_irregular_spending_is_not_proposed(client: TestClient, account: Account) -> None:
    """The false positive that would make the feature worthless."""
    for day, amount in (
        (date(2026, 1, 5), "1250.00"),
        (date(2026, 1, 11), "980.50"),
        (date(2026, 1, 19), "2100.75"),
        (date(2026, 1, 24), "760.00"),
        (date(2026, 2, 3), "1890.25"),
    ):
        record(client, account, day=day, amount=amount, description="SHWAPNO", category="Food")

    assert detect(client, account)["candidates"] == []


def test_income_is_never_proposed_as_a_subscription(client: TestClient, account: Account) -> None:
    """A regular salary is not something to cancel."""
    for index in range(5):
        record(
            client,
            account,
            day=FIRST_CHARGE + timedelta(days=30 * index),
            amount="45000.00",
            description="MONTHLY SALARY",
            category="Salary",
            kind="income",
        )

    assert detect(client, account)["candidates"] == []


def test_too_few_charges_is_not_a_pattern(client: TestClient, account: Account) -> None:
    record_monthly(client, account, count=2)

    assert detect(client, account)["candidates"] == []


def test_charges_outside_the_window_are_not_searched(client: TestClient, account: Account) -> None:
    record_monthly(client, account, count=5, start=date(2024, 1, 5))

    assert detect(client, account, lookback_days=90)["candidates"] == []


def test_descriptions_with_no_merchant_are_skipped(client: TestClient, account: Account) -> None:
    """ADR-007 records this limitation honestly rather than guessing."""
    for index in range(5):
        record(
            client,
            account,
            day=FIRST_CHARGE + timedelta(days=30 * index),
            description=f"POS PURCHASE {4021 + index}",
        )

    assert detect(client, account)["candidates"] == []


# ─── Already tracked ──────────────────────────────────────────────────────


def track(client: TestClient, account: Account, name: str) -> None:
    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": name,
            "amount": "499.00",
            "billing_cycle": "monthly",
            "start_date": "2026-01-05",
        },
        headers=account.headers,
        params=TODAY,
    )
    assert response.status_code == 201, response.text


def test_a_subscription_already_tracked_is_not_proposed_again(
    client: TestClient, account: Account
) -> None:
    record_monthly(client, account, count=5)
    track(client, account, "Netflix")

    assert detect(client, account)["candidates"] == []


def test_matching_a_tracked_name_is_case_insensitive(client: TestClient, account: Account) -> None:
    record_monthly(client, account, count=5)
    track(client, account, "netflix")

    assert detect(client, account)["candidates"] == []


def test_tracked_candidates_can_be_asked_for(client: TestClient, account: Account) -> None:
    record_monthly(client, account, count=5)
    track(client, account, "Netflix")

    body = detect(client, account, include_tracked=True)

    assert names(body) == ["Netflix"]


# ─── The constraint that matters ──────────────────────────────────────────


def test_detection_creates_nothing(client: TestClient, account: Account) -> None:
    """ADR-007's central constraint. A wrong guess appearing silently in
    someone's monthly commitment is worse than not finding it at all."""
    record_monthly(client, account, count=5)
    before = client.get(SUBSCRIPTIONS, headers=account.headers, params=TODAY).json()

    body = detect(client, account)
    after = client.get(SUBSCRIPTIONS, headers=account.headers, params=TODAY).json()

    assert body["candidates"]  # it did find something
    assert before == after == []  # and created none of it


def test_detection_does_not_touch_the_transactions_it_read(
    client: TestClient, account: Account
) -> None:
    record_monthly(client, account, count=5)
    before = client.get(TRANSACTIONS, headers=account.headers).json()

    detect(client, account)

    assert client.get(TRANSACTIONS, headers=account.headers).json() == before


def test_running_detection_twice_gives_the_same_answer(
    client: TestClient, account: Account
) -> None:
    """It has no state, so it cannot drift between runs."""
    record_monthly(client, account, count=5)

    first = detect(client, account)
    second = detect(client, account)

    assert first == second


# ─── Scoping and cost ─────────────────────────────────────────────────────


def test_another_users_history_is_not_searched(
    client: TestClient, account: Account, other_account: Account
) -> None:
    record_monthly(client, other_account, count=5)

    assert detect(client, account)["candidates"] == []


def test_detection_is_one_query_however_much_history(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    """The algorithm is pure, so only the gathering can cost anything."""
    record_monthly(client, account, count=4, description="NETFLIX.COM")
    query_counter.reset()
    client.post(DETECT, headers=account.headers, params=TODAY)
    with_one = len(query_counter.selects)

    for merchant in ("SPOTIFY", "ADOBE", "GOOGLE DRIVE"):
        record_monthly(client, account, count=4, description=merchant, amount="299.00")
    query_counter.reset()
    body = client.post(DETECT, headers=account.headers, params=TODAY).json()
    with_many = len(query_counter.selects)

    assert len(body["candidates"]) >= 1
    # One extra `name_exists` check per candidate is expected; the history
    # itself is fetched once whatever its size.
    assert with_many - with_one <= len(body["candidates"])
