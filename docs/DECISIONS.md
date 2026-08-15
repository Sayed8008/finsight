# Architecture Decision Log

A running record of significant technical decisions, why they were made, and
what was rejected. Each entry is short on purpose.

Format: **what we decided**, **why**, **what we rejected**.

---

## ADR-001 — Layered architecture with HTTP between GUI and backend
**Date:** 2026-08-15 · **Status:** Accepted

The PySide6 client talks to a FastAPI backend over HTTP; only the backend
touches MySQL.

**Why:** Layered separation is a stated learning objective of the course. The
network boundary makes it structurally impossible to leak business logic into
widget code. It also means a future web or mobile client is a client, not a
rewrite.

**Rejected:** Embedding SQLAlchemy directly in the desktop app (as GnuCash and
similar products do). This is genuinely simpler and avoids requiring the user to
run a server — but it eliminates the architectural separation being assessed.

**Known cost:** The user must run both a backend process and MySQL. Mitigated by
a launcher script that starts both.

---

## ADR-002 — Synchronous SQLAlchemy and `def` route handlers
**Date:** 2026-08-15 · **Status:** Accepted

Route handlers are plain `def`, not `async def`. SQLAlchemy is used in
synchronous mode.

**Why:** PyMySQL is a synchronous driver; async SQLAlchemy would require
`aiomysql` or `asyncmy` instead. FastAPI runs `def` handlers in a threadpool, so
nothing blocks. Async concurrency benefits high-simultaneous-request workloads;
this application has one user. Async would add cost (event-loop blocking bugs,
greenlet errors, async fixtures) with no corresponding benefit.

**Rejected:** `asyncmy` + async SQLAlchemy.

---

## ADR-003 — Money as DECIMAL / Decimal / JSON string
**Date:** 2026-08-15 · **Status:** Accepted

| Layer | Representation |
|---|---|
| MySQL | `DECIMAL(14,2)` |
| SQLAlchemy | `Numeric(14, 2)` |
| Python | `decimal.Decimal` — never `float` |
| JSON | **string** (`"650.00"`) |

**Why:** Binary floating point cannot represent decimal fractions exactly, which
produces drift in accumulated sums. JSON has no decimal type — a JSON number is
an IEEE double, so serialising as a number reintroduces the exact problem the
`Decimal` storage was chosen to avoid. Strings survive the wire intact.

Rounding, percentage, and division-by-zero rules live in a single module
(`core/money.py`) rather than being reimplemented per call site.

---

## ADR-004 — Argon2id for password hashing
**Date:** 2026-08-15 · **Status:** Accepted

Use `argon2-cffi` directly.

**Why:** Argon2id is OWASP's current first-choice password hashing
recommendation. It has no input-length truncation.

**Rejected:** `passlib[bcrypt]`, the common tutorial default. `passlib` is
effectively unmaintained and currently errors on version detection against
modern `bcrypt` releases. bcrypt also silently truncates passwords at 72 bytes.

---

## ADR-005 — Tests run against MySQL, not SQLite
**Date:** 2026-08-15 · **Status:** Accepted

A dedicated `finsight_test` MySQL database; each test runs in a transaction that
is rolled back.

**Why:** The analytics layer depends on date functions and `GROUP BY` semantics
that differ between SQLite and MySQL. Testing on SQLite would produce passing
tests against code that fails in production. Correctness over test speed.

---

## ADR-006 — Per-user categories, seeded at registration
**Date:** 2026-08-15 · **Status:** Accepted

Every user owns a private copy of the default category set, created when their
account is created. There are no global/shared category rows.

**Why:** It establishes one invariant — *every row in every domain table has a
`user_id`* — which makes the "users may only access their own data" requirement
enforceable by a single shared dependency instead of per-endpoint vigilance.
Shared categories would require `WHERE user_id = ? OR user_id IS NULL` on every
query, and renaming a shared category would affect other users.

**Cost:** ~20 duplicated rows per account. Negligible.

---

## ADR-007 — Subscription auto-detection is a first-class feature
**Date:** 2026-08-15 · **Status:** Accepted

Recurrence detection over existing transaction history is promoted from a single
insight rule to its own phase, with a dedicated endpoint
(`POST /subscriptions/detect`).

**Why:** It is the only component of the project that is a genuine algorithm
rather than CRUD plus arithmetic — description normalisation, amount clustering
with tolerance, interval-regularity scoring, and confidence explanation. It
addresses a real problem (forgotten subscriptions) and is the strongest
demonstration material.

**Constraint:** Detection never creates a subscription silently. It returns
candidates with evidence and a confidence score; the user confirms or ignores.

**Known limitation:** Detection quality is bounded by the quality of the CSV
description column. Opaque descriptors (`POS PURCHASE 4021`) are unmatchable.

---

## ADR-008 — In-app reminders are a view over the insights engine
**Date:** 2026-08-15 · **Status:** Accepted

There is no separate notifications subsystem. "Renewal in 2 days" and "budget
exceeded" are insight rules already; reminders are a rendering of high-severity
insights.

**Why:** Avoids a parallel subsystem duplicating rule logic. Desktop
notifications can later be added as a second renderer of the same data.

