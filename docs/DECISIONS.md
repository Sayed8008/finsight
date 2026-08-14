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
