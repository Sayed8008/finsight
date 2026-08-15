# Progress

Where the project stands, and what comes next. Updated at the end of each
phase.

**Last updated:** 2026-08-15 · **Current state:** Phase 5 complete

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
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest    # expect 399 passed
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
| 5 | Budgets: model exists; utilisation calculations and UI | ✅ done |
| 6 | Subscriptions: model exists; cycle maths and UI | ⬜ next |
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
| `GET /api/v1/budgets` | list, each with spent/remaining/percentage/status |
| `POST /api/v1/budgets` | set a budget |
| `GET /api/v1/budgets/{id}` | one budget with its utilisation |
| `PATCH /api/v1/budgets/{id}` | change amount, period or category |
| `DELETE /api/v1/budgets/{id}` | delete |

There is no `DELETE /categories/{id}` — see ADR-020. The budget endpoints take
an optional `as_of` date, which decides `is_current` and `days_remaining`; it
exists so those fields can be tested without waiting for the calendar.

**Database** — MySQL 8.4, five tables, one migration applied. Schema in
`docs/DATABASE.md`. Neither Phase 4 nor Phase 5 needed a migration: the tables
already existed, and nothing a budget computes is stored (ADR-015).

**Desktop client** — PySide6. Login and registration screens, then a shell
with sidebar navigation. Two real sections:

- **Transactions** — a `QAbstractTableModel` behind a `QTableView`, a filter
  bar, server-side sorting, a pager, and an add/edit dialog.
- **Budgets** — a summary strip and one card per budget, each with a progress
  bar coloured by status, plus a set/edit dialog.

Four of six sections are still placeholders.

**Tests** — 399 passing: security, money and budget-arithmetic unit tests;
model/constraint and repository tests against real MySQL; API tests for auth,
categories, transactions and budgets; and GUI tests via pytest-qt.

---

## Next: Phase 6 — Subscriptions

The model exists, with `billing_cycle`, `status`, `start_date` and
`next_billing_date`. What is missing is the cycle arithmetic and the interface.
This phase is the groundwork for Phase 9.5, where subscriptions are *detected*
rather than entered.

1. **Cycle maths** — advance `next_billing_date` by one cycle; monthly and
   yearly equivalent cost for any cycle (ADR-015: derived, never stored). Pure
   functions in their own module, as `budget_utilisation` is.
2. **Subscription endpoints** — CRUD, plus upcoming renewals within N days.
3. **Subscriptions view** — cards or a table, with the total monthly
   commitment and what renews next.

**Watch out for:**

- **Month-end arithmetic is the trap.** Adding a month to 31 January must not
  produce 31 February. Decide the rule — clamp to the last valid day is the
  usual choice — and test 29/30/31, February, and leap years explicitly.
  `calendar.monthrange` is already used for this in `budget_dialog.py`.
- Monthly equivalents need one conversion table, in one module, or weekly
  (×52/12, not ×4) will end up wrong somewhere.
- `category_id` is **nullable** here, unlike on a transaction — a detected
  subscription may not be categorised yet. Every join and every response has
  to cope with `None`.
- Paused is not cancelled: paused stays visible but out of current cost
  totals. That distinction is in the model already; keep it in the maths.
- The `(user_id, status, next_billing_date)` index exists to serve upcoming
  renewals — write the query so it can be used.

**Deliberately deferred:** detection from transaction history (9.5), charting
(7).

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
- A weekly and a monthly budget cannot both exist for one category, because
  budgets may not overlap (ADR-023). Deliberate: two budgets covering today
  would give "how much is left?" two answers.
- The budgets screen totals only the cards currently on screen. That is a
  presentation sum of figures the server already computed, not a separate
  calculation — but it means the strip reflects the active filters, not the
  whole account. A proper account-wide total belongs to the dashboard (7).
- A budget whose category is later deactivated stays visible and editable. Only
  *attaching* a new budget to a retired category is refused.