---

## ADR-009 — PyJWT for access tokens
**Date:** 2026-08-15 · **Status:** Accepted

**Why:** `python-jose`, the other common choice, is effectively unmaintained.
PyJWT is actively maintained and is what FastAPI's own documentation uses.

**Rejected:** `python-jose[cryptography]`.

---

## ADR-010 — httpx2 as the single HTTP client
**Date:** 2026-08-15 · **Status:** Accepted

The desktop client uses `httpx2`, which also backs Starlette's `TestClient`.

**Why:** Starlette 1.6 deprecated httpx v1 inside its `TestClient` and emits a
warning telling you to install `httpx2`. Using httpx2 for the desktop client as
well means one HTTP library in the project rather than two.

**Verified:** `httpx2.Client`, `ConnectError`, `TimeoutException` and
`HTTPStatusError` all exist with the same names, so no adaptation was needed.

---

## ADR-011 — The desktop package is `client`, not `app`
**Date:** 2026-08-15 · **Status:** Accepted

Backend code lives in `backend/app/`; desktop code lives in `frontend/client/`.

**Why:** The original plan had both named `app`. Since pytest puts both
`backend/` and `frontend/` on the import path, two packages named `app` would
shadow each other and produce import errors that are tedious to diagnose.
Distinct names cost nothing.

---

## ADR-012 — Layout bugs are found by rendering, not by reading
**Date:** 2026-08-15 · **Status:** Accepted

Qt views are screenshotted offscreen (`QT_QPA_PLATFORM=offscreen` plus
`QWidget.grab()`) and inspected during development.

**Why:** The first render of the main window revealed two defects invisible in
the source: `QListWidget` in a stretched layout silently clipped its last item
("Settings"), and Qt stylesheets ignore `max-width`, so the placeholder text
wrapped to the width of its title. Both now have regression tests.

---

## ADR-013 — The database URL is never written in `alembic.ini`
**Date:** 2026-08-15 · **Status:** Accepted

`alembic/env.py` reads the connection URL from application settings, or from
`-x db_url=...` on the command line.

**Why:** `alembic.ini` is tracked by git and the connection URL contains the
database password. Alembic's generated default puts the URL straight into the
ini file, which would publish the credential in a public repository.

---

## ADR-014 — Test schemas are built by running migrations
**Date:** 2026-08-15 · **Status:** Accepted

The test database is created by `alembic upgrade head`, not
`Base.metadata.create_all`. A further test asserts that autogenerate finds no
difference between the models and the migrated schema.

**Why:** `create_all` builds tables from the models, so it would pass happily
while the migrations were broken or missing — exactly the failure that only
appears on a fresh database. Running the real migrations exercises them on
every test run, and the drift check catches a model changed without a
corresponding migration.

**Cost:** Slightly slower session startup. Worth it.

---

## ADR-015 — Derived financial values are computed, never stored
**Date:** 2026-08-15 · **Status:** Accepted

Budget spent/remaining/percentage/status, and subscription monthly/yearly
equivalents, are calculated on read. No column stores them.

**Why:** A stored total is a cache, and it goes stale the instant a
transaction is added, edited, deleted, or recategorised. Keeping it correct
would mean invalidation logic on every write path. Recomputing from an indexed
aggregate query is fast at this data size and cannot be wrong.

**Revisit if:** aggregate queries become measurably slow — measure first.

---

---

## ADR-016 — Access tokens are held in memory only
**Date:** 2026-08-15 · **Status:** Accepted

The desktop client keeps the access token in memory. Closing the application
means signing in again. Nothing is written to disk.

**Why:** A token stored in a plain file is readable by anything running as the
user. Doing it properly means the OS keyring (Windows Credential Manager,
Linux Secret Service) plus a fallback for headless sessions — real work for a
convenience feature.

**Deferred, not rejected:** a "stay signed in" option would store a *refresh*
token in the keyring, not the access token.

---

## ADR-017 — Logout is client-side; tokens are not revocable
**Date:** 2026-08-15 · **Status:** Accepted

`POST /auth/logout` exists, requires authentication and logs the event, but
cannot invalidate an already-issued token.

**Why:** JWTs are stateless by design — the server holds no session to end.
Genuine revocation needs a denylist of issued tokens checked on every request,
which reintroduces the per-request lookup that stateless tokens exist to
avoid. Short token lifetimes (60 minutes) are the mitigation instead.

**Honest limitation, worth stating in the report:** a stolen token remains
valid until it expires.

---

## ADR-018 — Login failures are deliberately indistinguishable
**Date:** 2026-08-15 · **Status:** Accepted

An unknown email and a wrong password return the same status, the same
message, and take comparable time. When no account exists, the service still
performs a hash verification against a dummy hash before failing.

**Why:** Differing responses turn a login form into a way of testing which
email addresses hold accounts. Matching the *message* is easy; matching the
*timing* is the part usually missed, because Argon2 verification takes long
enough to be measurable over a network.

**Tested:** `test_unknown_email_and_wrong_password_give_identical_responses`.

---

## ADR-019 — Client-side validation is for feedback, never enforcement
**Date:** 2026-08-15 · **Status:** Accepted

