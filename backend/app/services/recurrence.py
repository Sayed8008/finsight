"""Finding subscriptions hidden in ordinary transaction history.

The only part of this project that is a genuine algorithm rather than CRUD plus
arithmetic (ADR-007), and the one that addresses a real problem: money leaving
on a standing order is money nobody notices leaving.

Pure — dates, `Decimal`s and strings in, candidates out. No database, no clock.
The same shape as `insight_rules`, and for the same reasons.

Four steps, each of which can be wrong on its own and is therefore separately
tested:

1. **Normalise the description**, so "NETFLIX.COM 4021" and "Netflix.com" are
   recognised as the same merchant and a reference number does not make every
   charge unique.
2. **Cluster by amount**, with tolerance — a subscription whose price rose from
   499 to 549 is still one subscription, and exact matching would split it in
   two and then find neither half recurring.
3. **Score the intervals.** Three charges 30, 31 and 29 days apart are monthly.
   30, 5 and 62 are not, however tidy the amounts.
4. **Explain the confidence.** "Four charges of 499.00, 30±1 days apart" is
   something a person can check. "87%" is not — so the evidence *is* the
   confidence, and the level is derived from it rather than the other way
   round.

**Detection never creates anything** (ADR-007). It proposes; the user decides.
A wrong guess appearing silently in someone's monthly commitment would be worse
than missing it altogether — which is also why the thresholds below lean
towards saying nothing.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from app.core.money import quantise
from app.models.enums import BillingCycle

# ─── Normalisation ────────────────────────────────────────────────────────

#: Words that identify a payment rather than a merchant. Stripped so that
#: "POS PURCHASE NETFLIX" and "NETFLIX" are the same thing. Kept short on
#: purpose: every word here is one that can no longer distinguish two
#: merchants, so an over-long list starts merging things that differ.
NOISE_WORDS = frozenset(
    {
        "pos",
        "purchase",
        "payment",
        "pmt",
        "txn",
        "transaction",
        "debit",
        "credit",
        "card",
        "auto",
        "autopay",
        "recurring",
        "subscription",
        "www",
        "com",
        "net",
        "org",
        "ltd",
        "limited",
        "inc",
        "llc",
        "bv",
        "co",
    }
)

#: Shorter than this after normalising and the description carries no merchant
#: — "POS 4021" reduces to nothing usable, and guessing from it would be
#: inventing rather than detecting.
MIN_MERCHANT_LENGTH = 3


# ─── Thresholds ───────────────────────────────────────────────────────────

#: Fewer charges than this and there is no interval worth scoring: two charges
#: give one gap, and one gap is a coincidence rather than a pattern.
MIN_OCCURRENCES = 3

#: How far apart two amounts can be and still be the same subscription. A
#: price rise of 10% is common; 15% leaves room for one without merging a
#: 499 plan with a 999 one.
AMOUNT_TOLERANCE = Decimal("0.15")

#: An absolute floor, so small amounts cluster sensibly — 15% of 20.00 is
#: 3.00, which would split charges that differ by a rounding.
MIN_AMOUNT_TOLERANCE = Decimal("5.00")

#: Typical length of each cycle in days. Months and years are not whole
#: numbers of days, and pretending otherwise makes a yearly subscription look
#: irregular by five days every leap year.
CYCLE_DAYS: dict[BillingCycle, float] = {
    BillingCycle.WEEKLY: 7.0,
    BillingCycle.MONTHLY: 30.44,
    BillingCycle.QUARTERLY: 91.31,
    BillingCycle.YEARLY: 365.25,
}

#: How far the median gap may sit from a cycle's nominal length, as a share of
#: that length. Generous for short cycles, where a weekend delay is a large
#: proportion of a week.
CYCLE_TOLERANCE = 0.25

#: Below this regularity a run of charges is not a subscription, it is a habit.
MIN_REGULARITY = 0.55


class Confidence(StrEnum):
    """How much a candidate is worth believing.

    Three levels rather than a percentage. A percentage implies a precision the
    method does not have, and invites the interface to sort by a number nobody
    can check. The evidence is what a person actually verifies against.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


CONFIDENCE_ORDER: dict[Confidence, int] = {
    Confidence.HIGH: 0,
    Confidence.MEDIUM: 1,
    Confidence.LOW: 2,
}


# ─── Inputs and outputs ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Charge:
    """One transaction, as the detector sees it."""

    transaction_id: int
    date: date
    amount: Decimal
    description: str
    category_id: int | None = None


