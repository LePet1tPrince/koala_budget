# Koala Budget Export / Import — Implementation Plan

> **Status: proposed.** Nothing below is built yet. Every claim about the current
> schema was read out of the models, and the file/line references are current as
> of this branch.

Goal: a user downloads one file containing everything in their books, and can
load that file into a different Koala Budget team — a new tenant, a second
workspace, a self-hosted instance — and get the same books back. Balances,
budgets, goals and reconciliation state included.

The import **replaces** the destination team's financial data. It never merges.

---

## 1. What this is, and what it is not

`apps/ynab_import` is the neighbour this feature keeps being compared to, and the
comparison is misleading in the way that matters most. A YNAB export is missing
half the information Koala Budget needs (`docs/ynab-import-plan.md` §1: account
type, on-budget vs tracking, income categories, split parents), so that whole app
is an inference engine with a review wizard in front of it, and its integrity
gate is a *reconciliation* — a check that two differently-shaped systems agree.

Here both ends are Koala Budget. Nothing needs inferring. The difficulty moves to
three other places:

1. **Fidelity.** The export must carry enough that the round trip is lossless
   where it claims to be, and the losses must be named rather than discovered.
2. **Destruction.** Loading a file means deleting what is there. That is the
   single most dangerous operation in the product, and §4 is mostly about making
   it hard to do by accident and possible to undo.
3. **Versioning.** A file written today gets loaded a year from now, after the
   schema has moved. The format has to say what it is.

What this is **not**: a report exporter. No income statements, no Sankey data, no
"give me my transactions for a spreadsheet". Those are a separate feature and are
out of scope. It is also not a backup service — no scheduling, no retention, no
off-site copy, with the one exception in §4.4 that exists to make the wipe
survivable.

---

## 2. Three files, ten models

Eleven models hold a team's books. The format folds ten of them into three CSVs
by denormalising every model that is *only* a name or *only* an attachment to
something else, and drops one.

| file | models it carries | how |
|---|---|---|
| `accounts.csv` | `Account`, `AccountGroup`, `Institution`, `Goal` | One row per account. Group and institution attributes ride along as columns; a goal rides on its own backing equity account. |
| `journal.csv` | `JournalEntry`, `JournalLine`, `Payee`, `BankTransaction` | One row per **line**, entry attributes repeated across its lines. Payee is a name column; a feed row is five more columns on the line it belongs to, plus a standalone row when it is uncategorized (§2.4). |
| `budget.csv` | `Budget`, `GoalAllocation` | One row per monthly amount, with a `kind` column saying which it is. |
| — | `TransferMatchDismissal` | Dropped (§2.4). |

### 2.1 The three denormalisations, and why each is safe

**`AccountGroup` → columns on the account.** The group is name, type,
description, `is_system` and `sort_order`. Repeating those on each of its
accounts costs five columns and loses nothing — with one exception named in §2.3.
The account's *type* is already only knowable through its group
(`Account` has no `account_type` field of its own; every report reaches it via
`account_group__account_type`), so flattening it onto the account row arguably
makes the file more readable than the schema.

**`Institution` → a name column.** The model is one field, `name`
(`apps/accounts/models.py:105`). There is nothing to lose.

**`Payee` → a name column.** Same: one field (`apps/accounts/models.py:124`).

**`Goal` → columns on its backing equity account.** This is the least obvious one
and it is the reason three files is enough rather than four. A `Goal` has a
`OneToOneField` to the equity `Account` that backs it — `Goal.save()` creates
that account if one was not supplied (`apps/budget/models.py:124`). So a goal
genuinely *is* an equity account plus a target: name, description,
`target_amount`, `target_date`, `is_complete`, `is_archived`, `order`. Seven
columns, blank on every account that does not back a goal.

**`GoalAllocation` → rows in `budget.csv`.** An allocation is a month, a target
and an amount — the same shape as a `Budget` row, differing only in what the
target is and in carrying a `notes` field. A `kind` column separates them.

### 2.2 References: ids, not names

`Account` has **no** name uniqueness constraint. `AccountGroup`, `Institution`
and `Payee` each carry `unique_together = ["team", "name"]`
(`apps/accounts/models.py:40`, `115`, `133`); `Account` does not, and the
per-type uniqueness the product appears to have is enforced in `AccountForm.clean`
and the accounts board, not in the database. Existing teams can therefore hold two
accounts with the same name, and a format that referenced accounts by name would
silently merge them.

So `accounts.csv` carries an `account_id` column — the source primary key, used
strictly as a **file-local handle** — and `journal.csv` / `budget.csv` reference
it. Every file also carries the account's `name` alongside the id, purely so a
human reading the CSV can follow it; the importer reads the id and ignores the
name. `journal.csv` carries an `entry_id` that groups lines into entries and means
nothing outside the file.

Groups, institutions and payees need no ids: they are unique by name within the
team, which is exactly what makes them safe to denormalise.

### 2.3 What the denormalisation actually costs

Three losses, all small, all named so they are choices rather than surprises:

- **An account group with no accounts disappears.** A user who created "Vacation"
  under Expenses and has not put anything in it yet loses the empty group.
- **An institution with no accounts disappears.** Same shape.
- **A payee never used on an entry disappears.** The bank-feed payee autocomplete
  would lose it. Payees are cheap to recreate and are created implicitly on use.

All three are the same trade — a row that exists only as an anticipation is not
worth a fourth file — and all three are reported in the manifest's `omitted`
block so the import summary can say "3 empty account groups were not included".