The desktop client checks for empty fields and short passwords before calling
the API. Every one of those rules is also enforced server-side.

**Why:** The client check exists so the user hears about a mistake instantly
instead of after a round trip. It is not a security measure — anyone can call
the API directly, so the server is the only authority. Validating in one place
only would mean either a sluggish interface or an unprotected API.

---

## ADR-020 — Categories have no DELETE endpoint
**Date:** 2026-08-15 · **Status:** Accepted

A category is retired with `PATCH /categories/{id} {"is_active": false}`.
There is no `DELETE /categories/{id}`.

**Why:** The foreign key from `transactions.category_id` is `ON DELETE
RESTRICT`, so the database would refuse to delete any category that had ever
been used. An endpoint that works only for unused categories and answers 409
for the rest is a worse interface than not offering one: the caller has to
handle deactivation as a fallback anyway, so deactivation may as well be the
only path.

`category_type` is immutable for a related reason — flipping an expense
category to income would silently invalidate every transaction filed under it.
Changing a type means creating a category and moving the transactions across,
which is a deliberate act rather than a field edit.

**Rejected:** a `DELETE` that soft-deletes. A verb that says "delete" while
setting a flag reads fine and surprises everyone later.

**Consequence:** the list endpoint hides deactivated categories unless asked
(`include_inactive=true`), so the form pickers that call it cannot offer a
retired category for a new transaction.

---

## ADR-021 — Filtering, sorting and pagination happen in SQL
**Date:** 2026-08-15 · **Status:** Accepted

Transaction filters compose into one `WHERE` clause, with `ORDER BY` and
`LIMIT`/`OFFSET`. The endpoint returns a page envelope — `items`, `total`,
`page`, `page_size`, `pages` — and takes the sort column and direction as
parameters. Filters are carried by one frozen `TransactionFilters` value
object rather than a growing list of keyword arguments.

**Why:** Fetching a user's rows and sifting them in Python gets slower in
exact proportion to the history it is meant to search. It also makes `total`
a lie, and sorting wrong: a client can only order the page it was handed, so
"sort by amount" would sort 25 rows out of four thousand.

`total` costs a second `COUNT(*)` over the same clauses. Both queries are
built by one private method so they cannot drift apart — a count computed
from different criteria than the page it describes gives a pager that
disagrees with its own table.

**Rejected:** cursor pagination. It is the better design for an infinite feed,
but it cannot express "jump to page 7", which is what a table with a pager
needs.

**Two details that are easy to get wrong, and now have tests:**

- **`ORDER BY` needs a unique tie-breaker.** Rows sharing a sort value — several
  transactions on one date, the common case — have no defined order between
  them, so MySQL may return them differently per query. A row then appears on
  both page 1 and page 2 while another is never shown. Every sort ends in
  `id DESC`.
- **`LIKE` patterns need escaping.** `%` and `_` are wildcards, so an
  unescaped search for `50%` matches every description, and `snacks_x` matches
  `snacksXx`. SQLAlchemy's `contains(..., autoescape=True)` handles it.

**Also worth knowing:** the category is loaded by the same join that makes
sorting by category name possible (`contains_eager`), so a page of rows costs
two queries regardless of its size. A test counts the statements, because an
N+1 problem is invisible in a functional test — the rows are correct, there
are just N more round trips than there should be.

---

## ADR-022 — Qt stylesheet specificity: never style widgets by descendant type
**Date:** 2026-08-15 · **Status:** Accepted

Containers that need a transparent background are given an object name and
styled by id (`#FormRow`). Rules of the form `#SomeParent QWidget { ... }` are
not used.

**Why:** Qt stylesheets follow CSS specificity. `#TransactionDialog QWidget`
(one id, one type) is *more* specific than `#PrimaryButton` (one id), so it
wins. Since a `QPushButton` is a `QWidget`, a rule intended to make label
backgrounds transparent inside a dialog also set the primary button's
background to transparent — and the button was then drawn in white text on a
white dialog. It was laid out, sized, enabled, visible and clickable
throughout; only invisible.

**Found by:** rendering the dialog and looking at it, which is the practice
ADR-012 exists for. Every non-visual check passed — `isVisible()` was true and
`geometry()` was correct.

**Tested by:** grabbing the button and sampling a background pixel. A
regression test that asserts geometry or visibility would not have caught this
and would not catch it again; only the pixels distinguish "painted" from
"painted in nothing".

**Corollary:** the same trap applies to `alternate-background-color`, borders
and padding. If a rule needs to reach a group of widgets, the group gets a
shared object name.

**It happened again in Phase 5,** while writing `#BudgetCard QWidget` for the
same reason as before. Caught by the ADR rather than by the pixels this time,
which is what the ADR is for.

---

## ADR-023 — Budgets: expense categories only, and no overlapping periods
**Date:** 2026-08-15 · **Status:** Accepted

A budget can only be set on an **expense** category, and two budgets for the
same category may not **overlap in time**.

**Why (expense only):** every figure a budget produces — spent, remaining,
percentage — is a sum of expenses. "Spend no more than X on Salary" is not a
sentence anyone means, and allowing it would put a permanently 0%-used card on
the screen with no way to act on it.

