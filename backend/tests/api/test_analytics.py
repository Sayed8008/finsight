"""End-to-end tests for the analytics endpoints.

Two things carry most of the weight:

  * **empty months are filled in.** A database returns only the months that
    have rows; a chart that skips March puts February next to April and makes
    two months of change look like one.
  * **the comparison window is derived and equal in length.** Comparing a month
    against a fortnight and reading the result as a 50% saving is the failure
    this design exists to prevent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import Account, QueryCounter

TREND = "/api/v1/analytics/trend"
COMPARISON = "/api/v1/analytics/comparison"
CATEGORIES = "/api/v1/categories"
TRANSACTIONS = "/api/v1/transactions"

MARCH = {"as_of": "2026-03-15"}


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(c["id"] for c in body if c["name"] == name)


def record(
    client: TestClient,
    account: Account,
    *,
    amount: str,
    day: str,
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


def trend(client: TestClient, account: Account, **params: object) -> dict:
    response = client.get(TREND, headers=account.headers, params={**MARCH, **params})
    assert response.status_code == 200, response.text
    return response.json()


def comparison(client: TestClient, account: Account, **params: object) -> dict:
    response = client.get(COMPARISON, headers=account.headers, params={**MARCH, **params})
    assert response.status_code == 200, response.text
    return response.json()


# ─── Trend ────────────────────────────────────────────────────────────────


def test_the_trend_covers_the_requested_months_including_this_one(
    client: TestClient, account: Account
) -> None:
    body = trend(client, account, months=6)

    assert len(body["months"]) == 6
    assert body["months"][0]["first_day"] == "2025-10-01"
    assert body["months"][-1]["first_day"] == "2026-03-01"


def test_the_trend_defaults_to_six_months(client: TestClient, account: Account) -> None:
    assert len(trend(client, account)["months"]) == 6


def test_months_with_no_activity_come_back_as_zeroes(client: TestClient, account: Account) -> None:
    """The point of the fill. A skipped month is a chart that lies about it."""
    record(client, account, amount="500.00", day="2026-01-15")
    record(client, account, amount="700.00", day="2026-03-05")

    months = trend(client, account, months=4)["months"]

    assert [m["first_day"] for m in months] == [
        "2025-12-01",
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]
    assert [m["expense"] for m in months] == ["0.00", "500.00", "0.00", "700.00"]


def test_the_trend_separates_income_from_expense(client: TestClient, account: Account) -> None:
    record(client, account, amount="45000.00", day="2026-03-01", category="Salary", kind="income")
    record(client, account, amount="12000.00", day="2026-03-05")

    march = trend(client, account, months=1)["months"][0]

    assert march["income"] == "45000.00"
    assert march["expense"] == "12000.00"
    assert march["net"] == "33000.00"


def test_a_month_can_be_net_negative(client: TestClient, account: Account) -> None:
    record(client, account, amount="1000.00", day="2026-03-01", category="Salary", kind="income")
    record(client, account, amount="2500.00", day="2026-03-05")

    assert trend(client, account, months=1)["months"][0]["net"] == "-1500.00"


def test_the_trend_crosses_a_year_boundary(client: TestClient, account: Account) -> None:
    record(client, account, amount="100.00", day="2025-12-20")

    months = trend(client, account, months=4)["months"]

    assert months[0]["year"] == 2025
    assert months[0]["month"] == 12
    assert months[0]["expense"] == "100.00"


def test_has_activity_is_false_for_an_empty_span(client: TestClient, account: Account) -> None:
    body = trend(client, account)

    assert body["has_activity"] is False
    assert all(month["income"] == "0.00" for month in body["months"])


def test_has_activity_is_true_once_something_is_recorded(
    client: TestClient, account: Account
) -> None:
    record(client, account, amount="1.00", day="2026-03-01")

    assert trend(client, account)["has_activity"] is True


def test_a_single_month_trend_is_allowed(client: TestClient, account: Account) -> None:
    assert len(trend(client, account, months=1)["months"]) == 1


def test_an_absurd_span_is_rejected(client: TestClient, account: Account) -> None:
    assert client.get(TREND, headers=account.headers, params={"months": 500}).status_code == 422
    assert client.get(TREND, headers=account.headers, params={"months": 0}).status_code == 422


def test_the_trend_is_per_user(
    client: TestClient, account: Account, other_account: Account
) -> None:
    record(client, other_account, amount="9999.00", day="2026-03-01")

    assert trend(client, account)["has_activity"] is False


def test_the_trend_requires_authentication(client: TestClient) -> None:
    assert client.get(TREND).status_code == 401


def test_the_trend_is_one_query_however_many_months(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    """Grouping happens in SQL; the fill is a loop over a calendar, not queries."""
    for month in range(1, 4):
        record(client, account, amount="100.00", day=f"2026-0{month}-05")

    query_counter.reset()
    client.get(TREND, headers=account.headers, params={**MARCH, "months": 3})
    short = len(query_counter.selects)

    query_counter.reset()
    client.get(TREND, headers=account.headers, params={**MARCH, "months": 24})
    long = len(query_counter.selects)

    assert short == long


# ─── Comparison: the window ───────────────────────────────────────────────


def test_the_comparison_window_is_derived(client: TestClient, account: Account) -> None:
    body = comparison(client, account)

    assert body["period_start"] == "2026-03-01"
    assert body["period_end"] == "2026-03-31"
    assert body["previous_end"] == "2026-02-28"


def test_the_windows_are_the_same_length(client: TestClient, account: Account) -> None:
    """Unequal lengths would make the two totals incomparable."""
    from datetime import date

    body = comparison(client, account)
    current = date.fromisoformat(body["period_end"]) - date.fromisoformat(body["period_start"])
    previous = date.fromisoformat(body["previous_end"]) - date.fromisoformat(body["previous_start"])

    assert current == previous


def test_an_explicit_period_is_compared_with_what_precedes_it(
    client: TestClient, account: Account
) -> None:
    body = comparison(client, account, period_start="2026-03-10", period_end="2026-03-19")

    assert body["previous_start"] == "2026-02-28"
    assert body["previous_end"] == "2026-03-09"


def test_a_backwards_period_is_rejected(client: TestClient, account: Account) -> None:
    response = client.get(
        COMPARISON,
        headers=account.headers,
        params={"period_start": "2026-06-01", "period_end": "2026-01-01"},
    )

    assert response.status_code == 422


# ─── Comparison: the figures ──────────────────────────────────────────────


def test_a_rise_is_reported_with_its_percentage(client: TestClient, account: Account) -> None:
    record(client, account, amount="1000.00", day="2026-02-10")
    record(client, account, amount="1500.00", day="2026-03-10")

    change = comparison(client, account)["expense"]

    assert change["current"] == "1500.00"
    assert change["previous"] == "1000.00"
    assert change["difference"] == "500.00"
    assert change["percentage"] == "50.00"


def test_a_fall_is_a_negative_difference(client: TestClient, account: Account) -> None:
    record(client, account, amount="2000.00", day="2026-02-10")
    record(client, account, amount="500.00", day="2026-03-10")

    change = comparison(client, account)["expense"]

    assert change["difference"] == "-1500.00"
    assert change["percentage"] == "-75.00"


def test_starting_from_nothing_has_no_percentage(client: TestClient, account: Account) -> None:
    """Going from nothing to something is a start, not an increase of any %."""
    record(client, account, amount="500.00", day="2026-03-10")

    change = comparison(client, account)["expense"]

    assert change["previous"] == "0.00"
    assert change["percentage"] is None
    assert change["is_new"] is True


def test_two_empty_periods_are_not_new(client: TestClient, account: Account) -> None:
    change = comparison(client, account)["expense"]

    assert change["percentage"] is None
    assert change["is_new"] is False


def test_income_and_net_are_compared_too(client: TestClient, account: Account) -> None:
    record(client, account, amount="1000.00", day="2026-02-10", category="Salary", kind="income")
    record(client, account, amount="3000.00", day="2026-03-10", category="Salary", kind="income")

    body = comparison(client, account)

    assert body["income"]["difference"] == "2000.00"
    assert body["net"]["difference"] == "2000.00"


# ─── Comparison: categories ───────────────────────────────────────────────


def test_categories_are_ordered_by_biggest_movement(client: TestClient, account: Account) -> None:
    record(client, account, amount="100.00", day="2026-03-10", category="Food")
    record(client, account, amount="900.00", day="2026-03-10", category="Rent")

    names = [row["name"] for row in comparison(client, account)["categories"]]

    assert names[0] == "Rent"


def test_a_large_fall_ranks_as_high_as_a_large_rise(client: TestClient, account: Account) -> None:
    """Sorting by the signed value would bury the most useful finding."""
    record(client, account, amount="5000.00", day="2026-02-10", category="Shopping")
    record(client, account, amount="200.00", day="2026-03-10", category="Food")

    rows = comparison(client, account)["categories"]

    assert rows[0]["name"] == "Shopping"
    assert rows[0]["change"]["difference"] == "-5000.00"


def test_a_category_only_in_the_previous_period_still_appears(
    client: TestClient, account: Account
) -> None:
    """Something the user *stopped* spending on is exactly what to surface."""
    record(client, account, amount="800.00", day="2026-02-10", category="Entertainment")

    rows = comparison(client, account)["categories"]

    assert [row["name"] for row in rows] == ["Entertainment"]
    assert rows[0]["change"]["current"] == "0.00"
    assert rows[0]["change"]["previous"] == "800.00"


def test_a_category_only_in_the_current_period_appears_as_new(
    client: TestClient, account: Account
) -> None:
    record(client, account, amount="300.00", day="2026-03-10", category="Healthcare")

    rows = comparison(client, account)["categories"]

    assert rows[0]["name"] == "Healthcare"
    assert rows[0]["change"]["is_new"] is True


def test_a_category_in_both_periods_appears_once(client: TestClient, account: Account) -> None:
    record(client, account, amount="400.00", day="2026-02-10", category="Food")
    record(client, account, amount="600.00", day="2026-03-10", category="Food")

    rows = comparison(client, account)["categories"]

    assert len(rows) == 1
    assert rows[0]["change"]["difference"] == "200.00"


def test_the_breakdown_carries_the_category_colour(client: TestClient, account: Account) -> None:
    record(client, account, amount="400.00", day="2026-03-10", category="Food")

    row = comparison(client, account)["categories"][0]

    assert row["color"] is not None
    assert row["category_id"] is not None


def test_income_is_not_in_the_category_comparison(client: TestClient, account: Account) -> None:
    record(client, account, amount="45000.00", day="2026-03-01", category="Salary", kind="income")

    assert comparison(client, account)["categories"] == []


def test_the_comparison_is_per_user(
    client: TestClient, account: Account, other_account: Account
) -> None:
    record(client, other_account, amount="9999.00", day="2026-03-10")

    body = comparison(client, account)

    assert body["expense"]["current"] == "0.00"
    assert body["categories"] == []


def test_the_comparison_requires_authentication(client: TestClient) -> None:
    assert client.get(COMPARISON).status_code == 401


def test_every_figure_is_a_json_string(client: TestClient, account: Account) -> None:
    record(client, account, amount="1000.00", day="2026-02-10")
    record(client, account, amount="1500.00", day="2026-03-10")

    raw = client.get(COMPARISON, headers=account.headers, params=MARCH).text.replace(" ", "")

    assert '"difference":"500.00"' in raw
    assert '"percentage":"50.00"' in raw
