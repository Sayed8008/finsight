# Demonstration script

Twelve minutes, in the order that makes the most of what is here. The two
features worth building the demo around are **subscription detection** and **CSV
import** — detection because it is the only genuine algorithm in the project,
and import because it is where the most careful design went.

Everything below runs against the demo account, which is deterministic: the same
seed produces the same figures, so this can be rehearsed and will not surprise
you on the day.

---

## Before you start

```bash
./scripts/dev.sh backend                       # one terminal
.venv/bin/python scripts/seed_demo.py          # once — takes about a minute
./scripts/dev.sh client                        # another terminal
```

Sign in as `demo@finsight.app` / `demo-account-password`.

**Have ready:** a terminal with `http://127.0.0.1:8000/docs` open in a browser,
and a CSV file to import (see step 6 — you export one during the demo).

**Check first:** the budgets screen should show one green bar, one amber and one
red. If they are all green, the seed ran on the first or second of a month and
there is not enough spending yet; re-seed with `--days 400`.

---

## 1 · The problem (30 seconds)

Say it before showing anything:

> Money leaves on standing orders and nobody notices. The average person is
> paying for two or three things they have forgotten about. Every finance app
> shows you what you spent; this one tells you what you are *committed* to, and
> finds the commitments you did not know you had.

---

## 2 · Dashboard (1 minute)

The landing screen. Point at three things and no more:

- **The hero figure** is larger than everything else on purpose. A row of six
  equally loud numbers has no lead and the eye has nowhere to land.
- **The spending chart is bars, not a pie.** The question is "which is biggest
  and by how much", and lengths against a shared baseline are easy to compare
  where angles are not. The percentage is printed beside each bar, so the
  part-to-whole reading is not lost.
- **The line at the bottom** is not computed here. It is the top finding from
  the insights engine, rendered — so the dashboard and the insights screen can
  never disagree about what matters.

Worth saying: this whole screen is **one** request. Five requests would mean
five loading states and five chances to show figures taken at different moments.

---

## 3 · Transactions (1 minute)

- Type in the search box. One request goes out, not nine — the keystrokes are
  debounced.
- Sort by amount. **Every filter, sort and page happens in SQL.** Sorting in the
  client would reorder the twenty-five rows on screen and then disagree with a
  pager describing four hundred.
- Click the payment-method header. Nothing happens, deliberately: the API has no
  sort field for it, so the header is inert rather than pretending to work.

---

## 4 · Budgets (1 minute)

Three bars, three states — green, amber, red. Then say what is *not* happening:

> None of these numbers are stored. Spent, remaining, percentage and status are
> all recomputed on every read. A stored total is a cache, and it is wrong the
> instant a transaction is edited.

If asked why two budgets cannot overlap: because "how much is left for Food?"
would then have two answers, and every screen consuming it would have to pick
one arbitrarily.

---

## 5 · Find subscriptions — **the centrepiece** (3 minutes)

Go to **Subscriptions**. One is tracked. Then press **Find subscriptions**.

Talk through one candidate slowly:

> It found Adobe. Five charges of 2,100.00, ninety days apart, give or take two.
> That sentence *is* the confidence. It does not say "87% confident", because
> nobody can check 87% — you can check five charges ninety days apart against
> your own transaction list in about four seconds.

Then the three things it got right:

1. **Spotify has a price rise partway through** — 199 to 219 — and it is still
   *one* subscription. Exact amount matching would have split it into two and
   then found neither half recurring.
2. **The gym is not in this list.** It is paid for similar amounts at 18, 44, 25
   and 51 day gaps. That is a habit, not a subscription, and a detector that
   proposed it would be proving its threshold was low rather than that it works.
3. **Nothing has been created.** Press *Not a subscription* on one, *Track it* on
   another. Only the one you chose exists now. There is deliberately no "Track
   all" button — accepting eight guesses at once is exactly the action nobody
   takes carefully.

Be ready for this question — *"Rent and internet are in the list, is that
wrong?"*:

> No. Both genuinely recur, and somebody reviewing their commitments should see
> them. What is *not* in the list is the more interesting part: a year of
> groceries, taxis and cinema tickets contains runs that look regular from a
> distance, and earlier versions proposed several of them with evidence like
> "98±69 days apart". A spread of sixty-nine days on a ninety-eight day
> interval is not a rhythm, and the sentence gives itself away — so the rule is
> now that the spread shown must be within forty per cent of the interval
> shown. The check is on the numbers the user actually reads.