**Why (no overlap):** the question a budget exists to answer is "how much is
left for Food?". With two budgets both covering today, that question has two
answers, and every consumer — the card list, the dashboard, the insight rules
in Phase 9 — would have to pick one arbitrarily. Better to refuse at the point
of creation, where the user can see both periods, than to disambiguate forever
afterwards.

**What the schema could not do:** the unique constraint is on
`(user_id, category_id, period_start, period_end)`, so it only catches an
*exactly repeated* period. 1–31 March and 10–20 March pass it happily. The rule
therefore lives in the service, expressed as `start <= other_end AND end >=
other_start` — stated explicitly because the intuitive version, comparing start
to start, misses a period sitting entirely inside another. Both that case and
its mirror have tests.

**Rejected:** allowing overlap and summing, or preferring the shortest period.
Both are rules the user cannot see and would have to be told about.

**Accepted cost:** a weekly and a monthly budget on the same category cannot
coexist. Revisit if anyone actually wants that — it would mean deciding which
one the dashboard reports.

---

## ADR-024 — Styling a Qt widget means styling its sub-controls too
**Date:** 2026-08-15 · **Status:** Accepted

If a stylesheet rule matches a composite widget, that widget's sub-controls
(`::indicator`, `::chunk`, `::drop-down`, `::handle`) must be styled as well.

**Why:** Qt switches a widget to stylesheet rendering as soon as *any* rule
matches it, and then draws only what the sheet describes. A `QCheckBox` given
nothing but `color` and `background-color` renders as a label with **no box** —
still clickable, still checkable, still reporting `isVisible()` as true, and
completely invisible. The same applies to a `QProgressBar` without `::chunk`,
which is why the budget bars style theirs.

**Found by:** rendering the budgets screen and looking at it — the checkbox in
the filter bar was a floating line of text.

**Tested by:** grabbing the checkbox and asserting the border colour appears in
the indicator area unchecked, and the primary blue appears checked. As with
ADR-022, no test of geometry or visibility would catch this.

**Related:** ADR-012 (layout bugs are found by rendering) and ADR-022 (Qt
stylesheet specificity). Three separate faults now, all invisible in the source
and all obvious in a screenshot.

**It happened a third time, in Phase 11, and had been on screen since Phase 4.**
`#FieldSelect` styles the box and `::drop-down` styles the area the arrow sits
in — but nothing styled `::down-arrow`, so Qt drew none. Every combo box and
every date field in the application looked like a read-only text box, on every
filter bar, for seven phases. Found by rendering the new category dialog and
noticing that its "Kind" field did not look like a chooser.

The fix is worth recording too, because the obvious one does not work: a
zero-sized element with transparent side borders and one solid edge is a
*browser* CSS triangle, and Qt clamps the sub-control and draws a small
rectangle instead. It was tried, rendered, and looked worse than nothing. The
arrow is an SVG, and because a stylesheet `url(...)` resolves against the
working directory, the sheet carries a `%RESOURCES%` token that `load_stylesheet`
substitutes. Tests now load the sheet through that function rather than reading
the file, so what they render is what the application renders — a missing image
in Qt fails silently, and reading the raw file would have hidden exactly this
class of defect from the tests written to catch it.

---

## ADR-025 — Billing dates are anchored, and `next_billing_date` is derived
**Date:** 2026-08-15 · **Status:** Accepted

Every subscription occurrence is computed as `start_date + n cycles` from the
original anchor, never by adding one cycle to the previous date. Clients never
supply `next_billing_date`.

**Why (anchoring):** month-end clamping is correct in isolation and wrong when
applied repeatedly. Adding a month to 31 January must give 28 February, since
31 February does not exist — but adding a month to *that* gives 28 March, and a
subscription that bills on the last day has silently moved to the 28th for
good. Anchoring gives 31 Jan → 28 Feb → 31 Mar → 30 Apr → 31 May: clamped where
it must be, restored where it can be, which is what a real biller does.

**Why (derived, not supplied):** accepting a next billing date alongside a start
date and a cycle allows all three to disagree, and nothing can then say which
was meant. It is recomputed when the anchor or the cycle changes, and advanced
by `POST /subscriptions/{id}/renew`.

**Consequence:** renewing past a subscription's own end date cancels it rather
than scheduling a charge that will never happen.

**Also decided here:** a weekly cost converts at 52 charges a year, never four
a month. The two differ by about 8% — invisible on one row, material in a
total — so one table holds the conversions and a test asserts that monthly × 12
stays within rounding of yearly, since the interface shows both together.

**Rejected:** storing the schedule as a list of future dates. It would need
regenerating on every edit and would go stale exactly like a cached total
(ADR-015).

---

## ADR-026 — Chart colour is measured, and category hues are not a chart palette
**Date:** 2026-08-15 · **Status:** Accepted

The default category colours were re-picked by running them through a
colour-vision and contrast validator, and charts do **not** colour series by
category.

**What the measurement found.** `default_categories.py` claimed its colours were
"chosen to stay distinguishable when used as chart series". Validated, the
original set failed three checks:

