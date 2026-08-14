# Progress

Where the project stands, and what comes next. Updated at the end of each
phase.

**Last updated:** 2026-08-15 · **Current state:** Phase 4 complete

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
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest    # expect 280 passed
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
| 4 | Transactions and categories: CRUD, filtering, pagination, data table | ✅ done |
| 5 | Budgets: model exists; utilisation calculations and UI | ⬜ next |
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
| `GET /api/v1/categories` | list; filter by type, hides deactivated by default |
| `POST /api/v1/categories` | create |
| `GET /api/v1/categories/{id}` | one category |
| `PATCH /api/v1/categories/{id}` | rename, recolour, deactivate, restore |
| `GET /api/v1/transactions` | paged, filtered, sorted list |
| `POST /api/v1/transactions` | record one |
| `GET /api/v1/transactions/{id}` | one transaction |
| `PATCH /api/v1/transactions/{id}` | edit |
| `DELETE /api/v1/transactions/{id}` | delete, permanently |
| `GET /api/v1/transactions/payment-methods` | distinct methods in use |

There is no `DELETE /categories/{id}` — see ADR-020.

**Database** — MySQL 8.4, five tables, one migration applied. Schema in
`docs/DATABASE.md`. Phase 4 needed no migration: both tables already existed.

**Desktop client** — PySide6. Login and registration screens, then a shell
with sidebar navigation. Transactions is a real view: a `QAbstractTableModel`
behind a `QTableView`, a filter bar, server-side sorting, a pager, and an
add/edit dialog. Four of six sections are still placeholders.

**Tests** — 280 passing: security and money unit tests, model/constraint and
repository tests against real MySQL, API tests for auth, categories and
transactions, and GUI tests via pytest-qt.

---

## Next: Phase 5 — Budgets

The model and its constraints already exist. What is missing is the
arithmetic and the interface.

1. **Utilisation** — spent, remaining, percentage and status, computed on read
   (ADR-015). `core/money.py` already has `percentage_of`, including the
   zero-denominator rule.
2. **Budget endpoints** — CRUD, plus the computed figures on read.
3. **Budgets view** — one card per budget with a progress bar; green / amber /
   red for healthy / warning / exceeded.

**Watch out for:**

- Spend must be one aggregate query per period, not a query per budget. The
  N+1 test pattern in `tests/db/test_transaction_repository.py` transfers
  directly.
- A budget's category must belong to the user, exactly as a transaction's
  does. `TransactionService._require_own_category` is the shape to copy.
- The `(user_id, category_id, period_start, period_end)` unique constraint
  means overlapping budgets for one category are *not* prevented by the
  schema. Decide deliberately whether to reject them in the service.
- Amounts stay `Decimal` end to end, and `MoneyOut` is what makes them
  strings on the wire.

**Deliberately deferred:** subscription maths (6), charting (7).

---

## Known limitations, recorded on purpose

- Logout cannot revoke an issued token (ADR-017).
- The access token is not persisted, so the app asks for a password on every
  launch (ADR-016).
- No rate limiting on login. Worth adding in Phase 11 if time allows.
- Single currency. `currency_code` is stored per user so this can change
  without a backfill.
- The transactions table cannot be sorted by payment method: the API has no
  sort field for it, so that header is deliberately inert rather than
  appearing to work.
- Categories can only be created and edited through the API, not the
  interface — the Settings section is still a placeholder. The endpoints are
  there and tested; the screen is Phase 11.
- Transaction requests are synchronous and block the event loop. Imperceptible
  against localhost; the point to revisit is if the backend ever moves.
