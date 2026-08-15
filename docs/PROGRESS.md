# Progress

Where the project stands, and what comes next. Updated at the end of each
phase.

**Last updated:** 2026-08-15 · **Current state:** Phase 12 complete — all phases done

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
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest    # expect 1147 passed
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
| 11 | Polish: Settings, rate limiting, loading and empty states, tooltips | ✅ done |
| 12 | Packaging, README, screenshots, demo script | ✅ done |

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
- **Settings** — the account, and every category grouped by direction, with
  add, rename, recolour, retire and restore. Retired categories stay visible
  behind a toggle, because there is no delete to fall back on (ADR-020).

The Subscriptions screen also has **Find subscriptions**, which searches
transaction history for recurring charges and reviews the candidates one at a
time. Nothing is created without being chosen (ADR-007).

The Transactions screen has **Import** and **Export**. Import opens a review
dialog that reads the file, reports what importing it would do, and keeps its
own button disabled until that has happened — changing any option puts it back
to disabled and marks the report out of date, because a preview describes a file
read one particular way (ADR-033).

There are no placeholder sections left. Changing a category in Settings
refreshes the pickers on every screen that is already open (ADR-037), and the
three requests that can take real time — import, export, detection — say so
before they block, since every request in this client is synchronous (ADR-038).

**Tests** — 1147 passing: security, money, budget-arithmetic, billing-cycle,
recurrence, CSV-format, rate-limit and demo-data unit tests; model/constraint and
repository tests against real MySQL; API tests for every feature area; and GUI
tests via pytest-qt, including pixel checks on things no geometry assertion can
catch.

---

## Next: nothing planned

All twelve phases are complete. What follows is a list of what somebody picking
this up would most usefully do, in the order the reasoning below justifies —
not a plan, and nothing here is required for the project to be finished.

1. **Undo for an import.** The single largest gap. Nothing records which
   transactions arrived together, so "undo that import" needs a batch id on
   every row. Worth it the moment importing becomes routine.
2. **A shared store for the rate limiter** (ADR-036). In-process memory means
   the effective limit multiplies by the worker count and a restart forgets
   everything. One line to swap, and a dependency the application does not
   otherwise need.
3. **Requests off the event loop.** Import, export and detection say they are
   working before they block (ADR-038), which is honest rather than responsive.
   The real fix touches every view and needs a cancelled state on each.
4. **A tighter regularity floor for detection.** Candidates come back marked
   *Possible* with evidence like "82±70 days apart" — self-refuting, and
   correctly the lowest confidence level, but noise that costs credibility. The
   fix is a maximum spread relative to the median, not a higher `MIN_REGULARITY`.
5. **Deleting an account.** There is no endpoint, and adding one is not one line:
   `users` cascades to `categories`, but `transactions.category_id` is `ON DELETE
   RESTRICT`, so the cascade fails for any account that has ever recorded
   anything. Deletion has to walk the tables in dependency order. Found while
   clearing the demo account.

**Where to look first:** `docs/DECISIONS.md` for why anything is the way it is,
`README.md` for how to run it, and `docs/DEMO.md` for the order to show it in.

## Known limitations, recorded on purpose

- Logout cannot revoke an issued token (ADR-017).
- The access token is not persisted, so the app asks for a password on every
  launch (ADR-016).
- Login and registration are rate limited per client address, but the store is
  in-process (ADR-036): with more than one worker the effective limit multiplies
  by the worker count, and a restart forgets every tally. A shared store is the
  fix and is a dependency this application does not otherwise need.
- Single currency. `currency_code` is stored per user so this can change
  without a backfill.
- The transactions table cannot be sorted by payment method: the API has no
  sort field for it, so that header is deliberately inert rather than
  appearing to work.
- A category can be renamed and recoloured but its type never changes, and it
  is retired rather than deleted (ADR-020, ADR-037). Both are deliberate; both
  will look like missing features to somebody who does not read the reasoning.
- Requests are synchronous and block the event loop. Imperceptible against
  localhost for anything paged; import, export and detection say they are
  working before they block (ADR-038), which is honest rather than responsive.
  A worker thread is the real fix and would touch every view.
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
- Chart tooltips appear on hover only. There is no keyboard path to the exact
  figures, though the axis labels and printed shares mean nothing is readable
  *only* by hovering.
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
- Name, email and currency are shown in Settings and cannot be changed there.
  Changing an email means proving the new one belongs to you; changing a
  currency means deciding what happens to every amount already recorded.
  Neither is a field edit, and offering one as though it were would be worse
  than not offering it.
- The busy indicator is a wait cursor and a message, not a progress bar. Nothing
  reports how far through an import it is, because a synchronous call cannot
  report anything until it returns.
- Retiring a category takes effect immediately for new records, but a budget or
  subscription already attached to it keeps working. Deliberate — the same
  reasoning as a transaction keeping its category — and it means a retired
  category can still appear on the budgets screen.
- Detection's lowest confidence level can propose genuine noise: a candidate
  whose evidence reads "82±70 days apart" is not regular by any reading. It is
  marked *Possible* and the sentence refutes itself, which is ADR-032 working —
  but it is still a proposal that should not have been made. The fix is a
  ceiling on spread relative to the median, not a higher regularity floor.
- Detection proposes rent and utility bills alongside subscriptions. They are
  genuinely recurring, so these are true positives rather than false ones, but
  somebody expecting only streaming services will read them as noise.
- There is no way to delete an account. Adding one is more than an endpoint:
  `users` cascades to `categories`, while `transactions.category_id` is `ON
  DELETE RESTRICT`, so the cascade fails for any account that has ever recorded
  anything. Deletion has to walk the tables in dependency order.
- The month-to-date insights compare a partial period against a whole one, so
  early in a month "spending is down" is arithmetically true and misleading. The
  demo data pays salary on the first for this reason, which sidesteps the worst
  case rather than fixing it.
- Screenshots in `docs/screenshots/` are captured from the demo account and are
  regenerated by hand. Nothing checks that they still match the interface, so a
  changed screen leaves them stale until somebody re-runs the script.