| Check | Result |
|---|---|
| Chroma floor | `#4a5259`, `#7a6a4f`, `#8b939c` read as grey |
| Colour-vision separation | `#8a4fbd` ↔ `#1a56c4` ΔE **2.2** under protanopia — the same colour |
| Normal-vision floor | `#d9782e` ↔ `#c4472f` ΔE **11.8**, below the floor of 15 |

The claim was written from eyeballing, and eyeballing cannot answer this. The
replacements pass all five checks as an adjacent-pair sequence, which is the
right test because a category colour always appears as a swatch beside its own
name.

**Why charts do not use them.** Measured again with all pairs compared rather
than only adjacent ones, **nine categorical hues cannot be made safe** — the
best nine-colour set still collapses somewhere (`#4d8b1f` ↔ `#d9782e` at ΔE 1.8
under protanopia). That is a property of the colour space, not of the choices.
So the spending chart uses **one hue** and encodes magnitude by bar length,
with identity carried by the axis labels.

**Why a ranked bar and not a donut.** The reader's job is to compare magnitudes
and find the largest. Lengths against a shared baseline are easy to compare;
angles are not, least of all for the close values that matter most. A pie earns
its place only for part-to-whole at a glance with few segments. The percentage
is printed beside each bar so the part-to-whole reading is not lost.

**Consequence:** existing accounts keep the colours seeded when they registered
— the column is per-user and editable. Only new accounts get the validated set.

**Corollary:** past six categories the tail is folded into one "Other
categories" row, computed server-side so the shares still sum to 100.

---

## ADR-027 — Chart series use a measured colour pair, not the app's green/red
**Date:** 2026-08-15 · **Status:** Accepted

Income and expense are shown **green and red wherever an amount carries a
sign**, and **blue and orange in the trend chart**.

**Why the inconsistency is deliberate.** In a table or a list, the sign does the
work: `+8,000.00` and `−250.00` are unambiguous before colour is considered, and
green/red only reinforces what the character already said. In the trend chart
there is no sign — both series are positive bar heights — so colour is the
*only* thing separating them.

Measured, `#1a7f4b` and `#b4232c` are **ΔE 4.5** apart under deuteranopia: the
same colour to roughly one man in twelve. Blue `#1a56c4` and orange `#d9782e`
are **ΔE 29.7** apart under the same simulation and pass every other check too.
The chart uses those, with a legend naming both.

**Rejected:** keeping green/red and adding a pattern fill. Secondary encoding
rescues a pair in the ΔE 6–8 band; 4.5 is below even that, and a chart nobody
can read without the texture is not fixed by the texture.

**Also here:** grouped bars rather than stacked. Stacking income onto expense
would imply the two add up to something — they do not, and the quantity worth
seeing is the gap between them.

---

## ADR-028 — Independent requests track failure independently
**Date:** 2026-08-15 · **Status:** Accepted

A screen that makes more than one request records which of them are failing,
rather than keeping a single "something went wrong" flag.

**Why:** the analytics screen fetches a trend and a comparison separately, and
with one flag the second succeeding cleared the banner the first had set. A
failed request vanished with nothing on screen to say it had happened.

**Found by:** a test asserting the error was visible after a load in which one
request failed and the other did not.

**How:** failures are held in a dict keyed by request name; the banner shows
whatever is still failing, deduplicated so two requests failing because the
backend is down say it once.

**Applies to:** any future screen making more than one call. The dashboard is
unaffected, since it makes exactly one by design.

**Corollary, added in Phase 11: an empty state is not a failure state.** The
banner is not the only thing on screen. Auditing the empty states found the
analytics trend chart saying "No activity in this span" and its comparison
panel saying "Nothing to compare yet" when *both requests had failed* — two
confident claims about the account, in the middle of the screen, where the user
is actually looking. "You have no data" and "we could not fetch your data" call
for different acts, so each panel now has separate wording and a test that the
failure text does not leak into the ordinary empty state or survive a
recovery.

---

## ADR-029 — Insight rules are pure functions over a snapshot
**Date:** 2026-08-15 · **Status:** Accepted

Each rule is a function from an `InsightSnapshot` to zero or more insights. No
rule touches a session, a clock, or an HTTP request; the snapshot carries
everything, including what day it is. One service gathers it, once.

**Why:** three things follow that do not otherwise.

1. **Every rule is testable in three lines.** Build the fields it reads, call
   it, assert. Forty-six unit tests cover every threshold and boundary without
   a database between them.
2. **The cost of the screen is fixed.** Queries all happen in one place, so
   "how expensive is the insights page" has an answer that does not depend on
   which rules happen to fire. A rule that queried would make that
   unanswerable — and would have made the query-count test meaningless.
3. **Adding a rule cannot break the others.** It is a function appended to a
   list.

**The rule that has to hold for all of them:** *every insight explains itself*.
Each states the figure it found and what it was compared against. "Unusual
spending detected" is a shrug with a badge. There is a test asserting that
every insight any rule produces contains a digit and more than twenty
characters of explanation — it applies to rules not yet written.

**Consequence:** a rule needing data the snapshot lacks adds a field to the
snapshot. It does not reach for a session.

---

