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
