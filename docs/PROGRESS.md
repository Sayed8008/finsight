# Progress

Where the project stands, and what comes next. Updated at the end of each
phase.

**Last updated:** 2026-08-15 · **Current state:** Phase 3 complete

---

## Resuming work

Read these first, in order:

1. `docs/DECISIONS.md` — every architectural decision, with reasoning and
   rejected alternatives. Do not re-derive these.
2. `docs/DATABASE.md` — the schema.
3. This file — what is built and what is next.
4. `git log --oneline` — commit messages explain the *why* of each change.

Then verify the environment still works:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest    # expect 82 passed
.venv/bin/ruff check .                                  # expect clean
./scripts/dev.sh                                        # backend + client
```

---

## Phase status

| Phase | Content | Status |
|---|---|---|
| 0 | Repository, `.gitignore`, decision log, database setup script | ✅ done |
| 1 | Skeleton: venv, config, logging, `/health`, PySide6 shell, launchers | ✅ done |
| 2 | Database: 5 models, SQLAlchemy session layer, Alembic, first migration | ✅ done |
| 3 | Authentication: Argon2id, JWT, protected routes, login/register screens | ✅ done |
| 4 | Transactions and categories: CRUD, filtering, pagination, data table | ⬜ next |
| 5 | Budgets: model exists; utilisation calculations and UI | ⬜ |
| 6 | Subscriptions: model exists; cycle maths and UI | ⬜ |
| 7 | Dashboard: financial summary, QtCharts, recent activity | ⬜ |
| 8 | Analytics: aggregation endpoints, period comparison, charts | ⬜ |
| 9 | Insights: rule engine, severity, explanations | ⬜ |
| 9.5 | **Subscription auto-detection** from transaction history | ⬜ |
| 10 | CSV import (preview then commit) and export | ⬜ |
| 11 | Polish: error/empty/loading states, logging, theming | ⬜ |
| 12 | Packaging, README, screenshots, demo script | ⬜ |

Testing is not a phase. Tests are written within each phase, and every phase
ends with a green run.

---

## What exists now

**Backend** — FastAPI on `127.0.0.1:8000`, docs at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness; the client uses it to distinguish "down" from "errored" |
| `POST /api/v1/auth/register` | create account, seed 15 categories, return token |
| `POST /api/v1/auth/login` | exchange credentials for a token |
| `POST /api/v1/auth/logout` | authenticated no-op; see ADR-017 |
| `GET /api/v1/auth/me` | the signed-in user |

**Database** — MySQL 8.4, five tables, one migration applied. Schema in
`docs/DATABASE.md`.

**Desktop client** — PySide6. Login and registration screens, then a shell
with sidebar navigation. Five of six sections are placeholders.

**Tests** — 82 passing: security unit tests, model/constraint tests against
real MySQL, auth API tests, and GUI tests via pytest-qt.

---

## Next: Phase 4 — Transactions and categories

The largest phase so far. Suggested order, each step ending green:

1. **Category endpoints** — list, create, rename, deactivate. Smaller than
   transactions and everything else depends on them.
2. **Transaction repository** — filtering and pagination in SQL, never in
   Python. Filters: date range, type, category, payment method, amount range,
   description search; combinable.
3. **Transaction service and endpoints** — CRUD, with every query scoped to
   the current user.
4. **Transactions view** — a table with filter controls, an add/edit dialog,
   and delete confirmation.

**Watch out for:**

- Amounts are `Decimal` and cross the wire as **strings** (ADR-003). Confirm
  Pydantic's serialisation explicitly rather than assuming it.
- Every query must be scoped by `user_id`. One missed filter exposes another
  user's data — worth a test per endpoint that another account's row returns
  404.
- Pagination and filtering belong in the database. Do not fetch rows and
  filter them in Python.
- Loading the category list once per view, not per table row (N+1).

**Deliberately deferred to later phases:** budget calculations (5),
subscription maths (6), any charting (7).

---

## Known limitations, recorded on purpose

- Logout cannot revoke an issued token (ADR-017).
- The access token is not persisted, so the app asks for a password on every
  launch (ADR-016).
- No rate limiting on login. Worth adding in Phase 11 if time allows.
- Single currency. `currency_code` is stored per user so this can change
  without a backfill.