**One field, deliberately handled differently between the two name-only models.**
`Institution` and `Payee` are otherwise identical shapes (§2.1), but their
`is_archived`/`archived_at` — inherited from `BaseModel`, never overridden, not
surfaced in any form, serializer or filter for either model (verified: no
`archive()`/`restore()` call, no serializer field, no `is_archived` filter
anywhere in `apps/accounts/`) — are exported for one and not the other.
`institution` appears once per account (§3.2), so carrying its two archive
columns costs nothing. `payee` appears once per **line** — thousands of times
for a common payee — where the same two columns would have to repeat the same
value on every row and be asserted consistent across all of them (the §3.3
repeated-column check, for a fact nothing currently reads). The saved-anyway
argument in §2.6 ("every concrete field travels") is about not losing data
silently; repeating an always-`false` flag 13,000 times is not that — it is
cost with no fidelity behind it, and it is exactly the kind of considered
omission `DELIBERATELY_OMITTED` exists to record, as distinct from the
`goal_archived_at` and `feed_amount` gaps in §3.2/§3.3, which were plain misses.

### 2.4 The bank feed: why inference fails, and what to do instead

An earlier draft of this plan proposed *inferring* feed rows from the journal —
treating any entry with `source` in (`import`, `bank_match`) and a line on a
`has_feed` account as a categorized `BankTransaction`. **That rule is wrong**, and
checking it is what produced this section.

`JournalEntry.source` is documented as "Source of this journal entry" and cannot
be trusted to mean it. It is wrong in both directions:

- **False negatives — feed rows labelled `manual`.** Creating a bank feed
  transaction by hand writes `source=SOURCE_MANUAL`
  (`apps/bank_feed/views.py:486`), and so does categorizing a previously
  uncategorized feed row (`apps/bank_feed/views.py:690`).
  `BankTransaction.journal_source` also maps its own `manual` source to
  `SOURCE_MANUAL`. All three are feed rows the rule would skip.