@dataclass(frozen=True)
class Candidate:
    """A possible subscription, with everything needed to judge it."""

    #: Cleaned-up merchant name, title-cased for display.
    name: str
    amount: Decimal
    billing_cycle: BillingCycle
    confidence: Confidence
    #: The sentence a person checks the guess against.
    evidence: str
    occurrences: int
    first_seen: date
    last_seen: date
    #: Median days between charges, and how much they varied.
    median_interval_days: int
    interval_spread_days: int
    #: The transactions this was built from, so the interface can show them.
    transaction_ids: tuple[int, ...]
    category_id: int | None = None

    @property
    def next_expected(self) -> date:
        """When the next charge would fall if the pattern holds.

        Offered as a starting point for the user to confirm, never as a fact —
        this is a guess built on a guess.
        """
        return self.last_seen + timedelta(days=self.median_interval_days)


# ─── Step 1: normalisation ────────────────────────────────────────────────


def normalise_description(description: str | None) -> str:
    """Reduce a description to the merchant, or to nothing.

    Drops punctuation, any token containing a digit (reference numbers, card
    fragments, dates) and the payment-processor noise words above. What remains
    is the merchant, or — for something like "POS PURCHASE 4021" — nothing at
    all, which is the honest answer.
    """
    if not description:
        return ""

    text = re.sub(r"[^a-z0-9\s]", " ", description.lower())
    kept = [
        token
        for token in text.split()
        if not any(character.isdigit() for character in token) and token not in NOISE_WORDS
    ]

    merchant = " ".join(kept)
    return merchant if len(merchant) >= MIN_MERCHANT_LENGTH else ""


def display_name(merchant: str) -> str:
    """The normalised merchant, cased for a human."""
    return merchant.title()


# ─── Step 2: clustering by amount ─────────────────────────────────────────


def amounts_match(first: Decimal, second: Decimal) -> bool:
    """Whether two amounts are close enough to be the same subscription."""
    smaller = min(first, second)
    allowed = max(smaller * AMOUNT_TOLERANCE, MIN_AMOUNT_TOLERANCE)
    return abs(first - second) <= allowed


def cluster_by_amount(charges: list[Charge]) -> list[list[Charge]]:
    """Split charges for one merchant into groups of similar amount.

    Sorted by amount and grown greedily against the cluster's *first* member,
    not its previous one: chaining against the previous amount lets a cluster
    drift arbitrarily far, so 100, 115, 132, 152 would end up as one group.
    """
    clusters: list[list[Charge]] = []

    for charge in sorted(charges, key=lambda item: item.amount):
        for cluster in clusters:
            if amounts_match(cluster[0].amount, charge.amount):
                cluster.append(charge)
                break
        else:
            clusters.append([charge])

    return clusters


# ─── Step 3: interval scoring ─────────────────────────────────────────────


@dataclass(frozen=True)
class Interval:
    """The rhythm of a set of charges."""

    cycle: BillingCycle
    median_days: int
    spread_days: int
    regularity: float


def gaps_between(dates: list[date]) -> list[int]:
    ordered = sorted(dates)
    return [(later - earlier).days for earlier, later in zip(ordered, ordered[1:], strict=False)]


def closest_cycle(median_days: float) -> BillingCycle | None:
    """The billing cycle a median gap looks like, if any.

    Returns None rather than the nearest match when nothing is close: charges
    45 days apart are not monthly and not quarterly, and calling them either
    would be worse than admitting no pattern was found.
    """
    for cycle, nominal in CYCLE_DAYS.items():
        if abs(median_days - nominal) <= nominal * CYCLE_TOLERANCE:
            return cycle
    return None


def score_intervals(dates: list[date]) -> Interval | None:
    """How regular a set of charges is, and which cycle it fits.

    Regularity is one minus the average deviation from the median gap, as a
    share of that gap. Deviation from the *median* rather than the mean,
    because one missed month should not drag the whole score down — a
    subscription with a skipped charge is still a subscription.
    """
    gaps = gaps_between(dates)
    if len(gaps) < MIN_OCCURRENCES - 1:
        return None

    median_gap = statistics.median(gaps)
    if median_gap <= 0:
        return None

    cycle = closest_cycle(median_gap)
    if cycle is None:
        return None

    deviations = [abs(gap - median_gap) for gap in gaps]
    average_deviation = sum(deviations) / len(deviations)
    regularity = max(0.0, 1.0 - average_deviation / median_gap)

    return Interval(
        cycle=cycle,
        median_days=int(round(median_gap)),
        spread_days=int(round(max(deviations))) if deviations else 0,
        regularity=regularity,
    )


