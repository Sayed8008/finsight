"""End-to-end tests for the subscription endpoints.

The themes: `next_billing_date` is derived and never accepted; renewals are
computed from the original anchor so month-end subscriptions do not drift;
paused subscriptions stay visible but stop costing anything; and a nullable
category must not make rows disappear.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import Account, QueryCounter

SUBSCRIPTIONS = "/api/v1/subscriptions"
CATEGORIES = "/api/v1/categories"

TODAY = {"as_of": "2026-03-15"}


def category_id(client: TestClient, account: Account, name: str) -> int:
    body = client.get(CATEGORIES, headers=account.headers).json()
    return next(c["id"] for c in body if c["name"] == name)


def track(client: TestClient, account: Account, **overrides: object) -> dict:
    payload = {
        "name": "Netflix",
        "amount": "499.00",
        "billing_cycle": "monthly",
        "start_date": "2026-01-10",
        **overrides,
    }
    response = client.post(SUBSCRIPTIONS, json=payload, headers=account.headers, params=TODAY)
    assert response.status_code == 201, response.text
    return response.json()


def fetch(client: TestClient, account: Account, subscription_id: int, **params: object) -> dict:
    response = client.get(
        f"{SUBSCRIPTIONS}/{subscription_id}", headers=account.headers, params={**TODAY, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


# ─── Creating ─────────────────────────────────────────────────────────────


def test_tracking_a_subscription(client: TestClient, account: Account) -> None:
    body = track(client, account)

    assert body["name"] == "Netflix"
    assert body["amount"] == "499.00"
    assert body["billing_cycle"] == "monthly"
    assert body["status"] == "active"


def test_the_next_billing_date_is_derived_not_accepted(
    client: TestClient, account: Account
) -> None:
    """Started 10 January, monthly, today is 15 March — next charge is 10 April."""
    body = track(client, account, start_date="2026-01-10")

    assert body["next_billing_date"] == "2026-04-10"


def test_a_supplied_next_billing_date_is_ignored(client: TestClient, account: Account) -> None:
    """Accepting it would allow a subscription whose own fields disagree."""
    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": "Netflix",
            "amount": "499.00",
            "billing_cycle": "monthly",
            "start_date": "2026-01-10",
            "next_billing_date": "2030-01-01",
        },
        headers=account.headers,
        params=TODAY,
    )

    assert response.status_code == 201
    assert response.json()["next_billing_date"] == "2026-04-10"


def test_a_future_start_date_is_itself_the_first_charge(
    client: TestClient, account: Account
) -> None:
    body = track(client, account, start_date="2026-06-01")

    assert body["next_billing_date"] == "2026-06-01"


def test_a_subscription_starting_today_bills_today(client: TestClient, account: Account) -> None:
    body = track(client, account, start_date="2026-03-15")

    assert body["next_billing_date"] == "2026-03-15"
    assert body["days_until_renewal"] == 0


def test_a_category_is_optional(client: TestClient, account: Account) -> None:
    """Detection in Phase 9.5 produces subscriptions with no category yet."""
    body = track(client, account)

    assert body["category"] is None


def test_a_category_can_be_given(client: TestClient, account: Account) -> None:
    subscriptions = category_id(client, account, "Subscriptions")

    body = track(client, account, category_id=subscriptions)

    assert body["category"]["name"] == "Subscriptions"


def test_another_users_category_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = category_id(client, other_account, "Subscriptions")

    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": "Netflix",
            "amount": "499.00",
            "billing_cycle": "monthly",
            "start_date": "2026-01-10",
            "category_id": theirs,
        },
        headers=account.headers,
    )

    assert response.status_code == 404


def test_a_blank_name_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": "   ",
            "amount": "499.00",
            "billing_cycle": "monthly",
            "start_date": "2026-01-10",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_a_zero_amount_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": "Netflix",
            "amount": "0.00",
            "billing_cycle": "monthly",
            "start_date": "2026-01-10",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_an_unknown_cycle_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": "Netflix",
            "amount": "499.00",
            "billing_cycle": "fortnightly",
            "start_date": "2026-01-10",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_an_end_date_before_the_start_is_rejected(client: TestClient, account: Account) -> None:
    response = client.post(
        SUBSCRIPTIONS,
        json={
            "name": "Netflix",
            "amount": "499.00",
            "billing_cycle": "monthly",
            "start_date": "2026-06-01",
            "end_date": "2026-01-01",
        },
        headers=account.headers,
    )

    assert response.status_code == 422


def test_creating_requires_authentication(client: TestClient) -> None:
    assert client.post(SUBSCRIPTIONS, json={"name": "x"}).status_code == 401


# ─── Derived costs ────────────────────────────────────────────────────────


def test_monthly_and_yearly_costs_are_derived(client: TestClient, account: Account) -> None:
    body = track(client, account, amount="499.00", billing_cycle="monthly")

    assert body["monthly_cost"] == "499.00"
    assert body["yearly_cost"] == "5988.00"


def test_a_yearly_subscription_is_spread_over_twelve_months(
    client: TestClient, account: Account
) -> None:
    body = track(client, account, amount="6000.00", billing_cycle="yearly")

    assert body["monthly_cost"] == "500.00"
    assert body["yearly_cost"] == "6000.00"


def test_a_weekly_subscription_uses_fifty_two_weeks_not_four_per_month(
    client: TestClient, account: Account
) -> None:
    """Four weeks to a month understates a weekly cost by about 8%."""
    body = track(client, account, amount="100.00", billing_cycle="weekly")

    assert body["monthly_cost"] == "433.33"
    assert body["yearly_cost"] == "5200.00"


def test_costs_are_json_strings(client: TestClient, account: Account) -> None:
    subscription = track(client, account)

    raw = client.get(f"{SUBSCRIPTIONS}/{subscription['id']}", headers=account.headers).text
    compact = raw.replace(" ", "")

    assert '"monthly_cost":"499.00"' in compact
    assert '"amount":"499.00"' in compact


# ─── Renewing, and the month-end trap ─────────────────────────────────────


def test_renewing_advances_to_the_next_charge(client: TestClient, account: Account) -> None:
    subscription = track(client, account, start_date="2026-01-10")
    assert subscription["next_billing_date"] == "2026-04-10"

    body = client.post(
        f"{SUBSCRIPTIONS}/{subscription['id']}/renew", headers=account.headers, params=TODAY
    ).json()

    assert body["next_billing_date"] == "2026-05-10"


def test_a_month_end_subscription_does_not_drift(client: TestClient, account: Account) -> None:
    """The trap this phase was warned about.

    Adding a month to each previous date gives 31 Jan, 28 Feb, 28 Mar — the
    subscription silently leaves the 31st. Computing from the anchor keeps it
    on the last day of each month.
    """
    subscription = track(client, account, start_date="2026-01-31")
    seen = [subscription["next_billing_date"]]

    for _ in range(3):
        body = client.post(
            f"{SUBSCRIPTIONS}/{subscription['id']}/renew", headers=account.headers, params=TODAY
        ).json()
        seen.append(body["next_billing_date"])

    # April has 30 days, so the charge clamps — and then *returns* to the 31st
    # in May. Stepping from each previous date would have stranded it on the
    # 30th from April onwards.
    assert seen == ["2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30"]


def test_renewing_past_the_end_date_cancels_instead(client: TestClient, account: Account) -> None:
    """Better to close it than to invent a charge that will never happen."""
    subscription = track(client, account, start_date="2026-01-10", end_date="2026-04-30")
    assert subscription["next_billing_date"] == "2026-04-10"

    body = client.post(
        f"{SUBSCRIPTIONS}/{subscription['id']}/renew", headers=account.headers, params=TODAY
    ).json()

    assert body["status"] == "cancelled"
    assert body["next_billing_date"] == "2026-04-10"


def test_a_cancelled_subscription_cannot_be_renewed(client: TestClient, account: Account) -> None:
    subscription = track(client, account, status="cancelled")

    response = client.post(f"{SUBSCRIPTIONS}/{subscription['id']}/renew", headers=account.headers)

    assert response.status_code == 422


def test_renewing_another_users_subscription_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = track(client, other_account)

    response = client.post(f"{SUBSCRIPTIONS}/{theirs['id']}/renew", headers=account.headers)

    assert response.status_code == 404


# ─── Renewal timing ───────────────────────────────────────────────────────


def test_days_until_renewal_counts_forward(client: TestClient, account: Account) -> None:
    subscription = track(client, account, start_date="2026-03-20")

    assert fetch(client, account, subscription["id"])["days_until_renewal"] == 5


def test_an_overdue_subscription_reports_negative_days(
    client: TestClient, account: Account
) -> None:
    """An active subscription nobody marked as renewed is overdue, not hidden."""
    subscription = track(client, account, start_date="2026-01-10")

    body = fetch(client, account, subscription["id"], as_of="2026-05-01")

    assert body["days_until_renewal"] < 0
    assert body["is_due_soon"] is True


def test_due_soon_covers_the_next_week(client: TestClient, account: Account) -> None:
    soon = track(client, account, start_date="2026-03-18")
    later = track(client, account, name="Spotify", start_date="2026-04-30")

    assert fetch(client, account, soon["id"])["is_due_soon"] is True
    assert fetch(client, account, later["id"])["is_due_soon"] is False


def test_a_paused_subscription_is_never_due_soon(client: TestClient, account: Account) -> None:
    subscription = track(client, account, start_date="2026-03-16", status="paused")

    assert fetch(client, account, subscription["id"])["is_due_soon"] is False


# ─── Listing and filtering ────────────────────────────────────────────────


def test_listing_is_soonest_renewal_first(client: TestClient, account: Account) -> None:
    track(client, account, name="Later", start_date="2026-05-01")
    track(client, account, name="Sooner", start_date="2026-03-20")

    body = client.get(SUBSCRIPTIONS, headers=account.headers, params=TODAY).json()

    assert [s["name"] for s in body] == ["Sooner", "Later"]


def test_listing_can_be_filtered_by_status(client: TestClient, account: Account) -> None:
    track(client, account, name="Active one")
    track(client, account, name="Paused one", status="paused")

    body = client.get(
        SUBSCRIPTIONS, headers=account.headers, params={**TODAY, "subscription_status": "paused"}
    ).json()

    assert [s["name"] for s in body] == ["Paused one"]


def test_listing_can_be_filtered_by_category(client: TestClient, account: Account) -> None:
    subscriptions = category_id(client, account, "Subscriptions")
    track(client, account, name="Categorised", category_id=subscriptions)
    track(client, account, name="Uncategorised")

    body = client.get(
        SUBSCRIPTIONS, headers=account.headers, params={**TODAY, "category_id": subscriptions}
    ).json()

    assert [s["name"] for s in body] == ["Categorised"]


def test_uncategorised_subscriptions_still_appear(client: TestClient, account: Account) -> None:
    """An inner join on a nullable column would drop exactly these rows."""
    track(client, account, name="Uncategorised")

    body = client.get(SUBSCRIPTIONS, headers=account.headers, params=TODAY).json()

    assert [s["name"] for s in body] == ["Uncategorised"]
    assert body[0]["category"] is None


def test_due_within_days_narrows_to_upcoming(client: TestClient, account: Account) -> None:
    track(client, account, name="This week", start_date="2026-03-18")
    track(client, account, name="Next month", start_date="2026-04-30")

    body = client.get(
        SUBSCRIPTIONS, headers=account.headers, params={**TODAY, "due_within_days": 7}
    ).json()

    assert [s["name"] for s in body] == ["This week"]


def test_an_absurd_lookahead_is_rejected(client: TestClient, account: Account) -> None:
    response = client.get(
        SUBSCRIPTIONS, headers=account.headers, params={"due_within_days": 100000}
    )

    assert response.status_code == 422


def test_listing_shows_only_your_own(
    client: TestClient, account: Account, other_account: Account
) -> None:
    track(client, other_account, name="Theirs")

    assert client.get(SUBSCRIPTIONS, headers=account.headers).json() == []


def test_listing_costs_the_same_however_many_there_are(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    """The category is eager-loaded on the same outer join, so no query per row."""
    track(client, account, name="One")
    query_counter.reset()
    client.get(SUBSCRIPTIONS, headers=account.headers, params=TODAY)
    with_one = len(query_counter.selects)

    for name in ("Two", "Three", "Four", "Five"):
        track(client, account, name=name)
    query_counter.reset()
    body = client.get(SUBSCRIPTIONS, headers=account.headers, params=TODAY).json()
    with_five = len(query_counter.selects)

    assert len(body) == 5
    assert with_one == with_five


# ─── Summary ──────────────────────────────────────────────────────────────


def test_the_summary_totals_active_subscriptions(client: TestClient, account: Account) -> None:
    track(client, account, name="Monthly", amount="500.00", billing_cycle="monthly")
    track(client, account, name="Yearly", amount="1200.00", billing_cycle="yearly")

    body = client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers, params=TODAY).json()

    assert body["active_count"] == 2
    assert body["monthly_total"] == "600.00"
    assert body["yearly_total"] == "7200.00"


def test_paused_subscriptions_are_counted_but_not_charged(
    client: TestClient, account: Account
) -> None:
    """A paused subscription is not being billed, so it must not inflate the total."""
    track(client, account, name="Active", amount="500.00")
    track(client, account, name="Paused", amount="900.00", status="paused")

    body = client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers, params=TODAY).json()

    assert body["active_count"] == 1
    assert body["paused_count"] == 1
    assert body["monthly_total"] == "500.00"


def test_cancelled_subscriptions_are_excluded_from_totals(
    client: TestClient, account: Account
) -> None:
    track(client, account, name="Active", amount="500.00")
    track(client, account, name="Gone", amount="900.00", status="cancelled")

    body = client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers, params=TODAY).json()

    assert body["cancelled_count"] == 1
    assert body["monthly_total"] == "500.00"


def test_the_summary_names_the_next_renewal(client: TestClient, account: Account) -> None:
    track(client, account, name="Later", start_date="2026-05-01")
    track(client, account, name="Sooner", start_date="2026-03-20")

    body = client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers, params=TODAY).json()

    assert body["next_renewal"]["name"] == "Sooner"


def test_an_empty_summary_is_zeroes_not_an_error(client: TestClient, account: Account) -> None:
    body = client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers).json()

    assert body["active_count"] == 0
    assert body["monthly_total"] == "0.00"
    assert body["next_renewal"] is None


def test_summary_is_not_mistaken_for_a_subscription_id(
    client: TestClient, account: Account
) -> None:
    """Route order: declared after `/{id}`, this would be a 422."""
    response = client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers)

    assert response.status_code == 200


def test_the_summary_is_per_user(
    client: TestClient, account: Account, other_account: Account
) -> None:
    track(client, other_account, amount="9999.00")

    body = client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers).json()

    assert body["monthly_total"] == "0.00"


def test_the_summary_costs_a_constant_number_of_queries(
    client: TestClient, account: Account, query_counter: QueryCounter
) -> None:
    for name in ("One", "Two", "Three", "Four", "Five", "Six"):
        track(client, account, name=name)

    query_counter.reset()
    client.get(f"{SUBSCRIPTIONS}/summary", headers=account.headers, params=TODAY)

    # One grouped aggregate, plus one listing for the next renewal, plus the
    # user lookup the auth dependency performs.
    assert len(query_counter.selects) <= 4


# ─── Editing and deleting ─────────────────────────────────────────────────


def test_editing_an_amount(client: TestClient, account: Account) -> None:
    subscription = track(client, account)

    body = client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}", json={"amount": "599.00"}, headers=account.headers
    ).json()

    assert body["amount"] == "599.00"
    assert body["monthly_cost"] == "599.00"


def test_changing_the_cycle_recomputes_the_next_charge(
    client: TestClient, account: Account
) -> None:
    """Leaving it alone would describe a schedule the cycle contradicts."""
    subscription = track(client, account, start_date="2026-01-10")
    assert subscription["next_billing_date"] == "2026-04-10"

    body = client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}",
        json={"billing_cycle": "yearly"},
        headers=account.headers,
        params=TODAY,
    ).json()

    assert body["next_billing_date"] == "2027-01-10"


def test_changing_the_start_date_recomputes_the_next_charge(
    client: TestClient, account: Account
) -> None:
    subscription = track(client, account, start_date="2026-01-10")

    body = client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}",
        json={"start_date": "2026-01-25"},
        headers=account.headers,
        params=TODAY,
    ).json()

    assert body["next_billing_date"] == "2026-03-25"


def test_pausing_and_resuming(client: TestClient, account: Account) -> None:
    subscription = track(client, account)

    paused = client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}", json={"status": "paused"}, headers=account.headers
    ).json()
    assert paused["status"] == "paused"

    resumed = client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}", json={"status": "active"}, headers=account.headers
    ).json()
    assert resumed["status"] == "active"


def test_a_partial_update_leaves_other_fields_alone(client: TestClient, account: Account) -> None:
    subscription = track(client, account, payment_method="card")

    body = client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}", json={"amount": "599.00"}, headers=account.headers
    ).json()

    assert body["payment_method"] == "card"
    assert body["name"] == "Netflix"


def test_moving_the_end_date_before_the_start_is_rejected(
    client: TestClient, account: Account
) -> None:
    """The schema cannot see the stored start date when only the end is sent."""
    subscription = track(client, account, start_date="2026-06-01")

    response = client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}",
        json={"end_date": "2026-01-01"},
        headers=account.headers,
    )

    assert response.status_code == 422


def test_deleting_a_subscription(client: TestClient, account: Account) -> None:
    subscription = track(client, account)

    response = client.delete(f"{SUBSCRIPTIONS}/{subscription['id']}", headers=account.headers)

    assert response.status_code == 204
    assert client.get(SUBSCRIPTIONS, headers=account.headers).json() == []


def test_deleting_is_different_from_cancelling(client: TestClient, account: Account) -> None:
    """Cancelling keeps the record; deleting is for something tracked by mistake."""
    subscription = track(client, account)
    client.patch(
        f"{SUBSCRIPTIONS}/{subscription['id']}",
        json={"status": "cancelled"},
        headers=account.headers,
    )

    body = client.get(SUBSCRIPTIONS, headers=account.headers, params=TODAY).json()

    assert len(body) == 1
    assert body[0]["status"] == "cancelled"


# ─── One user's data is invisible to another ──────────────────────────────


def test_reading_another_users_subscription_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = track(client, other_account)

    assert client.get(f"{SUBSCRIPTIONS}/{theirs['id']}", headers=account.headers).status_code == 404


def test_editing_another_users_subscription_is_a_404(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = track(client, other_account)

    response = client.patch(
        f"{SUBSCRIPTIONS}/{theirs['id']}", json={"amount": "1.00"}, headers=account.headers
    )

    assert response.status_code == 404


def test_deleting_another_users_subscription_is_a_404_and_leaves_it(
    client: TestClient, account: Account, other_account: Account
) -> None:
    theirs = track(client, other_account)

    assert (
        client.delete(f"{SUBSCRIPTIONS}/{theirs['id']}", headers=account.headers).status_code == 404
    )
    assert (
        client.get(f"{SUBSCRIPTIONS}/{theirs['id']}", headers=other_account.headers).status_code
        == 200
    )
