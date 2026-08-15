"""Tests for subscription detection.

Pure, and exhaustive by design: this is the one component whose failure mode is
being *plausibly* wrong rather than raising. A detector that proposes a weekly
grocery shop as a subscription, or splits Netflix into two candidates after a
price rise, produces output that looks entirely reasonable and is useless.

Each of the four steps is tested on its own, because each can be wrong
independently, and then the whole thing is tested end to end on realistic
history.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.enums import BillingCycle
from app.services.recurrence import (
    MAX_OFF_CYCLE,
    MAX_SKIPPED_CYCLES,
    MIN_OCCURRENCES,
    MIN_REGULARITY,
    Candidate,
    Charge,
    Confidence,
    Interval,
    amounts_match,
    closest_cycle,
    cluster_by_amount,
    cycles_in,
    detect,
    display_name,
    gaps_between,
    is_regular_enough,
    normalise_description,
    off_cycle_days,
    score_intervals,
)

START = date(2026, 1, 5)


def charge(
    day: date | str,
    amount: str = "499.00",
    description: str = "NETFLIX.COM",
    transaction_id: int = 0,
    category_id: int | None = None,
) -> Charge:
    return Charge(
        transaction_id=transaction_id,
        date=date.fromisoformat(day) if isinstance(day, str) else day,
        amount=Decimal(amount),
        description=description,
        category_id=category_id,
    )


def monthly_charges(
    count: int,
    *,
    amount: str = "499.00",
    description: str = "NETFLIX.COM",
    start: date = START,
    jitter: tuple[int, ...] = (),
) -> list[Charge]:
    """`count` charges roughly a month apart, optionally with day-level jitter."""
    charges = []
    for index in range(count):
        offset = 30 * index + (jitter[index] if index < len(jitter) else 0)
        charges.append(
            charge(
                start + timedelta(days=offset),
                amount=amount,
                description=description,
                transaction_id=index + 1,
            )
        )
    return charges


# ─── Step 1: normalisation ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NETFLIX.COM", "netflix"),
        ("Netflix.com", "netflix"),
        ("NETFLIX.COM 4021", "netflix"),
        ("netflix", "netflix"),
        # Payment-processor noise carries no merchant.
        ("POS PURCHASE NETFLIX", "netflix"),
        ("AUTOPAY SPOTIFY", "spotify"),
        # Reference numbers must not make every charge unique.
        ("SPOTIFY P0A1B2C3", "spotify"),
        ("SPOTIFY 88213", "spotify"),
        # Multi-word merchants survive.
        ("Google Drive", "google drive"),
        # Punctuation is separation, not content.
        ("ADOBE*CREATIVE", "adobe creative"),
    ],
)
def test_normalisation_finds_the_merchant(raw: str, expected: str) -> None:
    assert normalise_description(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        "   ",
        "4021",
        # The case ADR-007 records as unmatchable, and it must stay that way:
        # guessing a merchant from this would be inventing one.
        "POS PURCHASE 4021",
        "TXN 99881",
    ],
)
def test_a_description_with_no_merchant_yields_nothing(raw: str | None) -> None:
    assert normalise_description(raw) == ""


def test_two_spellings_of_one_merchant_agree() -> None:
    """The whole point of step one."""
    assert normalise_description("NETFLIX.COM 4021") == normalise_description("Netflix.com")


def test_two_different_merchants_stay_apart() -> None:
    """The failure that matters more: merging things that differ."""
    assert normalise_description("Google Drive") != normalise_description("Google Play")


def test_display_name_is_cased_for_a_person() -> None:
    assert display_name("netflix") == "Netflix"
    assert display_name("google drive") == "Google Drive"


# ─── Step 2: amount clustering ────────────────────────────────────────────


def test_identical_amounts_cluster() -> None:
    assert amounts_match(Decimal("499.00"), Decimal("499.00"))


def test_a_modest_price_rise_stays_one_subscription() -> None:
    """499 to 549 is a price rise, not a second subscription."""
    assert amounts_match(Decimal("499.00"), Decimal("549.00"))


def test_a_different_plan_is_a_different_subscription() -> None:
    assert not amounts_match(Decimal("499.00"), Decimal("999.00"))


def test_small_amounts_get_an_absolute_floor() -> None:
    """15% of 20.00 is 3.00, which would split a rounding difference."""
    assert amounts_match(Decimal("20.00"), Decimal("24.00"))


def test_clustering_separates_two_plans_from_one_merchant() -> None:
    charges = [
        charge(START, "499.00"),
        charge(START + timedelta(days=30), "499.00"),
        charge(START, "1999.00"),
        charge(START + timedelta(days=30), "1999.00"),
    ]

    clusters = cluster_by_amount(charges)

    assert sorted(len(cluster) for cluster in clusters) == [2, 2]


def test_a_cluster_cannot_drift_by_chaining() -> None:
    """Grown against the cluster's first member, not its previous one.

    Chaining would let 100 → 115 → 132 → 152 become one group, which is a 52%
    spread being treated as a single price.
    """
    charges = [
        charge(START, "100.00"),
        charge(START, "115.00"),
        charge(START, "132.00"),
        charge(START, "152.00"),
    ]

    clusters = cluster_by_amount(charges)

    assert len(clusters) > 1


# ─── Step 3: interval scoring ─────────────────────────────────────────────


def test_gaps_are_measured_between_sorted_dates() -> None:
    dates = [date(2026, 3, 1), date(2026, 1, 1), date(2026, 2, 1)]

    assert gaps_between(dates) == [31, 28]


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (7, BillingCycle.WEEKLY),
        (30, BillingCycle.MONTHLY),
        (31, BillingCycle.MONTHLY),
        (28, BillingCycle.MONTHLY),
        (91, BillingCycle.QUARTERLY),
        (365, BillingCycle.YEARLY),
    ],
)
def test_a_gap_is_matched_to_its_cycle(days: int, expected: BillingCycle) -> None:
    assert closest_cycle(days) is expected


@pytest.mark.parametrize("days", [1, 3, 17, 45, 200])
def test_a_gap_matching_no_cycle_returns_nothing(days: int) -> None:
    """45 days is neither monthly nor quarterly, and calling it either is worse
    than admitting no pattern was found."""
    assert closest_cycle(days) is None


def test_regular_monthly_charges_score_highly() -> None:
    interval = score_intervals([charge.date for charge in monthly_charges(4)])

    assert interval is not None
    assert interval.cycle is BillingCycle.MONTHLY
    assert interval.regularity > 0.95
    assert interval.spread_days == 0


def test_a_few_days_of_jitter_is_still_monthly() -> None:
    """Weekends and bank holidays move charges. This must survive that."""
    dates = [charge.date for charge in monthly_charges(4, jitter=(0, 1, -2, 1))]

    interval = score_intervals(dates)

    assert interval is not None
    assert interval.cycle is BillingCycle.MONTHLY
    assert interval.regularity > 0.8


def test_irregular_charges_are_measured_and_then_refused() -> None:
    """30, 5 and 62 days apart is a habit, not a subscription.

    The scorer *measures*; it does not judge. It reports the rhythm and
    `is_regular_enough` applies the thresholds — which is why this still gets
    an interval and still never reaches the user.

    Worth reading closely, because what disqualifies this run is not what it
    looks like. The 62-day gap is a month with a charge missing and is scored
    as such; the 5-day gap is the one that cannot be any whole number of
    monthly cycles, and it is the reason the run is refused.
    """
    dates = [
        START,
        START + timedelta(days=30),
        START + timedelta(days=35),
        START + timedelta(days=97),
    ]

    interval = score_intervals(dates)

    assert interval is not None
    assert is_regular_enough(interval) is False
    assert interval.spread_days > interval.median_days * MAX_OFF_CYCLE


def test_irregular_charges_are_never_proposed() -> None:
    """The threshold, applied where the decision is actually made."""
    charges = [
        charge(START, "499.00", transaction_id=1),
        charge(START + timedelta(days=30), "499.00", transaction_id=2),
        charge(START + timedelta(days=35), "499.00", transaction_id=3),
        charge(START + timedelta(days=97), "499.00", transaction_id=4),
    ]

    assert detect(charges) == []


def test_two_charges_are_not_enough_to_judge() -> None:
    """One gap is a coincidence."""
    assert score_intervals([START, START + timedelta(days=30)]) is None


def test_a_missed_month_does_not_destroy_the_score() -> None:
    """Deviation is measured from the median, so one skipped charge does not
    drag a genuine subscription below the threshold."""
    dates = [
        START,
        START + timedelta(days=30),
        START + timedelta(days=60),
        # A month missed here.
        START + timedelta(days=120),
        START + timedelta(days=150),
    ]

    interval = score_intervals(dates)

    assert interval is not None
    assert interval.cycle is BillingCycle.MONTHLY


# ─── Step 4: end to end ───────────────────────────────────────────────────


def only_candidate(charges: list[Charge]) -> Candidate:
    found = detect(charges)
    assert len(found) == 1, [candidate.name for candidate in found]
    return found[0]


def test_a_clean_monthly_subscription_is_found() -> None:
    candidate = only_candidate(monthly_charges(5))

    assert candidate.name == "Netflix"
    assert candidate.amount == Decimal("499.00")
    assert candidate.billing_cycle is BillingCycle.MONTHLY
    assert candidate.confidence is Confidence.HIGH
    assert candidate.occurrences == 5


def test_the_evidence_is_something_a_person_can_check() -> None:
    """ "87% confident" cannot be verified. This can, against the transactions."""
    candidate = only_candidate(monthly_charges(4))

    assert "4 charges" in candidate.evidence
    assert "499.00" in candidate.evidence
    assert "30" in candidate.evidence


def test_the_evidence_admits_when_amounts_varied() -> None:
    charges = monthly_charges(4)
    charges[-1] = charge(charges[-1].date, "549.00", transaction_id=99)

    candidate = only_candidate(charges)

    assert "about" in candidate.evidence


def test_a_candidate_names_the_transactions_it_came_from() -> None:
    """So the interface can show its work rather than asking to be trusted."""
    charges = monthly_charges(4)

    candidate = only_candidate(charges)

    assert set(candidate.transaction_ids) == {c.transaction_id for c in charges}


def test_a_price_rise_stays_one_candidate() -> None:
    """Exact matching would split this in two and then find neither recurring."""
    charges = monthly_charges(3) + monthly_charges(
        3, amount="549.00", start=START + timedelta(days=90)
    )
    for index, item in enumerate(charges):
        charges[index] = Charge(
            transaction_id=index + 1,
            date=item.date,
            amount=item.amount,
            description=item.description,
        )

    candidate = only_candidate(charges)

    assert candidate.occurrences == 6


def test_two_plans_from_one_merchant_are_two_candidates() -> None:
    charges = monthly_charges(4) + monthly_charges(4, amount="1999.00")
    for index, item in enumerate(charges):
        charges[index] = Charge(
            transaction_id=index + 1,
            date=item.date,
            amount=item.amount,
            description=item.description,
        )

    found = detect(charges)

    assert len(found) == 2
    assert {candidate.amount for candidate in found} == {
        Decimal("499.00"),
        Decimal("1999.00"),
    }


def test_a_weekly_grocery_shop_is_not_proposed() -> None:
    """The false positive that would make the feature worthless.

    Irregular days, irregular amounts — recognisably a habit rather than a
    standing order.
    """
    charges = [
        charge("2026-01-05", "1250.00", "SHWAPNO SUPERSTORE", 1),
        charge("2026-01-11", "980.50", "SHWAPNO SUPERSTORE", 2),
        charge("2026-01-19", "2100.75", "SHWAPNO SUPERSTORE", 3),
        charge("2026-01-24", "760.00", "SHWAPNO SUPERSTORE", 4),
        charge("2026-02-03", "1890.25", "SHWAPNO SUPERSTORE", 5),
    ]

    assert detect(charges) == []


def test_too_few_charges_is_not_a_pattern() -> None:
    assert detect(monthly_charges(MIN_OCCURRENCES - 1)) == []


def test_descriptions_carrying_no_merchant_are_skipped() -> None:
    """ADR-007 records this limitation. Returning nonsense would be worse."""
    charges = [
        charge("2026-01-05", "499.00", "POS PURCHASE 4021", 1),
        charge("2026-02-04", "499.00", "POS PURCHASE 4022", 2),
        charge("2026-03-06", "499.00", "POS PURCHASE 4023", 3),
    ]

    assert detect(charges) == []


def test_a_yearly_subscription_is_found() -> None:
    charges = [
        charge("2024-03-01", "5200.00", "ADOBE", 1),
        charge("2025-03-02", "5200.00", "ADOBE", 2),
        charge("2026-03-01", "5200.00", "ADOBE", 3),
    ]

    candidate = only_candidate(charges)

    assert candidate.billing_cycle is BillingCycle.YEARLY


def test_a_weekly_subscription_is_found() -> None:
    charges = [
        charge(START + timedelta(days=7 * index), "150.00", "CLEANER", index + 1)
        for index in range(5)
    ]

    candidate = only_candidate(charges)

    assert candidate.billing_cycle is BillingCycle.WEEKLY


def test_the_next_charge_is_projected_from_the_last(qtbot=None) -> None:
    candidate = only_candidate(monthly_charges(4))

    assert candidate.next_expected == candidate.last_seen + timedelta(days=30)


def test_the_suggested_category_is_the_one_mostly_used() -> None:
    charges = monthly_charges(4)
    charges = [
        Charge(c.transaction_id, c.date, c.amount, c.description, category_id=7 if i < 3 else 9)
        for i, c in enumerate(charges)
    ]

    assert only_candidate(charges).category_id == 7


def test_candidates_are_ordered_by_confidence_then_cost() -> None:
    """The expensive forgotten subscription is the one worth finding first."""
    strong_cheap = monthly_charges(5, amount="199.00", description="SPOTIFY")
    strong_dear = monthly_charges(5, amount="1999.00", description="ADOBE")
    charges = strong_cheap + strong_dear
    charges = [
        Charge(index + 1, c.date, c.amount, c.description) for index, c in enumerate(charges)
    ]

    found = detect(charges)

    assert [candidate.name for candidate in found] == ["Adobe", "Spotify"]


def test_detection_returns_proposals_and_nothing_else() -> None:
    """ADR-007: it never creates. The return type is the guarantee — there is
    no session here to create anything with."""
    found = detect(monthly_charges(4))

    assert all(isinstance(candidate, Candidate) for candidate in found)


# ─── Gaps are measured against whole cycles ───────────────────────────────
#
# The fix for a real defect: charges 29, 124 and 98 days apart scored 0.68
# regularity and were proposed as quarterly, carrying the evidence "98±69 days
# apart" — a sentence that refutes itself. An average absorbs one wild gap
# among tidy ones almost entirely, so regularity alone could never catch it.


def test_an_ordinary_gap_is_one_cycle() -> None:
    assert cycles_in(30, 30.0) == 1
    assert off_cycle_days(30, 30.0) == 0


def test_a_missed_charge_is_two_cycles_rather_than_a_wild_gap() -> None:
    """Measured against the median it is thirty days out; measured against the
    nearest multiple it is exactly on cycle, with one charge absent."""
    assert cycles_in(60, 30.0) == 2
    assert off_cycle_days(60, 30.0) == 0


def test_a_gap_that_is_no_whole_number_of_cycles_is_far_off() -> None:
    assert off_cycle_days(45, 30.0) == 15


def test_a_gap_shorter_than_a_cycle_cannot_be_a_multiple_of_it() -> None:
    """The case that catches most real noise: a run of roughly quarterly
    charges with one pair five weeks apart is not quarterly."""
    assert cycles_in(13, 82.0) == 1
    assert off_cycle_days(13, 82.0) == 69


def test_the_number_of_cycles_searched_is_bounded() -> None:
    """Unbounded, every long gap is near *some* multiple and the measurement
    means nothing for exactly the runs it exists to reject."""
    assert cycles_in(300, 30.0) == MAX_SKIPPED_CYCLES
    assert off_cycle_days(300, 30.0) == 240


def test_two_consecutive_skips_are_not_a_subscription() -> None:
    """A bound of three was tried and introduced a false positive that had not
    been there: four cinema tickets 30, 90 and 32 days apart read as "monthly,
    with two charges missing". Arithmetically available, and not what
    happened."""
    dates = [
        START,
        START + timedelta(days=30),
        START + timedelta(days=120),
        START + timedelta(days=152),
    ]

    interval = score_intervals(dates)

    assert interval is not None
    assert is_regular_enough(interval) is False


def test_a_subscription_with_a_missed_month_is_still_a_subscription() -> None:
    """The tolerance the scorer has always claimed, now actually delivered:
    measured against the median, this run scored 0.67 and printed "30±30 days
    apart" — a range from nothing to two months, offered as evidence."""
    dates = [
        START,
        START + timedelta(days=30),
        START + timedelta(days=90),  # the 60-day gap: one charge missing
        START + timedelta(days=120),
    ]

    interval = score_intervals(dates)

    assert interval is not None
    assert is_regular_enough(interval) is True
    assert interval.spread_days == 0
    assert interval.missed_charges == 1


