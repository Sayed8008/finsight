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