---

## 6 · Export, then import — **the second centrepiece** (3 minutes)

Back to **Transactions**. Press **Export** and save the file. Open it in a
spreadsheet if you can:

> Plain decimals, ISO dates, no currency symbols. It is data before it is a
> report. There is also an apostrophe in front of any description starting with
> `=` — otherwise a description somebody typed becomes a formula the moment
> Excel opens it.

Now press **Import** and choose the same file. **Do not press the import button
yet** — the point is what happens before it.

- The Import button is disabled. It stays that way until the file has been read.
- Press **Check the file**. The report says exactly what would happen: how many
  rows, which categories, and — because this is the file we just exported —
  that every row is already recorded.
- **Change the date order.** The report is immediately marked out of date and
  the button goes back to disabled, because a preview describes a file read one
  particular way.

Then the sentence to land:

> The import will not run without the fingerprint the preview handed back, and
> that fingerprint covers the options as well as the file. So you cannot import
> a file you have not looked at, and you cannot preview it one way and import it
> another. And when it does run, every row lands or none does — a file that half
> imports is worse than one that does not import at all, because nobody can tell
> which half landed.

If there is time, edit a row of the CSV to have a bad date and check it again:
the preview names the line number and the reason, and offers to import the rest
only *after* showing exactly what it would leave out.

---

## 7 · Insights (1 minute)

> Every one of these explains itself. Each names the figure it found and what it
> was compared against. "Unusual spending detected" is a shrug with a badge —
> there is a test asserting that every insight any rule produces contains a digit
> and more than twenty characters of explanation, and it applies to rules that
> have not been written yet.

Click through from an insight to the screen it concerns.

---

## 8 · Analytics and Settings (1 minute)

- The trend chart is **blue and orange, not green and red**, although green and
  red are used everywhere else an amount carries a sign. Here there is no sign —
  both series are positive bar heights — so colour is the only thing separating
  them, and measured, green and red are the same colour to roughly one man in
  twelve.
- Settings: categories are **retired, not deleted**, and retired ones stay
  visible so they can be restored. There is no delete endpoint, because the
  foreign key would refuse it for any category that had ever been used.

---

## 9 · Close (30 seconds)

> Three things I would point at if you only remember one slide. It is layered —
> the interface cannot reach the database even if somebody wanted it to. The
> arithmetic is in pure functions with no database and no clock, which is why
> there are eleven hundred tests and they run in under two minutes. And the
> decision log has forty entries, each with what I rejected, because most
> of the interesting work was in the choices that do not show up as features.

---

## Questions to expect

**"Why not connect to a bank?"** Open banking needs a licensed aggregator and
a production security posture. CSV import is the honest version of the same
capability, and it is where the careful design went.

**"Why a desktop app rather than a web app?"** Layered separation over a network
boundary was the objective, and the boundary is real either way. A web client
would be a client of the same API, not a rewrite.

**"How do you know the detection works?"** It is a pure function, so it is
tested directly — every threshold and boundary, including the ones that must
*not* fire. And the demo data itself has a test that runs the real detector over
it and asserts it finds the three subscriptions and not the gym.

**"What would you do next?"** Undo for imports, a shared store for the rate
limiter so it survives more than one worker, and moving requests off the event
loop. All three are in the limitations list with the reasoning.

**"What went wrong?"** The one I would lead with is not an interface defect.
Running detection over a year of realistic history — rather than over the tidy
dates the unit tests used — showed it proposing candidates whose own evidence
refuted them: "98±69 days apart" is not a rhythm, and the sentence says so. The
tests all passed, because every one of them used intervals chosen to be either
regular or obviously irregular, and nothing in between. The fix was a ceiling on
the worst gap rather than a higher average, and it is checked against the exact
figures the sentence prints.

Rendering the interface caught a defect in every single interface phase — a primary button painted in nothing, a checkbox with no box,
combo boxes that had no dropdown arrow for seven phases, and an import report
that went on claiming "412 of 418 rows would be imported" after the options had
changed. None of them were visible in the source, and none would have been
caught by a test of geometry or visibility.
