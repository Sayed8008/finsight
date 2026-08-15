# Progress

Where the project stands, and what comes next. Updated at the end of each
phase.

**Last updated:** 2026-08-15 · **Current state:** Phase 9 complete

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
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest    # expect 749 passed
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
| 6 | Subscriptions: model exists; cycle maths and UI | ✅ done |
| 7 | Dashboard: financial summary, QtCharts, recent activity | ✅ done |
| 8 | Analytics: aggregation endpoints, period comparison, charts | ✅ done |
| 9 | Insights: rule engine, severity, explanations | ✅ done |
| 9.5 | **Subscription auto-detection** from transaction history | ⬜ next |
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
| `GET /api/v1/subscriptions` | list, with costs and renewal timing |
| `GET /api/v1/subscriptions/summary` | monthly/yearly commitment, next renewal |
| `POST /api/v1/subscriptions` | track one |
| `GET /api/v1/subscriptions/{id}` | one subscription |
| `PATCH /api/v1/subscriptions/{id}` | edit |
| `POST /api/v1/subscriptions/{id}/renew` | record a charge, advance the date |
| `DELETE /api/v1/subscriptions/{id}` | delete outright (not the same as cancelling) |
| `GET /api/v1/dashboard` | the whole first screen in one payload |
| `GET /api/v1/analytics/trend` | income and expense per month, gaps filled |
| `GET /api/v1/analytics/comparison` | a period against the one before it |
| `GET /api/v1/insights` | what is worth knowing, each explaining itself |

There is no `DELETE /categories/{id}` — see ADR-020. The budget endpoints take
an optional `as_of` date, which decides `is_current` and `days_remaining`; it
exists so those fields can be tested without waiting for the calendar.

**Database** — MySQL 8.4, five tables, one migration applied. Schema in
`docs/DATABASE.md`. Phases 4, 5 and 6 needed no migration: the tables already
existed, and everything they compute is derived, never stored (ADR-015).

**Desktop client** — PySide6. Login and registration screens, then a shell
with sidebar navigation. Five real sections:

- **Dashboard** — a hero figure and stat tiles, a ranked spending chart, recent
  activity, and one line naming whatever needs attention.
- **Transactions** — a `QAbstractTableModel` behind a `QTableView`, a filter
  bar, server-side sorting, a pager, and an add/edit dialog.
- **Budgets** — a summary strip and one card per budget, each with a progress
  bar coloured by status, plus a set/edit dialog.
- **Subscriptions** — a commitment strip, one card per subscription with its
  state and renewal wording, and a track/edit dialog.
- **Analytics** — a grouped monthly trend chart, change tiles, and a table of
  what moved against the previous period.
- **Insights** — one card per finding, severity in colour and in words, each
  with the explanation the rule wrote and a link to the screen it concerns.

A sixth section, **Insights**, lists what the rules found. Only
**Settings** is still a placeholder.

**Tests** — 749 passing: security, money, budget-arithmetic and billing-cycle
unit tests; model/constraint and repository tests against real MySQL; API tests
for every feature area; and GUI tests via pytest-qt, including pixel checks on
things no geometry assertion can catch.

---

## Next: Phase 9.5 — Subscription auto-detection

The feature ADR-007 promoted to its own phase, and the only part of the project
that is a genuine algorithm rather than CRUD plus arithmetic. It finds
subscriptions the user never told the application about, by looking for
recurrence in transactions they already recorded.

1. **Description normalisation** — strip reference numbers, dates and card
   digits so "NETFLIX.COM 4021" and "NETFLIX COM" group together.
2. **Amount clustering with tolerance** — a subscription that rises from 499 to
   549 is the same subscription, and an exact-match grouping would miss it.
3. **Interval regularity scoring** — three charges 30, 31 and 29 days apart is
   monthly; 30, 5 and 62 is not. The score has to survive a missing month.
4. **Confidence with evidence** — every candidate says which transactions it
   was built from and why it scored what it did.
5. **`POST /subscriptions/detect`** — returns candidates. It creates nothing.

**Watch out for:**

- **ADR-007 is explicit: detection never creates a subscription silently.** It
  proposes; the user confirms. A wrong guess that quietly appears in someone's
  commitment total is worse than no guess.
- Confidence must be **explainable in the same way insights are** — "four
  charges of 499.00, 30±1 days apart" and not "87%". The evidence *is* the
  confidence. `insight_rules` is the shape to copy.
- Skip candidates that match an existing subscription:
  `SubscriptionRepository.name_exists` was written for exactly this.
- The algorithm is pure and belongs in its own module, testable without a
  database. Only the gathering touches the session.
- ADR-007 records the honest limitation: detection is bounded by the quality of
  the description column, and `POS PURCHASE 4021` is unmatchable. Say so in the
  interface rather than returning nonsense.

**Deliberately deferred:** CSV import and export (10).

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
- Existing accounts keep the category colours seeded when they registered. The
  validated palette (ADR-026) only reaches new accounts — the column is
  per-user and editable, so no backfill was run.
- The dashboard's attention line is computed in the view. It should become a
  rendering of insights in Phase 9 (ADR-008), not a second place that decides
  what matters.
- The spending chart and the trend chart have no hover tooltips. Values are
  readable from the axis and the labels; a tooltip layer is Phase 11 polish.
- Analytics comparison always uses the immediately preceding window. Comparing
  against the same month last year would need a second mode.
- Insight thresholds are constants in `insight_rules.py`, not user settings.
  Gathered and named in one block so they can become settings later without a
  hunt, but nobody can tune them from the interface today.
- Insights are recomputed on every request. Correct, and the reason they can
  never be stale — but it means the screen costs a fixed handful of queries
  each time it is opened rather than being free to poll.
- The insights screen has no "dismiss". An insight goes away when the thing it
  describes changes, which is honest but means a known-and-accepted situation
  keeps being reported.
- Renewals are recorded by hand ("Mark renewed"). Nothing advances a billing
  date automatically, because nothing runs when the app is closed. A scheduled
  job would be a service, not a desktop app.
- An active subscription whose date has passed shows as overdue rather than
  rolling forward on its own — the app cannot know whether the charge was
  actually taken.
- `POST /subscriptions` accepts a `next_billing_date` in the body and ignores
  it, rather than rejecting the request. Pydantic drops unknown fields; the
  derived value always wins.
