"""End-to-end tests for the savings journey endpoint.

Three things carry most of the weight:

  * **each month is its own result.** Two identical months each saved the same
    amount; the second did not save both. This is the misreading the whole
    feature was specified against, so it is asserted against real rows through
    the real API rather than against a calculation in isolation.
  * **the month in progress is excluded.** A partial month shows a salary and
    almost no spending early on, and the reverse at the end. Including it would
    make "are you improving?" answer differently depending on the day.
  * **one account cannot see another's.** There is no parameter naming a user,
    so the test that matters is that two accounts with the same months in the
    same database get their own figures.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import Account

SAVINGS = "/api/v1/savings"
CATEGORIES = "/api/v1/categories"
TRANSACTIONS = "/api/v1/transactions"

#: Evaluated as if it were this day, so "the current month" is August 2026 and
#: every completed month before it is fixed rather than moving with the clock.
AUGUST = {"as_of": "2026-08-15"}


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(c["id"] for c in body if c["name"] == name)


def record(
    client: TestClient,
    account: Account,
    *,
    amount: str,
    day: str,
    kind: str = "expense",
    category: str | None = None,
) -> None:
    name = category or ("Salary" if kind == "income" else "Food")
    response = client.post(
        TRANSACTIONS,
        json={
            "amount": amount,
            "transaction_type": kind,
            "category_id": category_id(client, account, name),
            "date": day,
            "description": "test",
        },
        headers=account.headers,
    )
    assert response.status_code == 201, response.text


def month_of(client: TestClient, account: Account, *, income: str, expense: str, day: str) -> None:
    """A month with one income and one expense, both dated inside it."""
    record(client, account, amount=income, day=day, kind="income")
    record(client, account, amount=expense, day=day, kind="expense")


def journey(client: TestClient, account: Account, **params) -> dict:
    response = client.get(
        SAVINGS, params={**AUGUST, **params}, headers=account.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


# ─── The calculation, through the API ─────────────────────────────────────


def test_a_month_reports_its_own_income_expense_and_net(
    client: TestClient, account: Account
) -> None:
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-06-10")

    months = journey(client, account)["months"]

    assert len(months) == 1
    assert months[0]["income"] == "50000.00"
    assert months[0]["expense"] == "30000.00"
    assert months[0]["net"] == "20000.00"
    assert months[0]["rate"] == "40.00"


def test_savings_do_not_accumulate_across_months(
    client: TestClient, account: Account
) -> None:
    """The misreading this feature was specified against. Two identical months
    each saved 20,000 — February did not save 40,000."""
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-01-10")
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-02-10")

    months = journey(client, account)["months"]

    assert [m["net"] for m in months] == ["20000.00", "20000.00"]


def test_a_month_that_overspent_reports_a_deficit(
    client: TestClient, account: Account
) -> None:
    month_of(client, account, income="40000.00", expense="45000.00", day="2026-06-10")

    months = journey(client, account)["months"]

    assert months[0]["net"] == "-5000.00"
    assert months[0]["rate"] == "-12.50"


def test_a_month_with_no_income_is_a_deficit_with_a_zero_rate(
    client: TestClient, account: Account
) -> None:
    record(client, account, amount="5000.00", day="2026-06-10")

    months = journey(client, account)["months"]

    assert months[0]["income"] == "0.00"
    assert months[0]["net"] == "-5000.00"
    assert months[0]["rate"] == "0.00"


# ─── Which months appear ──────────────────────────────────────────────────


def test_the_month_in_progress_is_excluded(client: TestClient, account: Account) -> None:
    """August is the current month on the evaluation date, and a partial month
    is not a savings result."""
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-07-10")
    month_of(client, account, income="50000.00", expense="1000.00", day="2026-08-10")

    months = journey(client, account)["months"]

    assert [(m["year"], m["month"]) for m in months] == [(2026, 7)]


def test_months_come_back_oldest_first(client: TestClient, account: Account) -> None:
    for day in ("2026-06-10", "2026-04-10", "2026-05-10"):
        month_of(client, account, income="50000.00", expense="30000.00", day=day)

    months = journey(client, account)["months"]

    assert [m["month"] for m in months] == [4, 5, 6]


def test_a_month_with_no_activity_at_all_is_left_out(
    client: TestClient, account: Account
) -> None:
    """Not a zero: a month before the account had any activity did not save
    nothing, and a point on the line there would be invented."""
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-04-10")
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-06-10")

    months = journey(client, account)["months"]

    assert [m["month"] for m in months] == [4, 6]


def test_an_account_with_no_history_says_so_rather_than_failing(
    client: TestClient, account: Account
) -> None:
    body = journey(client, account)

    assert body["has_history"] is False
    assert body["months"] == []
    assert body["badges"] == []
    assert body["summary"]["latest"] is None


# ─── The range filter ─────────────────────────────────────────────────────


def six_months(client: TestClient, account: Account) -> None:
    """February through July 2026, saving 1,000 more each month."""
    for index, number in enumerate(range(2, 8)):
        month_of(
            client,
            account,
            income="50000.00",
            expense=f"{40000 - index * 1000}.00",
            day=f"2026-0{number}-10",
        )


def test_a_range_returns_the_most_recent_months(
    client: TestClient, account: Account
) -> None:
    six_months(client, account)

    months = journey(client, account, months=3)["months"]

    assert [m["month"] for m in months] == [5, 6, 7]


def test_each_month_stays_its_own_point_rather_than_being_combined(
    client: TestClient, account: Account
) -> None:
    """"Last 3 months" is three points, not one total."""
    six_months(client, account)

    months = journey(client, account, months=3)["months"]

    assert len(months) == 3
    assert len({m["net"] for m in months}) == 3


def test_asking_for_more_months_than_exist_returns_what_there_is(
    client: TestClient, account: Account
) -> None:
    six_months(client, account)

    assert len(journey(client, account, months=24)["months"]) == 6


def test_all_time_returns_the_whole_history(client: TestClient, account: Account) -> None:
    six_months(client, account)

    assert len(journey(client, account, months=0)["months"]) == 6


def test_every_offered_range_is_accepted(client: TestClient, account: Account) -> None:
    """The five the interface offers, including all-time."""
    six_months(client, account)

    for months in (3, 6, 12, 24, 0):
        response = client.get(
            SAVINGS, params={**AUGUST, "months": months}, headers=account.headers
        )
        assert response.status_code == 200, months


def test_switching_ranges_repeatedly_gives_the_same_answers(
    client: TestClient, account: Account
) -> None:
    """Nothing is cached or accumulated server-side, so the fifth request for
    three months matches the first."""
    six_months(client, account)

    first = journey(client, account, months=3)
    for months in (6, 24, 0, 3, 12, 3):
        journey(client, account, months=months)
    last = journey(client, account, months=3)

    assert first == last


def test_a_negative_range_is_refused(client: TestClient, account: Account) -> None:
    response = client.get(SAVINGS, params={"months": -1}, headers=account.headers)

    assert response.status_code == 422


def test_an_absurd_range_is_refused(client: TestClient, account: Account) -> None:
    response = client.get(SAVINGS, params={"months": 100000}, headers=account.headers)

    assert response.status_code == 422


# ─── The summary ──────────────────────────────────────────────────────────


def test_the_summary_names_the_latest_previous_and_best_months(
    client: TestClient, account: Account
) -> None:
    six_months(client, account)

    summary = journey(client, account)["summary"]

    assert summary["latest"]["month"] == 7
    assert summary["previous"]["month"] == 6
    assert summary["best"]["month"] == 7
    assert summary["is_personal_best"] is True


def test_the_summary_reports_the_change_in_money(
    client: TestClient, account: Account
) -> None:
    six_months(client, account)

    assert journey(client, account)["summary"]["change"] == "1000.00"


def test_the_change_percentage_is_null_against_a_month_that_saved_nothing(
    client: TestClient, account: Account
) -> None:
    """"Up 300% from minus 2,000" is arithmetic that means nothing."""
    month_of(client, account, income="40000.00", expense="45000.00", day="2026-06-10")
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-07-10")

    summary = journey(client, account)["summary"]

    assert summary["change_percentage"] is None
    assert summary["change"] == "25000.00"


def test_the_summary_describes_the_whole_history_not_the_window(
    client: TestClient, account: Account
) -> None:
    """Narrowing the chart to three months must not retract a personal best
    that really happened."""
    six_months(client, account)

    narrow = journey(client, account, months=3)["summary"]
    wide = journey(client, account, months=0)["summary"]

    assert narrow == wide


# ─── Badges ───────────────────────────────────────────────────────────────


def test_badges_are_earned_from_real_history(client: TestClient, account: Account) -> None:
    six_months(client, account)

    codes = {b["code"] for b in journey(client, account)["badges"]}

    assert "personal_best" in codes
    assert "consistent_saver" in codes
    assert "improving" in codes


def test_badges_survive_narrowing_the_range(client: TestClient, account: Account) -> None:
    six_months(client, account)

    wide = journey(client, account, months=0)["badges"]
    narrow = journey(client, account, months=3)["badges"]

    assert wide == narrow


def test_an_account_that_only_overspent_earns_nothing(
    client: TestClient, account: Account
) -> None:
    month_of(client, account, income="40000.00", expense="45000.00", day="2026-06-10")

    assert journey(client, account)["badges"] == []


def test_observations_are_returned_and_name_their_figures(
    client: TestClient, account: Account
) -> None:
    six_months(client, account)

    lines = journey(client, account)["observations"]

    assert lines
    assert all(any(ch.isdigit() for ch in line) for line in lines)


# ─── Authentication and isolation ─────────────────────────────────────────


def test_the_endpoint_requires_authentication(client: TestClient) -> None:
    assert client.get(SAVINGS).status_code == 401


def test_a_bad_token_is_refused(client: TestClient) -> None:
    response = client.get(SAVINGS, headers={"Authorization": "Bearer nonsense"})

    assert response.status_code == 401


def test_one_account_never_sees_another_history(
    client: TestClient, account: Account, other_account: Account
) -> None:
    """Both have activity in the same months of the same database. Each must
    get only its own figures."""
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-06-10")
    month_of(client, other_account, income="90000.00", expense="10000.00", day="2026-06-10")

    mine = journey(client, account)["months"]
    theirs = journey(client, other_account)["months"]

    assert [m["net"] for m in mine] == ["20000.00"]
    assert [m["net"] for m in theirs] == ["80000.00"]


def test_an_account_with_no_transactions_is_not_shown_anothers(
    client: TestClient, account: Account, other_account: Account
) -> None:
    month_of(client, account, income="50000.00", expense="30000.00", day="2026-06-10")

    assert journey(client, other_account)["has_history"] is False