## ADR-030 — The dashboard renders insights; it does not judge
**Date:** 2026-08-15 · **Status:** Accepted

The dashboard's attention bar shows the top insight from the same endpoint the
insights screen uses. It no longer works out its own line from budget counts
and the next renewal.

**Why:** ADR-008 said reminders would be a view over the insights engine rather
than a parallel subsystem. Phase 7 shipped an attention bar before that engine
existed, which left two places deciding what deserves attention — free to
disagree the moment either threshold moved. Now there is one.

**Consequence:** the dashboard payload carries `insights` and
`needs_attention`. A test asserts the codes it returns are identical to the
insights endpoint's, so the two cannot drift.

**Found while doing it:** the insights endpoint was gathering its snapshot
twice — once for the findings and once for the period they describe — which
doubled every query behind the screen. Caught by a query-counting test, not by
reading the code.

---

## ADR-031 — Detection matches merchants conservatively, and says when it cannot
**Date:** 2026-08-15 · **Status:** Accepted

Descriptions are normalised by stripping punctuation, any token containing a
digit, and a short list of payment-processor words. Two charges group together
only when the result matches **exactly**.

**Why exact rather than fuzzy:** the tempting next step is prefix or
similarity matching, so "NETFLIX AMSTERDAM" joins "NETFLIX". It would also join
"GOOGLE DRIVE" to "GOOGLE PLAY". A missed subscription costs the user nothing —
they carry on as they were. A merged pair produces a confident, wrong proposal
about their money. The asymmetry decides it.

**The noise list is short on purpose.** Every word in it is one that can no
longer distinguish two merchants, so a longer list buys recall at the cost of
exactly the failure above.

**When there is no merchant, it says so.** `POS PURCHASE 4021` normalises to
nothing and is skipped, which ADR-007 already recorded as the honest limitation.
Guessing from it would be inventing rather than detecting.

**Rejected:** scoring candidates by string similarity. It would need a
threshold nobody could justify, and the failure it introduces is silent.

---

## ADR-032 — Confidence is evidence, not a percentage
**Date:** 2026-08-15 · **Status:** Accepted

A candidate carries three levels — high, medium, low — and a sentence:
"5 charges of 499.00, exactly 30 days apart."

**Why not a number:** "87% confident" implies a precision the method does not
have, invites sorting by a figure nobody can check, and cannot be verified
against anything. The sentence can: the user reads it, glances at their
transactions, and knows. The evidence *is* the confidence, and the level is
derived from the measurements rather than the other way round.

The level needs all three of enough charges, steady intervals and steady
amounts to reach *high* — any one of them weak drops it.

**Consequence:** the interface never displays a raw severity or a raw score. It
shows the sentence and a word.

**Related:** the same reasoning as ADR-029, where insights must name the
figures they were built from. Both come from the same rule — a finance
application that cannot say *why* it said something is worse than one that says
nothing.

---

## ADR-033 — Import is preview then commit, and the commit is fingerprinted
**Date:** 2026-08-15 · **Status:** Accepted

Importing a CSV is two requests. `POST /csv/preview` reads the file, resolves
every category, finds every duplicate and reports everything an import would do,
writing nothing. `POST /csv/import` does it again and only then writes — and it
will not run without the `digest` the preview returned.

**Why two requests.** A single endpoint has to decide by itself what to do about
an unreadable row or a category name the account does not have, and every one of
those decisions is one the user should be shown before it is made. Import is the
only place in this application where a single click can put thousands of wrong
rows into somebody's financial history.

**Why a fingerprint rather than a stored preview.** The obvious alternative is to
keep the parsed batch server-side and let the commit refer to it by id. That is a
piece of state with a lifetime, an eviction policy, and a window in which it
stops describing the file. The digest is `sha256(file bytes + options)`: it has
none of those, it survives a restart, and re-planning costs the same handful of
queries the preview did.

It covers the **options** as well as the bytes, which is the part that earns it.
Without that, a file previewed as day-first could be imported as month-first, and
every date would land a different day from the one the user was shown — a defect
with no symptom until months later.

**All or nothing.** The write is one transaction that rolls back whole, including
any categories created on the way. A file that half imports is worse than one
that does not import at all, because nobody can tell which half landed. Tested by
failing partway through and asserting that no row and no category survives.

**The defaults refuse.** An unknown category stops the import; an unreadable row
stops the import; a row already recorded is left out. The permissive versions —
create the categories, import the readable rows, keep the duplicates — all exist,
and the interface can only offer them *after* the preview has named exactly what
they would do. That is the difference between a choice and a shrug.

**Rejected:** a "dry run" flag on one endpoint. It is the same two calls with the
safety made optional, and the version without the flag is the one that gets
called.

**Nothing per row that can be done once.** Categories are one query, duplicate
detection is one query over the file's own date range, and the rows go in through
a Core `insert()` in chunks of 500 rather than as ORM objects — the ORM would
round-trip each row to fetch an id nothing wants. A test imports 10 rows and then
200 and asserts the statement count barely moves; an N+1 import is functionally
perfect and unusable, and only counting catches it.

---

## ADR-034 — The CSV reader asks rather than guesses
**Date:** 2026-08-15 · **Status:** Accepted