- **False positives — non-feed entries labelled `import`.** The YNAB importer
  writes `source=SOURCE_IMPORT` on every entry and creates **zero**
  `BankTransaction` rows, deliberately (`apps/ynab_import/services/apply.py:240`,
  and `docs/ynab-import-plan.md` D12: "Straight to the journal … no
  `BankTransaction` rows"). On the sample export that is 6,623 entries. A
  YNAB-migrated team round-tripping through the inference rule would have **6,623
  bank feed rows fabricated for it that never existed** — precisely the "inventing
  an inbox history" failure the rule was written to avoid.

`source` is a grab-bag, not a provenance flag. Opening balances are
`SOURCE_MANUAL` (`apps/onboarding/services/opening.py:149`); reconciliation
adjustments are `SOURCE_BANK_MATCH` and *do* create a feed row
(`apps/bank_feed/views.py:1684`). No rule over it separates feed from non-feed.
**See §8 — this is a real modelling smell that predates this feature.**

#### Adding a flag to the journal instead?

The obvious next move is a new field — `JournalLine.is_bank_feed`, or a
`feed_source` CharField — marking the lines that have a feed row. Rejected, for
three reasons in increasing order of weight:

1. **The attribute already exists.** `BankTransaction.journal_entry` is exactly
   "this ledger entry came from the feed", pointing the other way. A flag on the
   line is a second source of truth for one fact, and **six** write paths would
   have to maintain both (`_create_journal_from_bank_transaction`, manual
   `create`, `update`, `_update_journal_category`, `batch_edit`, CSV
   `_auto_categorize_transaction`). The first one that forgets produces a silent
   export bug.
2. **It needs a migration and a backfill**, and the backfill can only be computed
   from `BankTransaction.journal_entry` anyway — so the field starts life as a
   cached copy of a join.
3. **It does not solve the actual problem.** An *uncategorized* feed row has no
   journal entry and no journal line, so there is nowhere to hang a flag. The
   Inbox — the only part genuinely at risk — would still be lost.

#### What to do instead: carry it, don't infer it

`journal.csv` is already one row per `JournalLine`, and a categorized feed row is
exactly one per line on a feed account. So the feed row rides on the line, the
same denormalisation already used three times in §2.1:

- **Categorized feed rows** → five columns on their line: `feed_source`,
  `feed_posted_date`, `feed_description`, `feed_merchant`, `feed_is_mirror`.
  Blank on every line that has no feed row — which is the fact the inference rule
  was trying and failing to deduce, now simply recorded. A transfer with two feed
  legs fills both lines, `feed_is_mirror` marking which is the synthetic one, so
  the mirror relationship survives without `sync_transfer` having to rebuild it.
- **Uncategorized feed rows** → rows in the same file with `status=uncategorized`
  and a blank `entry_id`. Nothing else in the row applies: no payee, no `dr`/`cr`
  counterpart, no entry. The importer keys on the explicit status value rather
  than on the blank, and §6's balance assertion skips them because they belong to
  no entry.

Cost: no migration, no backfill, no fourth file, and — unlike the inference — it
is exact. `journal.csv` becomes "one row per ledger line, plus one per pending
feed row", which the `status` column states outright on every such row rather than
leaving a reader to work out why some rows have no entry.

**What is still lost**, now down to three things, all small:

- **`BankTransaction.raw`** — the original bank payload. Diagnostic only, and a
  JSON blob in a CSV cell would bloat the file substantially for Plaid rows.
- **`PlaidTransaction` detail** — the pending flag, Plaid's own category, the
  category confidence and the payment channel shown in the edit modal. These hang
  off `PlaidTransaction`, which does not travel (§2.5). All four serializer
  methods are `hasattr`-guarded (`apps/bank_feed/serializers.py:66–89`) and return
  `False`/`None`, so a `plaid`-sourced row renders correctly without them.
- **`TransferMatchDismissal`** — the pairs a user marked "not the same movement".
  Carrying them needs a stable handle for feed rows and a fourth file for two
  foreign keys. The transfer reviewer re-suggests those pairs once and the user
  dismisses them once. Reported in the manifest's `omitted` block so the count is
  at least visible.

#### What the Bank Feed page shows after an import

Everything it showed before, because the page is driven entirely by
`BankTransaction` rows and the journal lines they point at — both of which now
travel:

| surface | source | travels? |
|---|---|---|
| Which account cards appear | `Account.for_team.filter(has_feed=True)` | ✅ `has_feed` is a column |
| Card balance / categorized / reconciled balance | `JournalLine` sums | ✅ |
| Card uncategorized badge, latest-transaction date | `BankTransaction`, excluding archived | ✅ incl. `feed_is_archived` |
| The row list and its pagination | `BankTransaction` | ✅ |
| Quick Filters (To Review / Reconciled / Uncategorized) | `journal_entry` null-ness + `JournalLine.is_reconciled` | ✅ |
| Archived view | `BankTransaction.is_archived` | ✅ |
| Reconciled lock column | `JournalLine.is_reconciled` | ✅ |
| A transfer appearing in **both** account feeds | two feed rows on one entry, `feed_is_mirror` | ✅ |
| Plaid detail in the edit modal | `PlaidTransaction` | ❌ degrades to `None` |

**The one thing that will surprise a user**: entries that never had a feed row are
still not in the feed — YNAB-imported history (zero feed rows by design),
transactions typed on the Transactions page, opening balances. That is faithful
rather than a gap; the feed after an import looks exactly as it did before the
export. It is worth a line in the import summary all the same, because "my
Transactions page has 6,000 rows and my Bank Feed is empty" reads like a bug to
someone who has just migrated.

### 2.5 Out of scope, and why each

- **`plaid` (`PlaidItem`, `PlaidAccount`, `PlaidTransaction`).** `access_token` is
  a live bank credential, and `plaid_item_id` / `plaid_account_id` /
  `plaid_transaction_id` are `unique=True` **globally**, not per team — importing
  them would either collide or hand one tenant another's connection. A migrated
  team re-links its banks.
- **`audit` (`AuditEvent`, `AuditLog`).** The record of who did what in *that*
  team on *that* instance. Replaying it into another tenant under another user's
  name would make the audit log lie, which is the one thing an audit log may not
  do. The import writes its own event instead.
- **`onboarding.OnboardingState`, `monthly_review.MonthlyReviewState`.**
  Walkthrough progress, not books. The importer marks onboarding finished, as
  `apps/ynab_import/tasks.py::_finish_onboarding` already does.
- **`teams`, `users`, `subscriptions`, `api`, `chat`.** Identity, billing,
  configuration — the tenant, not the books.

### 2.6 The field rule, and what does not survive

**Every concrete field on every exported model travels**, minus the three
exceptions below. Stating it as a rule rather than as ten hand-written column
lists is what the completeness test in §7 Phase 5 enforces, and it is not
theoretical: the first draft of §3 listed columns by reading each model's
*declared* fields and so missed `is_archived` and `archived_at`, which
`BaseModel` puts on **all ten** exported models
(`apps/utils/models.py:12–13`) — see §8.

- **`created_at` / `updated_at`.** `BaseModel` sets these with `auto_now_add` /
  `auto_now`, and the honest reading of an imported row's `created_at` is "when it
  was imported". One consequence needs handling rather than accepting:
  `JournalEntry.Meta.ordering` is `["-entry_date", "-created_at"]`, so **same-day
  entries order by insertion sequence**. The exporter emits entries ordered by
  `(entry_date, id)` and the importer inserts in file order, reproducing the
  original relative order of same-day entries. Line order within an entry matters
  too — the transactions table picks debit and credit sides with subqueries
  ordered `("-dr_amount", "pk")` (`apps/journal/filters.py`), which decides the
  split of a `$0.00` entry — so line rows keep file order as well.
- **`JournalLine.budget`.** Derived, not data: it is `(account, month)` looked up
  against `Budget`. Re-deriving on import via the existing
  `JournalLineQuerySet.bulk_create_for_import` (`apps/journal/models.py:99`)
  cannot go stale; carrying it could.

---

## 3. The format

### 3.1 One zip, three CSVs, one manifest

`koala-budget-{team-slug}-{YYYY-MM-DD}.zip`, containing:

```
manifest.json
accounts.csv
journal.csv
budget.csv
```

A zip rather than three loose downloads because a browser cannot hand over three
files as one artifact, and because the manifest has to travel with them. The user
unzips it and can open any CSV in a spreadsheet, which is the whole point of
choosing CSV.

**`manifest.json`** carries what a CSV has nowhere to put:

```jsonc
{
  "format": "koala-budget-export",
  "format_version": 1,
  "exported_at": "2026-09-21T14:03:11Z",
  "source": { "team_name": "Bender Household", "app_version": "…", "currency": "CAD" },
  "files": {
    "accounts.csv": { "rows": 104, "sha256": "…" },
    "journal.csv":  { "rows": 13335, "sha256": "…" },
    "budget.csv":   { "rows": 1904, "sha256": "…" }
  },
  "checks":  { /* §6 */ },
  "omitted": { "empty_account_groups": 3, "unused_payees": 12,
               "uncategorised_bank_transactions": 0 }
}
```

The per-file `sha256` earns its place against a specific hazard: the user opens
`accounts.csv` in Excel to have a look, Excel saves it back having reformatted
every date and stripped a leading zero, and the import then fails somewhere
strange. With the hash, the importer can say *"accounts.csv was modified after it
was exported"* — which is the actual problem. It **warns rather than refuses**,
because hand-editing an export is a legitimate thing to want to do and §6's checks
are the real gate.

### 3.2 `accounts.csv`

One row per account. Ordered by `Account.Meta.ordering`, so the file reads in
chart-of-accounts order.

| column | notes |
|---|---|
| `account_id` | File-local handle (§2.2). |
| `name` | |
| `account_type` | `asset` / `liability` / `income` / `expense` / `goal`. From the group. |
| `group_name`, `group_description`, `group_is_system`, `group_sort_order`, `group_is_archived`, `group_archived_at` | Denormalised `AccountGroup`. |
| `institution`, `institution_is_archived`, `institution_archived_at` | Name, or all three blank. Repeated only once per account (not per use), so carrying the archive flags costs two columns on a ~100-row file rather than the repetition problem `Payee` has (§2.6 note). |
| `has_feed`, `is_system`, `sort_order`, `is_archived`, `archived_at` | |
| `goal_name`, `goal_description`, `goal_target_amount`, `goal_target_date`, `goal_is_complete`, `goal_is_archived`, `goal_archived_at`, `goal_order` | Blank unless this account backs a goal. |

### 3.3 `journal.csv`

One row per **line**, entry columns repeated, plus one row per uncategorized feed
row (§2.4). Ordered by `(entry_date, entry_id)` then line order within the entry
(§2.6), with uncategorized rows last.

| column | notes |
|---|---|
| `entry_id` | Groups lines into entries. File-local. **Blank** on an uncategorized feed row. |
| `entry_date`, `payee`, `description`, `source` | Repeated on every line of the entry. Blank on an uncategorized feed row. |
| `status` | `draft` / `posted` / `void` (D6), or **`uncategorized`** — a file-level value, not a `JournalEntry.status`, marking a pending feed row. |
| `account_id` | References `accounts.csv`. On an uncategorized row, the feed account. |
| `account_name` | **Informational.** The importer reads `account_id`. |
| `entry_is_archived`, `entry_archived_at` | `JournalEntry`'s own archive flags, from `BaseModel`. |
| `dr_amount`, `cr_amount` | Blank on an uncategorized feed row. |
| `is_cleared`, `is_reconciled`, `is_archived`, `archived_at` | Per line, which is where they live. |
| `feed_source` | `plaid` / `csv` / `manual` / `system`, or blank when this line has no feed row. Non-blank **is** the "this came from the bank feed" flag (§2.4). |
| `feed_amount`, `feed_posted_date`, `feed_description`, `feed_merchant` | The feed row's own values. Usually equal to the line's `dr_amount`/`cr_amount` and the entry's date/description, but they can diverge: `apps/journal/views.py` and `apps/journal/serializers.py` — the Transactions page's own edit path — write to `JournalLine`/`JournalEntry` directly and never touch a linked `BankTransaction`. Assuming `feed_amount` was derivable from the line was the first thing this section got wrong (§8): the two are independently editable today, so it needs its own column. |
| `feed_is_mirror` | `true` on the synthetic counterpart leg of a transfer. |
| `feed_is_archived`, `feed_archived_at` | **Load-bearing, and easy to miss.** `BankTransaction.is_archived` is what the feed's Archived view reads, and `_annotate_feed_account_activity` excludes archived rows from `uncategorized_count`, `latest_transaction_date` and `latest_reconciled_date` (`apps/bank_feed/views.py:76–105`). It is a *different field* from the `is_archived` on the same row's `JournalLine`. |

Repeating the entry columns is the cost of one flat file, and it is what makes
`journal.csv` the file a human would actually want: every row is a complete
readable fact. The importer asserts the repeated values are consistent within an
`entry_id` rather than trusting the first one it sees — a hand-edited file that
changes the date on one line of a two-line entry should be told so, not silently
half-applied.

The `feed_*` columns are blank on roughly half the rows (the category side of a
two-line entry never has a feed row). Writing them always, rather than letting
blank mean "same as the entry", keeps §3.5's "blank means blank" rule intact — the
file zips, and an overloaded blank is how a format starts lying.

### 3.4 `budget.csv`

| column | notes |
|---|---|
| `kind` | `budget` or `goal`. |
| `month` | `YYYY-MM-01`. Asserted to be the first of the month — `GoalAllocation.save()` normalises this (`apps/budget/models.py:204`) and `bulk_create` skips `save()`. |
| `account_id` | The category for a `budget` row; the goal's backing equity account for a `goal` row. One column, because a goal is identified by its account (§2.1). |
| `account_name` | Informational. |
| `amount` | Goal allocations may be **negative** — a withdrawal subtracts from the month's allocation (`apps/budget/views.py::goal_withdraw`). |
| `notes` | `goal` rows only. |
| `is_archived`, `archived_at` | From `BaseModel`, per §2.6's rule. |

### 3.5 CSV mechanics worth settling once

- **Encoding: UTF-8 with BOM**, read back with `utf-8-sig`. Excel on Windows
  misreads UTF-8 without a BOM, and payee names carry accents. This matches what
  `apps/bank_feed/services/csv_upload.py` already handles on the way in.
- **Dates: ISO `YYYY-MM-DD`, parsed strictly.** No format guessing. A row that
  will not parse fails loudly with its line number, following the
  `parse_date_strict` precedent in the CSV upload wizard rather than the lenient
  path.
- **Amounts: plain decimal strings**, `-45.50`, no currency symbol, no thousands
  separator, parsed with `Decimal(...)`. A quiet advantage of CSV over JSON here:
  there is no float to accidentally route a `Decimal` through, which is how a
  ledger silently stops balancing.
- **Booleans: `true` / `false`** lowercase. Anything else is an error, not a
  guess.
- **Blank means blank**, not zero and not null-the-string. `dr_amount` is always
  written, `0.00` included.

### 3.6 Size, and why the export is synchronous

The YNAB sample — 5 years, 36 accounts — is 6,623 entries and 13,335 lines. As
CSV that is roughly 2.5 MB across the three files, under 1 MB zipped, and a
handful of queries. It runs in a request.

`StreamingHttpResponse` is the instinct for a large export and has a failure mode
this feature cannot tolerate: a stream that dies halfway sends a `200` with a
truncated file, and the user has something that looks like an export and is not.
Building the zip in memory and sending it with a `Content-Length` makes a
truncated download a transport error the browser reports.

`EXPORT_MAX_ROWS` (200,000 lines, ≈15× the sample) guards the tail: over it the
export refuses with a message rather than filling a worker's memory, and moving to
a Celery job that writes a file becomes a real task rather than speculative work.

### 3.7 Versioning

`format_version` is an integer in the manifest, incremented whenever an existing
column changes meaning or a required one appears.

- **Older** than the importer knows → an upgrade chain of pure functions over the
  parsed rows (`upgrade_1_to_2(tables)`, …). They compose; one test each.
- **Newer** → refuse plainly: "This export was made by a newer version of Koala
  Budget." Guessing at a format from the future is how you write a half-correct
  ledger.
- **Unknown columns** inside a known version are ignored. **Missing** columns that
  the version requires are an error naming the column and the file.

### 3.8 Why not `dumpdata` / `loaddata`

Django's serializers carry the `team` foreign key verbatim with no notion of
retargeting it, so a `loaddata` writes into the *source* team id — on a different
instance, into whatever team happens to hold that id. They also have no place for
§6's checks, no version negotiation, and serialise anything with a FK reachable
from the models named. Three CSVs and a manifest are a few hundred lines of
explicit, auditable code; `loaddata` is a footgun pointed at multi-tenancy.

---

## 4. The wipe

This is the control the feature is really about.

### 4.1 One path, not two

There is no merge mode and no "import into an empty team" fast path. **Every
import wipes first**, including into a team that looks empty — because a
freshly-created team is not empty: `bootstrap_team_on_create` (or the onboarding
flow) has already given it a chart of accounts, including the system
`Reconciliation Adjustments` account that opening balances and reconciliation post
against (`apps/onboarding/services/opening.py:32`). Importing alongside that
leaves two system accounts, two equity groups, and a chart the user did not
choose.

One path also means one thing to test and one thing to explain.

### 4.2 Deletion order is forced by the schema

Three `PROTECT`s decide the order. Relying on cascade would be shorter and wrong
twice over: deleting an `Account` silently takes its `Budget`, `Goal` and
`BankTransaction` rows with it, and the counts reported back to the user should be
*counted*, not inferred from what vanished.

1. `JournalLine` — `account` is `PROTECT` (`apps/journal/models.py:140`).
2. `JournalEntry` — `payee` is `PROTECT`. (`BankTransaction.journal_entry` is
   `SET_NULL`, so feed rows survive this and go on their own terms.)
3. `BankTransaction` — cascades `PlaidTransaction` and `TransferMatchDismissal`.
4. `GoalAllocation`, then `Goal`.
5. `Budget`.
6. `PlaidAccount`, then `PlaidItem` — `PlaidAccount.account` is `PROTECT`
   (`apps/plaid/models.py:65`). **A wipe therefore disconnects the team's banks.**
   That belongs on the confirmation screen in as many words, not in a footnote.
7. `Account`.
8. `AccountGroup` — `Account.account_group` is `PROTECT`.
9. `Payee`, `Institution`.

### 4.3 The audit-signal trap

`apps/audit/signals.py` registers `post_delete` on both `JournalEntry` (line 63)
and `JournalLine` (line 127). `QuerySet.delete()` fires `post_delete` per object,
and to do so Django loads every object into memory first. Wiping the YNAB sample
would load ~20,000 objects and write ~20,000 `AuditLog` rows — each a field-level
diff describing the deletion of a row being deleted as part of one operation the
user performed once.

That is both slow and actively unhelpful: the audit log's value is that a change
to a transaction can be traced, and 20,000 rows saying "wiped" bury that.

**Decision:** the wipe deletes journal rows with `_raw_delete()` on a queryset
whose FKs have already been cleared in order, bypassing the signals, and records
the operation as a single `AuditEvent.DATA_WIPED` carrying per-model counts. This
is the same trade `bulk_create_for_import` already makes in the other direction
(`apps/journal/models.py:99`: "an import is one operation, and 13,000 field diffs
describing it would be noise"). The symmetry is not decoration — it means a
wipe-and-import pair leaves exactly two audit events, which is what happened.

### 4.4 Making it hard to do by accident

Five guards, in order of how much each is worth:

1. **Wipe and import are one `transaction.atomic` block.** A failed import must
   not leave an emptied team. Nearly free — `apply_plan` in the YNAB importer is
   already built this way, for the same reason.
2. **A safety export is taken first, inside the transaction, and stored on the
   import row.** The exporter already exists and runs in under a second; taking
   one before destroying anything turns "I imported the wrong file" from
   unrecoverable into a download link. Retained for `SAFETY_EXPORT_WINDOW`
   (7 days), then blanked by a periodic task — the same reasoning by which
   `YnabImport` clears its staged CSVs.
3. **Admin only** — `@team_admin_required` on every import route. The export is
   fine for any member; the import is not.
4. **Type the team name to confirm**, checked server-side against
   `request.team.name`. The only gesture that reliably survives a distracted
   click.
5. **The confirmation screen shows both sides**: what is in the file (counts, date
   range, net worth) beside what will be destroyed (counts, date range, net worth,
   and the Plaid connections from §4.2). A user with the wrong file open sees it
   here.

### 4.5 A standalone wipe?

Not in this feature. "Clear this team" with no import to follow is a reasonable
thing to want and the machinery here supplies it, but shipping a destructive
button whose only outcome is destruction is a different risk conversation. The
service is written so it can be exposed later (`wipe_team(team) -> WipeCounts`);
nothing exposes it on its own.

---

## 5. Decisions

| | question | resolution |
|---|---|---|
| **D1** | CSV or JSON? | **CSV**, three files plus a JSON manifest, in a zip. CSV costs the nesting (lines under entries) and needs a manifest for anything that is not a table; it buys a file the user can open, and removes the `Decimal`-through-`float` hazard entirely. |
| **D2** | How many files? | **Three**, by denormalising every model that is only a name (`Institution`, `Payee`) or only an attachment (`AccountGroup` → account, `Goal` → its backing equity account, `GoalAllocation` → a budget row with a `kind`, `BankTransaction` → the line it projects). Ten models, three files. |
| **D3** | How are rows cross-referenced? | Source primary keys as **file-local handles**, with the human-readable name beside them as an ignored informational column. Names alone are unsafe: `Account` has no name uniqueness constraint (§2.2). |
| **D4** | The bank feed | **Carried, not inferred** — five `feed_*` columns on the line in `journal.csv`, and uncategorized rows as `status=uncategorized` rows in the same file (§2.4). Inference from `JournalEntry.source` was tried and is provably wrong in both directions; a new flag on `JournalLine` was considered and rejected as a second source of truth that six write paths would have to maintain and that still would not carry the Inbox. Only `raw` and `TransferMatchDismissal` are lost. |
| **D5** | Reconciliation state | Travels, and needs nothing special: `is_reconciled` / `is_cleared` / `is_archived` are `JournalLine` fields, so they are columns in `journal.csv`. |
| **D6** | Void entries | Exported. A void entry is excluded from every balance but it is *evidence* — the transfer-duplicate resolver voids a leg rather than deleting it precisely so the history stays readable. Dropping voids would silently rewrite that history. |
| **D7** | `is_system` accounts and groups | Exported and restored verbatim. Since §4.1 wipes first, there is no conflict with the destination's own system rows to resolve. |
| **D8** | Merge, or replace? | Replace, always. Merging two sets of double-entry books has no correct answer: the same transaction imported twice double-counts every balance, and no key identifies "the same transaction" across tenants. `apps/ynab_import/services/apply.py::can_import` already refuses a non-empty team on this reasoning; this feature supplies the wipe it tells the user to go and do. |
| **D9** | Where does each side run? | Export synchronous with a `Content-Length` (§3.6). Import in Celery, reusing `YnabImport`'s progress machinery — `ProgressChannel` on a second connection, the 99% clamp, the dead-worker grace period. Each of those was found by driving a real import; re-deriving them would be waste. |
| **D10** | Across deployments? | Yes. No URLs, no user ids, no team id in any file. `app_version` is recorded for support; `format_version` is what gates compatibility. |
| **D11** | Multi-currency | The app has no per-account currency field. `source.currency` is informational and the summary states the assumption, matching `docs/ynab-import-plan.md` D13. |
| **D12** | Hand-edited files | Warned about via the manifest's per-file `sha256`, not refused. §6's checks are the real gate. |

---

## 6. The integrity gate

The YNAB importer's best idea is that the import checks itself and the result
gates the "your data is in" screen (`docs/ynab-import-plan.md` §2). Here the check
is stronger, because both sides are the same system — so it is an equality, not a
reconciliation, and a mismatch is a **bug**, not a judgement call.

The exporter computes a `checks` block **by querying the database** — not by
summing the CSVs, or the check only proves the exporter is self-consistent with
itself — and writes it into `manifest.json`:

| check | what it is |
|---|---|
| `counts` | Rows per file, plus entries, accounts, goals. |
| `trial_balance` | `sum(dr_amount)` and `sum(cr_amount)` over non-void lines. Equal in the file *and* after import. |
| `account_balances` | `{account_id: "dr−cr over non-void lines"}` for every account. |
| `net_worth` | Assets − liabilities as of the export date. |
| `budget_totals` | `sum(budget_amount)` per month. |
| `goal_totals` | `{account_id: sum(allocations)}`. |
| `date_range` | First and last `entry_date`. |
| `feed_counts` | Total, uncategorized, archived and mirror `BankTransaction` rows. |

The importer recomputes all of it from the destination database after the writes
and **before the transaction commits**, and compares. Any mismatch raises and
rolls the whole thing back — including the wipe, which is precisely why they share
one transaction. The user sees "the import did not verify, nothing was changed",
which is a far better outcome than a team whose balances are quietly wrong.

Three assertions run before anything is deleted, on the parsed files:

- **every entry balances** — `sum(dr) == sum(cr)` across the rows sharing an
  `entry_id`, checked in Python because `full_clean` on tens of thousands of rows
  is its own query storm (the YNAB precedent). Rows with `status=uncategorized`
  are skipped: they belong to no entry, and folding them in would make every
  file with a pending Inbox fail to balance;
- **every entry's repeated columns are internally consistent** (§3.3);
- **every `account_id` resolves** in `accounts.csv`, and every `month` is a first
  of month.

That ordering is the point: parse and validate first, wipe second, write third. A
file that cannot be imported must never have cost the user their books.

---

## 7. Implementation

New Django app **`apps/portability`**. Not `apps/transfer` — "transfer" already
means something specific and load-bearing here (transfer detection, transfer
mirrors, `TransferMatchDismissal`), and a second meaning would be a lasting tax on
every grep.

Built the way `apps/onboarding` and `apps/ynab_import` are: pure functions for
anything that both previews and applies, side effects confined to one module.

### Phase 1 — The format (pure, no DB)

`services/schema.py` — `FORMAT_VERSION` and, per file, the ordered column list
with a type and a `from_model` / `to_model` mapping. **One place** that says what
a column is, read by the writer, the reader and the tests — the same discipline as
`apps/journal/filters.py::COLUMNS` and
`apps/onboarding/questions.py::QUESTION_CATALOG`.

`services/read.py` — `read_archive(bytes) -> Tables | raise DocumentError`:
unzip, verify hashes (warn), negotiate version, parse each CSV, run §6's
pre-flight assertions. Pure.

`services/upgrade.py` — the `format_version` chain. Empty at v1; exists so the
first migration has somewhere to go.

Tests: a fixture team exercising every awkward corner — a void entry, an archived
line, a reconciled transfer (one entry, two feed-account lines), a goal with
allocations including a negative one, a system account, a `$0.00` entry, an
account named the same as another of a different type, an empty account group.

### Phase 2 — Export

`services/export.py`
- `build_archive(team) -> bytes` — a handful of `select_related`/`prefetch`
  queries, entries ordered `(entry_date, id)`, lines in `id` order (§2.6).
- `build_checks(team) -> dict` (§6), from the database.
- `build_omitted(team) -> dict` (§2.3) — the counts the summary reports.

### Phase 3 — Wipe and apply

`services/wipe.py` — `wipe_team(team) -> WipeCounts`, §4.2's order, §4.3's
`_raw_delete` for journal rows. No `@transaction.atomic` of its own; always called
inside the caller's.

`services/apply.py`, one `transaction.atomic` block:

1. `read_archive` again — the preview ran it, but the request is not the
   authority.
2. Safety export (§4.4.2), stored before anything is destroyed.
3. `wipe_team`.
4. Insert in FK order, building `{file_handle: new_id}`: `Institution`, `Payee`,
   `AccountGroup`, `Account`, `Goal`, `Budget`, `GoalAllocation`, `JournalEntry`,
   `JournalLine`.
5. `BankTransaction` — one per row with a non-blank `feed_source` (linked to the
   line's entry) plus one per `status=uncategorized` row (`journal_entry=None`).
   A straight insert, not a reconstruction: `sync_transfer` is **not** called,
   because `feed_is_mirror` already says which leg is the mirror and re-deriving
   it would be the inference this design exists to avoid.
6. Recompute `checks`, compare, raise on any mismatch.
7. `AuditEvent.DATA_IMPORTED` with counts, wipe counts and the check result.

Four traps this order exists to avoid:

- **`Goal.save()` creates an account** when `pk is None and not account_id`
  (`apps/budget/models.py:124`). Goals are inserted after accounts with
  `account_id` already mapped; `bulk_create` skips `save()` entirely and is the
  safer instrument regardless.
- **`Budget` before `JournalLine`**, because `JournalLine.budget` is resolved from
  `(account, month)` — use the existing
  `JournalLineQuerySet.bulk_create_for_import(lines, budget_map)` rather than a
  second implementation that can drift from it.
- **`GoalAllocation.save()` normalises `month` to the first of the month** and
  `bulk_create` skips it — hence the pre-flight assertion in §6 rather than trust.
- **`bulk_create` skips the audit signals**, which is wanted (§4.3) and must be
  said in the docstring so it is not "fixed" later.

`tasks.py` — `run_data_import`, modelled on `apps/ynab_import/tasks.py`:
`ProgressChannel` on a second connection, both progress channels failing
independently, neither able to fail the import.

### Phase 4 — Endpoints and UI

Team-scoped under `/a/{slug}/data/`:

| route | guard | |
|---|---|---|
| `GET export/` | `login_and_team_required` | Downloads the zip. Logs `AuditEvent.DATA_EXPORTED`. |
| `GET /` | `team_admin_required` | The page: an Export card and an Import card. |
| `POST api/upload/` | `team_admin_required` | Parses and validates; returns the file summary and what would be destroyed. Writes nothing. |
| `POST api/apply/` | `team_admin_required` | Re-checks the typed team name, queues the task. |
| `GET api/status/` | `team_admin_required` | Polled. |
| `GET api/safety-export/` | `team_admin_required` | The pre-wipe copy, while retained. |

One new section in `apps/web/settings_sections.py` under the existing
`GROUP_DATA`, beside "Import from YNAB" and "Audit log" — that list is the single
definition and both the rail and the hub cards read it.

Frontend: Vite entry `data-transfer-app`, `assets/javascript/portability/`. Four
screens over the shared `common/` primitives (`Modal`, `Toast`, `Spinner`) — no
new dependency; the MUI removal in restyle Phase 7 is not to be undone.

1. **Export** — one button, plus the uncategorised-inbox count from D4 with a
   link to the Bank Feed.
2. **Upload** — drop the zip.
3. **Confirm** — §4.4.5's two-column comparison, the Plaid warning, the
   type-the-team-name box. This is the screen the feature lives or dies on; it
   should read as a consequence, not a form.
4. **Apply / Done** — the YNAB apply screen's behaviour (monotonic bar, creep
   between reports, ETA silent below 10%, "waiting for the background worker"
   after 12 seconds), then counts written, the check result, and what did not come
   across.

### Phase 5 — Tests

The headline test is a **round trip**, written first:

```
fixture team → export → wipe+import into a second team → export again
             → assert the two archives are byte-identical after
               normalising the id columns, and that both check blocks match
```

Comparing whole *files* rather than spot-checking balances is what makes this a
fidelity test. Pair it with a **schema-completeness test** that walks each
exported model's `_meta.fields` and fails on any concrete field not either mapped
in `schema.py` or named in an explicit `DELIBERATELY_OMITTED` set. That is the
test that keeps the format honest as the schema moves, and it is the reason the
column lists are data rather than code.

Then: version refusal (newer manifest), upgrade-chain steps, dangling
`account_id`, unbalanced entry, inconsistent repeated entry columns, `Decimal`
fidelity (a `0.10` + `0.20` sum a float would break), UTF-8-with-BOM round trip on
an accented payee, the wipe's deletion order against a team with Plaid rows, the
rollback (force a check failure, assert the destination is untouched), and
`team_admin_required` on every import route.

Three feed-specific tests, each locking a fact §2.4 was written around: a
**YNAB-shaped team** (entries with `source=import` and no feed rows at all)
round-trips with `feed_counts` still zero — the regression test for the inference
rule that was rejected; a **transfer** round-trips as two feed legs on one entry
with `feed_is_mirror` on the same side it started; and an **uncategorized row**
round-trips as an uncategorized row without disturbing the trial balance.

E2E: one Playwright test — export, wipe-import into a second team, assert the
dashboard net worth matches. Page object in `e2e/pages/portability.py`.

---

## 8. Risks

- **The import is the most destructive operation in the product.** Everything in
  §4 is mitigation; the residual risk is a user who confirms without reading. The
  safety export is what makes that recoverable — the part most tempting to cut and
  most important to keep.
- **Schema drift silently breaking fidelity.** A field added to `JournalLine` next
  quarter and not added to `schema.py` produces exports that look fine and quietly
  lose it. The completeness test in Phase 5 is the whole answer, and it works only
  if `DELIBERATELY_OMITTED` is kept honest in review.

  **This already happened, in this document.** The first draft of §3 built its
  column lists by reading each model's *declared* fields, and so missed
  `is_archived` and `archived_at`, which `BaseModel` gives to all ten exported
  models (`apps/utils/models.py:12–13`). The visible consequence was specific:
  `BankTransaction.is_archived` is what the feed's Archived view reads and what
  `_annotate_feed_account_activity` filters on, so every archived feed row would
  have come back **unarchived** — reappearing in the main feed, inflating the
  account cards' uncategorized badge and moving their latest-transaction date.
  A plan written by inspection missed it; the completeness test would not have.
  That is the argument for the test, made once at the plan's own expense.

  **It happened twice more**, at the start of Phase 1, once `_meta.get_fields()`
  was actually run against the ten models instead of read off the source by eye:
  `goal_archived_at` was missing from `accounts.csv` (§3.2 — `Goal` inherits
  `archived_at` from `BaseModel` without overriding it, same as everything else,
  and the table simply did not list it), and `BankTransaction.amount` had no
  column at all (§3.3), on the false assumption that it was always derivable from
  its journal line's `dr_amount`/`cr_amount`. It is not: the Transactions page's
  own edit path (`apps/journal/views.py`, `apps/journal/serializers.py`) writes
  to the line directly and never touches a linked `BankTransaction`, so the two
  can drift. Both are fixed in §3.2/§3.3. Three misses from the same cause in one
  document is the actual argument for running the introspection *before* writing
  the column lists, not just testing them after — which is what Phase 1's
  implementation does (`schema.py`'s field maps are built from
  `model._meta.get_fields()`, checked in, and the CSV columns are generated from
  them, so a table like this one can no longer be the source of truth that drifts
  from the code).
- **Denormalisation makes the schema harder to change.** Adding a field to
  `AccountGroup` now means adding a column to `accounts.csv` and bumping
  `format_version`. That is the standing cost of three files instead of eleven,
  and it is worth naming as a cost rather than pretending it away.
- **Users will edit these files.** CSV's readability is the feature and its
  hazard. The hash warning, strict parsing and §6's checks are three layers
  against it; none makes hand-editing safe, and the summary should not imply it
  does.
- **`_raw_delete` bypasses signals by design** — if a future signal on
  `JournalLine` does something that matters, the wipe skips it. Worth a comment at
  the call site so the next person adding such a signal finds it.
- **`BudgetService.available()` is recursive per category per month**, already
  flagged by the YNAB plan (§6). An imported team with five years of history hits
  the same wall by the same route. Not this feature's bug, but this feature will
  find it.
- **`JournalEntry.source` does not mean what it says** (§2.4). This feature routes
  around it rather than fixing it, which is the right scope call but leaves the
  smell in place: a field whose `help_text` reads "Source of this journal entry"
  and whose value cannot answer where the entry came from. It is also load-bearing
  elsewhere — the Transactions page filters and badges on it
  (`apps/journal/filters.py`, `columns.js`'s `SOURCE_STYLES`), so those badges are
  showing users the same unreliable fact. Worth its own ticket: either a real
  provenance field maintained in one place, or narrowing `source` to what it can
  actually promise.

---

## 9. Open questions

1. ~~**Is losing the uncategorised Inbox acceptable?**~~ **Resolved** (§2.4): it
   is not lost. Uncategorized feed rows travel as `status=uncategorized` rows in
   `journal.csv`, at the cost of that file meaning "one row per ledger line, plus
   one per pending feed row". The remaining question is whether that dual meaning
   is worth it against a fourth `inbox.csv` — three files was the goal, and the
   `status` column makes each such row self-describing, so the recommendation is
   to keep it at three.
2. **Retention on the safety export.** 7 days is a guess. It is someone's entire
   financial history in a table; shorter is safer, longer is kinder to a user who
   realises a week later.
3. **May non-admins export?** Proposed yes, read-only, own team. The
   counter-argument is that a full export is the cleanest possible exfiltration.
   If the answer is no, it costs one decorator.
4. **Encryption at rest for the safety export.** The same question as
   `PlaidItem.access_token` under Known Issues, and probably the same answer at
   the same time rather than separately.
5. **`AuditEvent` types.** Three new — `DATA_EXPORTED`, `DATA_WIPED`,
   `DATA_IMPORTED` — and one audit migration, named here so the numbering is
   settled before two branches both add one.
