# Progress

Where the project stands, and what comes next. Updated at the end of each
phase.

**Last updated:** 2026-08-15 · **Current state:** Phase 10 complete

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
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest    # expect 1043 passed
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
| 9.5 | **Subscription auto-detection** from transaction history | ✅ done |
| 10 | CSV import (preview then commit) and export | ✅ done |
| 11 | Polish: error/empty/loading states, logging, theming | ⬜ next |
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
| `POST /api/v1/subscriptions/detect` | propose subscriptions found in history; creates nothing |
| `GET /api/v1/csv/transactions` | the filtered set as a CSV file, oldest first |
| `POST /api/v1/csv/preview` | what an import would do; writes nothing |
| `POST /api/v1/csv/import` | apply a previewed file, in one transaction |

There is no `DELETE /categories/{id}` — see ADR-020. The budget endpoints take
an optional `as_of` date, which decides `is_current` and `days_remaining`; it
exists so those fields can be tested without waiting for the calendar.

**Database** — MySQL 8.4, five tables, one migration applied. Schema in
`docs/DATABASE.md`. Phases 4, 5 and 6 needed no migration: the tables already
existed, and everything they compute is derived, never stored (ADR-015).

**Desktop client** — PySide6. Login and registration screens, then a shell
with sidebar navigation. Six real sections:

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

The Subscriptions screen also has **Find subscriptions**, which searches
transaction history for recurring charges and reviews the candidates one at a
time. Nothing is created without being chosen (ADR-007).

The Transactions screen has **Import** and **Export**. Import opens a review
dialog that reads the file, reports what importing it would do, and keeps its
own button disabled until that has happened — changing any option puts it back
to disabled and marks the report out of date, because a preview describes a file
read one particular way (ADR-033).

Only **Settings** is still a placeholder.

**Tests** — 1043 passing: security, money, budget-arithmetic, billing-cycle,
recurrence and CSV-format unit tests; model/constraint and repository tests
against real MySQL; API tests for every feature area; and GUI tests via
pytest-qt, including pixel checks on things no geometry assertion can catch.

---

## Next: Phase 11 — Polish

The features are done. What is left is everything the demo will be judged on
that is not a feature: the states a screen is in when it is not showing data,
the one section that is still a placeholder, and the details that have been
listed as known limitations for nine phases.

1. **Settings, which is still a placeholder.** The category endpoints exist and
   are tested; there is no screen. It is the last inert item in the sidebar and
   the most visible gap.
2. **Loading states.** Every request in this client is synchronous, so a slow
   one freezes the window with no indication why. Nothing is perceptible against
   localhost — but export and import are the first requests that can take real
   time, because they are the first bounded by file size rather than by page
   size.
3. **Error and empty states, audited rather than assumed.** Most screens have
   them. Whether every screen has a *distinct* one for "nothing yet" and
   "nothing matches these filters" has not been checked in one pass.
4. **Rate limiting on login.** Listed as a known limitation since Phase 3, and
   the only one on the list that is a security gap rather than a scope decision.
5. **Chart tooltips**, if there is time. The spending and trend charts have
   none; values are readable from the axis and the labels, so this is polish in
   the literal sense.

**Watch out for:**

- The rendering practice (ADR-012) has caught a real defect in every UI phase,
  including this one — the stale import report went on claiming "412 of 418 rows
  would be imported" for a reading nobody had chosen. Render the Settings screen
  and look at it before writing a test for it.
- A category screen has to deal with ADR-020: there is no DELETE, so the verb is
  "deactivate", and the screen has to show deactivated categories in a way that
  makes restoring them possible without making them look active.
- A loading state that appears for two milliseconds is worse than none. If one
  is added, it needs a delay before it shows.

**Then Phase 12:** packaging, README, screenshots, demo script.

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
- Detection matches merchant names exactly after normalising, so "NETFLIX
  AMSTERDAM" and "NETFLIX" are two merchants. Deliberate (ADR-031): a missed
  subscription costs nothing, a merged pair produces a confident wrong claim
  about someone's money.
- "Not a subscription" hides a candidate for that review only. A permanent
  never-suggest list needs its own table and a way to undo it, so the button
  does not pretend to more than it does.
- Detection needs at least three charges, so a subscription started two months
  ago cannot be found yet.
- Descriptions carrying no merchant — `POS PURCHASE 4021` — are unmatchable.
  Recorded in ADR-007 from the start and still true.
- Renewals are recorded by hand ("Mark renewed"). Nothing advances a billing
  date automatically, because nothing runs when the app is closed. A scheduled
  job would be a service, not a desktop app.
- An active subscription whose date has passed shows as overdue rather than
  rolling forward on its own — the app cannot know whether the charge was
  actually taken.
- `POST /subscriptions` accepts a `next_billing_date` in the body and ignores
  it, rather than rejecting the request. Pydantic drops unknown fields; the
  derived value always wins.
- A raw bank statement cannot be imported as it stands: every row needs a
  category, because `transactions.category_id` is NOT NULL and there is no
  "uncategorised" row (ADR-006). The import takes an optional fallback category
  instead of inventing one, so it takes one extra choice rather than an edit to
  the file.
- The importer reads no date format that spells its month — `4 Mar 2026` is
  refused. Three numbers with a stated order, or nothing.
- Duplicate detection ignores rows with no description, so re-importing a file
  of undescribed rows will double them. Deliberate, and the same asymmetry as
  ADR-031: an extra row is visible and deletable, a wrongly skipped one is data
  silently lost.
- The import reads the whole file into memory and answers in one request. Fine
  at the 5,000-row ceiling; a file large enough to need streaming would need a
  job, which is a service rather than a desktop app.
- Import and export are synchronous like every other request, so a large file
  blocks the window while it is read. The first place where that could actually
  be felt, since these are the only requests bounded by file size rather than
  page size. Phase 11.
- An import cannot be undone. Nothing records which transactions arrived
  together, so "undo that import" would need a batch id on every row — worth it
  only if imports become routine.
- A file previewed while another window changes the same categories could be
  refused at commit for a reason the preview did not show. The refusal is
  correct and the window is milliseconds; nothing pretends otherwise.