`transaction_csv.py` is pure — text in, values out, no session and no clock, the
same shape as `budget_utilisation`, `billing_cycle`, `insight_rules` and
`recurrence`. Reading a spreadsheet is not parsing a data format; it is guessing,
and the rule here is to guess as little as possible and be loud about the rest.

**Dates are stated.** `03/04/2026` is the third of April in Dhaka and the fourth
of March in Detroit, and nothing in the file says which. The caller supplies the
order and a value that does not fit is refused rather than reinterpreted.
Detection was rejected: it works only on files that happen to contain a day past
the twelfth, so it would succeed on most files and fail silently on exactly the
ones where every date is ambiguous.

Rows that *would* read as a different day the other way round are counted and
reported, so the preview can say "14 of these read differently the other way"
rather than presenting one reading as a fact.

**Direction is never assumed.** A row says which way money moved, through a type
column or through the sign of its amount. A bare `500.00` with neither is
refused; so is a row marked income carrying a negative amount, because something
is wrong with the file and either reading writes a figure the file does not
support. "Probably an expense" is a guess about somebody's finances.

**Amounts are parsed deliberately.** `1,234.56`, `1.234,56`, `(50.00)`, `৳1 234`,
`50.00-`, a Unicode minus and an en dash all mean something definite and are all
read. A third decimal place does not: money here has two places, so `12.3456` is
refused rather than rounded into disagreeing with the statement it came from.

**The one place it does decide, stated rather than left to a branch:** a lone
separator followed by exactly three digits is a thousands separator, so `1,234`
and `1.234` are both 1234. The alternative reading gives a number with three
decimal places, which is not money.

**Consequence:** a raw bank statement with no category column cannot be imported
as it stands, since `transactions.category_id` is NOT NULL and there is no
"uncategorised" row to hide behind (ADR-006). Rather than invent one, the import
takes an optional fallback category, which the preview names.

---

## ADR-035 — An export is data first, and cannot be a payload
**Date:** 2026-08-15 · **Status:** Accepted

`GET /csv/transactions` writes ISO dates, plain decimal amounts with no
thousands separator and no currency symbol, and a byte-order mark.

**Why plain.** The file is data before it is a report. Formatting an amount means
the reader has to undo the formatting to get a number back, and ISO is the one
date order that cannot be read two ways. Both choices are what make the export
readable straight back in — there is a test that exports one account and imports
it into another with no option changed, which is the only check that covers both
halves at once.

**Why the byte-order mark.** Without one, Excel opens a UTF-8 file as the
machine's local codepage, which turns "৳" and "Müller" into rubble. The reader
strips a BOM whether or not we wrote it, because a file that has been through
Excel has one either way.

**Formula injection.** A description of `=HYPERLINK(...)` is text in this
application and a formula the moment the export is opened in a spreadsheet. Free
text is written with a leading apostrophe when it starts `=`, `+`, `-` or `@`,
which Excel eats. The reader removes that apostrophe again only when it stands in
front of a formula character, so a description that genuinely begins `'twas`
keeps its quote and a defused one round-trips unchanged.

**Not paginated.** An export is the whole matching set by definition; a page of
one is a quietly truncated file that looks complete. It reuses the list's filter
clauses so that "export what I am looking at" cannot come to mean something else,
and takes a `MAX_EXPORT_ROWS` ceiling so one request cannot be asked to build an
unbounded string.

**Where the routes live.** Under their own `/csv` prefix rather than on the
transactions router: `/transactions/{transaction_id}` is declared there, and a
later `/transactions/export` would be handed to that `int` path parameter and
rejected before reaching its own handler. A separate prefix removes the trap
instead of documenting it.

---

## ADR-036 — Sign-in is throttled per address, and only failures count
**Date:** 2026-08-15 · **Status:** Accepted

`POST /auth/login` refuses after ten failed attempts from one client address
within five minutes, and answers 429 with `Retry-After`. `POST /auth/register`
is throttled the same way at five per hour. The limiter is a sliding window
over in-process memory.

**Why at all.** Without a limit, a login form is an offline password guesser
with a network in front of it. Argon2 (ADR-004) makes each guess expensive,
which narrows the gap and does not close it: a few guesses a second, for a week,
is a lot of guesses. This was on the known-limitations list from Phase 3 and was
the only entry there that is a security gap rather than a scope decision.

**Why per address and not per email.** Counting per email is the obvious design
and it is a weapon: anyone who knows an address can fail ten logins against it
and lock its owner out of their own account. The protection becomes the attack.
Per address, an attacker can only throttle themselves.

**Why only failures count, and a success clears the record.** The thing worth
limiting is guessing, and a correct password is not a guess. Otherwise two
typos this morning would still count against somebody this afternoon.

**Why it is checked before the password.** A refused request then costs an
Argon2 verification less — which is not only about load. Verification takes long
enough to be measurable, so a throttle applied afterwards would still let an
attacker time the response and learn from it.

**Why the response says nothing useful.** The message and status are identical
whether or not the account exists, and never say how many attempts remain. A
count would be a progress bar; a throttle that only fired for real accounts
would answer "does this email exist?" — the question ADR-018 exists to refuse.