def test_a_run_with_one_wild_gap_is_refused() -> None:
    """29, 124 and 98 days apart — the defect this rule exists for. Its
    regularity is comfortably above the floor; only the worst gap gives it
    away."""
    dates = [
        START,
        START + timedelta(days=29),
        START + timedelta(days=153),
        START + timedelta(days=251),
    ]

    interval = score_intervals(dates)

    assert interval is not None
    assert interval.regularity >= MIN_REGULARITY, "regularity alone would let this through"
    assert is_regular_enough(interval) is False


def test_the_ceiling_currently_subsumes_the_regularity_floor() -> None:
    """Written to fail if somebody relaxes the ceiling without thinking.

    The average deviation is never greater than the worst one, so passing
    `MAX_OFF_CYCLE` already guarantees a regularity of `1 - MAX_OFF_CYCLE`. As
    long as that is above `MIN_REGULARITY`, the floor cannot fire — which is
    fine, and is stated in `is_regular_enough`, but stops being true the moment
    the ceiling goes past 0.45. This is the test that says so out loud instead
    of leaving a dead threshold nobody notices.
    """
    assert 1 - MAX_OFF_CYCLE > MIN_REGULARITY


def test_the_regularity_floor_still_refuses_what_it_is_there_for() -> None:
    """Exercised directly, since the ceiling gets to these runs first."""
    ragged = Interval(
        cycle=BillingCycle.MONTHLY,
        median_days=30,
        spread_days=6,
        regularity=0.4,
    )

    assert is_regular_enough(ragged) is False


