"""Throttling repeated attempts at something.

Pure, in the same sense as `insight_rules` and `recurrence`: the clock is a
parameter rather than something this module reaches for. That is what lets every
threshold and boundary below be tested in three lines instead of with `sleep`,
and it is the only way a test for "the window expires after five minutes" can
run in a millisecond and still mean something.

**What this protects against.** Without it, a login form is an offline password
guesser with a network in front of it. Argon2 makes each guess expensive, which
narrows the gap but does not close it — a few guesses a second, for a week, is a
lot of guesses.

**Why attempts are counted per client address and not per email.** Counting per
email is the obvious design and it is a weapon: anyone who knows an address can
fail ten logins against it and lock the owner out of their own account. The
protection becomes the attack. Counting per address means an attacker can only
throttle themselves.

**Why only failures count.** A successful sign-in clears the record, so somebody
who mistypes their password twice and then gets it right is not one attempt away
from being locked out for five minutes. The thing worth limiting is *guessing*,
and a correct password is not a guess.

**Why the store is bounded.** A dictionary keyed by client address is a
dictionary an attacker chooses the keys of. Left to grow, it is a memory leak
with a hostile author. The oldest entries are dropped once it is full, which is
safe in the direction that matters: the worst case is that a very old, quiet
attacker gets their allowance back.
"""

from __future__ import annotations

import logging
from collections import OrderedDict, deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: How many distinct keys to track before the least recently seen are dropped.
#: Ten thousand addresses is far beyond anything this application will meet and
#: still a bounded amount of memory.
DEFAULT_CAPACITY = 10_000


@dataclass(frozen=True)
class Decision:
    """Whether an attempt is allowed, and what to tell the caller if not."""

    allowed: bool
    #: Attempts left in the current window. Zero once refused.
    remaining: int
    #: Whole seconds until the oldest attempt falls out of the window. Always at
    #: least one when refused: `Retry-After: 0` invites an immediate retry,
    #: which is the opposite of the point.
    retry_after_seconds: int


class SlidingWindowLimiter:
    """At most `limit` attempts per key in any `window_seconds` period.

    A sliding window rather than a fixed one. A fixed window resets on a clock
    boundary, so an attacker who waits for it can spend a full allowance at
    23:59:59 and another at 00:00:00 — twice the intended rate at exactly the
    moment a rate limit is being tested. A sliding window has no boundary to
    stand on.

    The cost is that each key holds its own timestamps rather than one counter.
    With a limit in the tens, that is a few dozen floats per key.
    """

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        if limit < 1:
            raise ValueError("A limit below one would refuse every attempt.")
        if window_seconds <= 0:
            raise ValueError("A window must have a length.")

        self._limit = limit
        self._window = float(window_seconds)
        self._capacity = capacity
        #: Ordered by how recently each key was touched, so eviction can drop
        #: the least recent without scanning.
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()

    # ─── Asking ───────────────────────────────────────────────────────────

    def check(self, key: str, now: float) -> Decision:
        """Whether an attempt would be allowed, without recording one.

        Separate from `record` because the two happen at different moments: the
        request is refused *before* the password is checked, and the attempt is
        only counted once it is known to have failed.
        """
        recent = self._recent(key, now)
        return self._decide(recent, now)

    def record(self, key: str, now: float) -> Decision:
        """Count one attempt against a key, and say where that leaves it.

        The decision returned describes the key *after* the attempt — that is,
        what `check` would say next — so `allowed=False` means the next attempt
        will be refused, not that this one was. Gating is `check`'s job, and it
        happens before the work rather than after it.

        Neutral about *what* is being counted, because the two callers count
        opposite things: signing in counts failures, since a correct password
        is not a guess, while registering counts successes, since the thing
        worth limiting there is accounts actually being created.
        """
        recent = self._recent(key, now)
        recent.append(now)
        self._attempts[key] = recent
        self._attempts.move_to_end(key)
        self._evict_if_full()

        decision = self._decide(recent, now)
        if not decision.allowed:
            logger.warning(
                "Rate limit reached for %s: %s attempts within %ss",
                key,
                len(recent),
                int(self._window),
            )
        return decision

    def clear(self, key: str) -> None:
        """Forget a key's history, after an attempt that was not a guess."""
        self._attempts.pop(key, None)

    # ─── Internals ────────────────────────────────────────────────────────

    def _recent(self, key: str, now: float) -> deque[float]:
        """This key's attempts still inside the window.

        Expired timestamps are dropped here rather than by a sweep, so the
        structure cleans itself on the only path that touches it.
        """
        recent = self._attempts.get(key)
        if recent is None:
            return deque()

        cutoff = now - self._window
        while recent and recent[0] <= cutoff:
            recent.popleft()

        if not recent:
            # An exhausted key is removed rather than left as an empty deque,
            # so a quiet period genuinely frees the memory it used.
            self._attempts.pop(key, None)
        return recent

    def _decide(self, recent: deque[float], now: float) -> Decision:
        if len(recent) < self._limit:
            return Decision(
                allowed=True,
                remaining=self._limit - len(recent),
                retry_after_seconds=0,
            )

        # The window frees up when its oldest attempt falls out of it.
        wait = self._window - (now - recent[0])
        return Decision(
            allowed=False,
            remaining=0,
            retry_after_seconds=max(1, int(wait) + 1),
        )

    def _evict_if_full(self) -> None:
        while len(self._attempts) > self._capacity:
            self._attempts.popitem(last=False)


__all__ = ["DEFAULT_CAPACITY", "Decision", "SlidingWindowLimiter"]