**Why the clock is a parameter.** `SlidingWindowLimiter` takes `now` rather than
reading it, which is what lets every threshold and boundary be tested in a
millisecond without `sleep`. The routes pass `monotonic()` rather than
wall-clock time, so an NTP step or a daylight-saving change cannot hand out a
fresh allowance or lock somebody out for an hour.

**Why a sliding window rather than a fixed one.** A fixed window resets on a
boundary, so an attacker who waits for it spends a full allowance either side
and gets twice the intended rate — at exactly the moment a rate limit is being
tested. A sliding window has no boundary to stand on. The cost is timestamps per
key instead of a counter, which at a limit of ten is a few dozen floats.

**Why the store is bounded.** A dictionary keyed by client address is one an
attacker chooses the keys of; left to grow it is a memory leak with a hostile
author. Ten thousand keys, least-recently-seen evicted, which errs in the safe
direction — an old, quiet attacker regains an allowance while whoever is active
stays limited.

**Honest limitation, worth stating in the report:** the store is in-process.
With more than one worker each keeps its own tally, so the effective limit
multiplies by the worker count, and a restart forgets everything. A shared store
is the fix and it is a dependency this application does not otherwise need. The
limiter is held on `app.state` rather than in a module global, so tests get a
fresh one per application and the swap would be one line.

---

## ADR-037 — Categories are retired in the open, and the change is announced
**Date:** 2026-08-15 · **Status:** Accepted

The Settings screen lists categories grouped by direction, with Add, Edit, and
Retire/Restore. Retired categories stay on the screen behind a "Show retired"
toggle, dimmed and badged. Changing any of them emits `categories_changed`,
which the shell turns into a refresh of every screen holding a category picker.

**Why the screen exists.** The category endpoints have been complete and tested
since Phase 4, reachable only with an HTTP client. The one thing a user is most
likely to want to change — what their spending is grouped into — was the one
thing the interface could not do.

**Why "Retire" and not "Delete".** There is no `DELETE /categories/{id}`
(ADR-020), and there cannot usefully be one: the foreign key is `ON DELETE
RESTRICT`, so any category ever used would refuse. The button therefore says
what actually happens, and the confirmation says what does *not* — the history
stays exactly where it is. A button labelled "Delete" that set a flag would read
fine and surprise everyone later, which is the same argument ADR-020 made about
the endpoint.

**Why retired categories stay visible.** They cannot be deleted, so a screen
that hid them would make restoring one impossible. They are dimmed *and*
badged: the dimming alone is colour carrying meaning by itself, which this
project does not do anywhere else either.

**Why the type chooser disappears when editing.** A category's type is
immutable, because flipping an expense category to income would silently
invalidate every transaction filed under it. The chooser is *gone* rather than
present and disabled — a greyed-out control invites "why can I not change this?"
and answers nothing, while a line of text states what the category is and moves
on.

**Why the signal.** Every screen offering a category picker fetches the list
once, when it is first opened, because the same fifteen names would otherwise be
requested for every row on screen. That is the right call and it has exactly one
consequence: a category created in Settings is invisible to those screens until
told. The alternative — refetching categories on every navigation — would undo
the reason they are cached at all. Only screens that have actually been opened
are refreshed, so the signal cannot make a request for a section nobody has
looked at.

**Colours are picked from a fixed set,** the measured one from ADR-026, rather
than typed as hex or chosen from a native colour wheel. A colour here always
appears as a small swatch beside its own name, and a free choice is a free
choice to pick two nobody can tell apart.

---

## ADR-038 — A blocking client says so before it blocks
**Date:** 2026-08-15 · **Status:** Accepted

Slow requests — import, export, subscription detection — are wrapped in
`working()`, which sets a wait cursor, puts a message in the screen's banner,
disables the controls that triggered it, and calls `processEvents()` **once**
before the call starts.

**Why the ordering is the whole thing.** Every request in this client is
synchronous. A blocked event loop paints nothing, so a message set immediately
before a blocking call appears only once the call has finished — saying
"Working…" at the exact moment the work is over. The single `processEvents()` is
what flushes that paint while the loop is still turning. Without it the code
looks correct and does nothing.

**Why the controls are disabled.** `processEvents()` delivers whatever is
queued, including a second click on the button that started this. Handing that
to the same handler would run two imports.

**Why not a worker thread.** That is the honest fix and it is a different piece
of work: every view would have to handle a reply arriving after the user had
moved on, and every screen would need a cancelled state. This phase is about
telling the truth, not about changing the architecture — the window is about to
freeze, here is why, and here is a cursor that says so.

**Restoration is in a `finally`,** because the interesting case is the request
that raises: a wait cursor left behind after a failure is a window that looks
permanently busy. Qt keeps a cursor *stack*, so an unbalanced restore would
leave it that way for the rest of the session; there is a test for nesting.

**Where it is applied, and where it is not.** Import, export and detection —
the three requests bounded by file size or by history rather than by page size,
and therefore the only three that can take long enough to look like a hang. The
paged list and the dashboard are single-digit milliseconds against localhost and
are left alone; a busy cursor that flickers for two frames is worse than none.