def test_the_printed_spread_never_contradicts_the_printed_interval() -> None:
    """The property the whole rule exists to guarantee, stated as itself: any
    candidate that reaches a user carries evidence that does not refute itself
    (ADR-032)."""
    charges = [
        charge(START, "742.50", transaction_id=1),
        charge(START + timedelta(days=29), "742.50", transaction_id=2),
        charge(START + timedelta(days=153), "742.50", transaction_id=3),
        charge(START + timedelta(days=251), "742.50", transaction_id=4),
        charge(START + timedelta(days=281), "499.00", transaction_id=5),
        charge(START + timedelta(days=311), "499.00", transaction_id=6),
        charge(START + timedelta(days=341), "499.00", transaction_id=7),
    ]

    for candidate in detect(charges):
        assert candidate.interval_spread_days <= (
            candidate.median_interval_days * MAX_OFF_CYCLE
        ), candidate.evidence


def test_evidence_names_a_missing_charge_rather_than_glossing_over_it() -> None:
    """"Exactly 30 days apart" for a run containing a 60-day gap is technically
    defensible and reads as a claim about charges nobody made."""
    charges = [
        charge(START, "499.00", transaction_id=1),
        charge(START + timedelta(days=30), "499.00", transaction_id=2),
        charge(START + timedelta(days=90), "499.00", transaction_id=3),
        charge(START + timedelta(days=120), "499.00", transaction_id=4),
    ]

    candidate = detect(charges)[0]

    assert "1 charge in that run appears to be missing" in candidate.evidence


def test_a_gap_in_the_record_costs_confidence() -> None:
    """A run with a hole in it may well be a subscription. It is not one to be
    most confident about."""
    charges = [
        charge(START + timedelta(days=30 * index), "499.00", transaction_id=index)
        for index in range(5)
    ]
    with_hole = [c for c in charges if c.transaction_id != 2]

    assert detect(charges)[0].confidence is Confidence.HIGH
    assert detect(with_hole)[0].confidence is not Confidence.HIGH