# ─── Step 4: confidence and evidence ──────────────────────────────────────


def rate_confidence(occurrences: int, interval: Interval, amounts: list[Decimal]) -> Confidence:
    """Turn the measurements into a level.

    Three inputs, all of which have to be good for HIGH: enough charges to rule
    out coincidence, gaps that hold their rhythm, and amounts that barely move.
    """
    identical_amounts = len(set(amounts)) == 1

    if occurrences >= 4 and interval.regularity >= 0.85 and identical_amounts:
        return Confidence.HIGH
    if occurrences >= 3 and interval.regularity >= 0.7:
        return Confidence.MEDIUM
    return Confidence.LOW


def describe(occurrences: int, amount: Decimal, interval: Interval, varied_amounts: bool) -> str:
    """The sentence a person checks the guess against.

    Deliberately concrete. "Four charges of 499.00, 30±1 days apart" can be
    verified against the transaction list in a few seconds; "87% confident"
    cannot be checked at all.
    """
    when = (
        f"{interval.median_days}±{interval.spread_days} days apart"
        if interval.spread_days
        else f"exactly {interval.median_days} days apart"
    )
    amount_text = f"about {amount:,.2f}" if varied_amounts else f"{amount:,.2f}"
    return f"{occurrences} charges of {amount_text}, {when}."


# ─── Putting it together ──────────────────────────────────────────────────


def detect(charges: list[Charge]) -> list[Candidate]:
    """Find every recurring pattern worth proposing.

    Ordered by confidence, then by what it costs per month — the expensive
    forgotten subscription is the one worth finding first.
    """
    by_merchant: dict[str, list[Charge]] = {}
    for charge in charges:
        merchant = normalise_description(charge.description)
        if not merchant:
            # No merchant in the description. Not a failure — some descriptors
            # genuinely carry nothing (ADR-007 records this limitation).
            continue
        by_merchant.setdefault(merchant, []).append(charge)

    candidates: list[Candidate] = []
    for merchant, merchant_charges in by_merchant.items():
        for cluster in cluster_by_amount(merchant_charges):
            candidate = _candidate_from(merchant, cluster)
            if candidate is not None:
                candidates.append(candidate)

    candidates.sort(key=lambda item: (CONFIDENCE_ORDER[item.confidence], -item.amount, item.name))
    return candidates


def _candidate_from(merchant: str, cluster: list[Charge]) -> Candidate | None:
    """One cluster, judged. None when it is not a pattern."""
    if len(cluster) < MIN_OCCURRENCES:
        return None

    ordered = sorted(cluster, key=lambda charge: charge.date)
    interval = score_intervals([charge.date for charge in ordered])
    if interval is None or interval.regularity < MIN_REGULARITY:
        return None

    amounts = [charge.amount for charge in ordered]
    # The median, not the mean: one unusual charge should not move the figure
    # the user is asked to confirm.
    typical = quantise(Decimal(statistics.median(amounts)))
    varied = len(set(amounts)) > 1

    return Candidate(
        name=display_name(merchant),
        amount=typical,
        billing_cycle=interval.cycle,
        confidence=rate_confidence(len(ordered), interval, amounts),
        evidence=describe(len(ordered), typical, interval, varied),
        occurrences=len(ordered),
        first_seen=ordered[0].date,
        last_seen=ordered[-1].date,
        median_interval_days=interval.median_days,
        interval_spread_days=interval.spread_days,
        transaction_ids=tuple(charge.transaction_id for charge in ordered),
        category_id=_most_common_category(ordered),
    )


def _most_common_category(charges: list[Charge]) -> int | None:
    """The category these charges were mostly filed under, if any.

    Offered as a suggestion when the user confirms, so a detected subscription
    starts out categorised the way its own transactions already are.
    """
    seen = [charge.category_id for charge in charges if charge.category_id is not None]
    if not seen:
        return None
    return statistics.mode(seen)


__all__ = [
    "AMOUNT_TOLERANCE",
    "MIN_OCCURRENCES",
    "Candidate",
    "Charge",
    "Confidence",
    "Interval",
    "amounts_match",
    "cluster_by_amount",
    "closest_cycle",
    "describe",
    "detect",
    "display_name",
    "gaps_between",
    "normalise_description",
    "rate_confidence",
    "score_intervals",
]
