# Transaction Rules — Requirements

Status: approved design, not started. This document is the complete brief for the implementing agent.
Read `CLAUDE.md` first; its single-writer rules apply to everything here.

## 1. Goal

Let a book define rules that categorize bank-feed transactions automatically or by suggestion:
"when money out is more than $120 and the description contains INSURANCE, categorize as Car Insurance".

Parity target is QuickBooks Online bank rules. On top of parity, the feature must be smarter in nine named
ways (section 9). Deterministic logic only: no LLM calls.

## 2. Decisions already made (do not reopen)

1. A rule match supersedes the history-based suggestion (`similar_categories` / `category_suggestions`).
   One suggestion slot per row: rule match if there is one, history-based suggestion otherwise.
2. A rule may categorize to another feed account (a transfer), but only in `suggest` mode. Never auto-post.
3. Thresholds (all constants in `apps/rules/constants.py`, nowhere else):

| Constant | Value | Meaning |
|---|---|---|
| `GRADUATE_STREAK` | 5 | Consecutive unchanged confirmations before offering auto-post |
| `DEMOTE_WINDOW` | 10 | Most recent auto-posted matches examined for demotion |
| `DEMOTE_OVERRIDES` | 2 | Overrides within the window that demote a rule to suggest |
| `ANOMALY_MULTIPLE` | 3 | Auto-post held when amount exceeds this × the rule's median |
| `ANOMALY_MIN_SAMPLES` | 5 | Matches a rule needs before the anomaly guard applies |
| `LEARN_MIN_COUNT` | 4 | Same-signature categorizations needed to propose a rule |
| `LEARN_MIN_CONSISTENCY` | 0.9 | Share of those that must agree on one category |
| `MAX_RULES_PER_BOOK` | 200 | |
| `MAX_CONDITIONS_PER_RULE` | 10 | |

## 3. Existing code to build on

| Piece | Location | Use |
|---|---|---|
| Single-category write path | `apps/bank_feed/services/categorize.py::categorize_single` | Rule category action |
| Split write path | `apps/bank_feed/services/splits.py::apply_splits`, `parse_legs` | Rule split action |
| Batch-edit field writes | `apps/bank_feed/views.py::BankFeedViewSet._apply_batch_edit`, `_batch_edit_refusal` | Extract (section 6.1) |
| Decategorize | `apps/bank_feed/views.py::BankFeedViewSet._decategorize` | Undo of an auto-post |
| Text normalization | `apps/bank_feed/services/similar_transactions.py::normalize`, `signature_tokens`, `NOISE_TOKENS` | Matching, draft rules, learning |
| History index | `similar_transactions.py::build_history_index` | Backtest, learning |
| Transfer candidates | `apps/bank_feed/services/feed_query.py::transfer_candidate_ids` | Auto-post hold (section 6.4) |
| Feed query params | `feed_query.py::FeedParams` | New `rule` filter |
| Plaid ingestion | `apps/plaid/tasks.py` (`BankTransaction.objects.create` near line 325) | Engine trigger |
| CSV ingestion | `apps/bank_feed/services/csv_upload.py` (create near line 881) | Engine trigger |
| Guards | `apps/journal/services/period_lock.py`, `apps.reconciliation.services.guards`, `apps.accounts.guards.assert_category_allowed` | Call, never restate |
| Audit | `apps/audit/utils.py::log_event`, `apps/audit/models.py::AuditEvent` | New event types |
| Scheduled tasks | `koala_budget/settings.py::SCHEDULED_TASKS` | Nightly learning task |

Conventions that matter here: `BankTransaction.amount` is signed, positive = outflow.
The feed's "payee" is `BankTransaction.merchant_name`; a categorized row's entry also has `JournalEntry.payee` (FK to `Payee`).

## 4. Data model — new app `apps/rules`

Mount at `rules/` in `book_urlpatterns` (`koala_budget/urls.py`). All models extend `BaseBookModel`.

### 4.1 `Rule`

| Field | Type | Notes |
|---|---|---|
| `name` | `CharField(100)` | `unique_together = ["book", "name"]` |
| `is_active` | `BooleanField(default=True)` | |
| `priority` | `PositiveIntegerField` | Lower wins. Not unique; order by `(priority, id)` |
| `mode` | `suggest` \| `auto_post` | Default `suggest` |
| `direction` | `any` \| `in` \| `out` | `out` = `amount > 0`, `in` = `amount < 0` |
| `accounts` | M2M → `accounts.Account` | Feed accounts only. Empty = every account |
| `match` | `all` \| `any` | How conditions combine. Direction and accounts always AND |
| `conditions` | `JSONField` | List of `{field, op, value}`; see 5.1. May be empty if direction or accounts is set |
| `category` | FK → `accounts.Account`, `SET_NULL`, nullable | Single-category action |
| `splits` | `JSONField`, nullable | `[{"category": <id>, "percent": "<decimal>"}]`, sums to 100 |
| `payee_name` | `CharField(200, blank=True)` | Blank = leave payee alone |
| `description` | `CharField(255, blank=True)` | Blank = leave description alone |
| `origin` | `manual` \| `from_action` \| `learned` | |
| `times_applied`, `times_confirmed`, `times_overridden` | `PositiveIntegerField` | |
| `confirm_streak` | `PositiveIntegerField` | |
| `last_matched_at` | `DateTimeField`, nullable | |
| `graduation_declined_at` | `DateTimeField`, nullable | User declined the auto-post offer; do not offer again |
| `demoted_at` | `DateTimeField`, nullable | Set when auto-demoted; cleared when the user re-enables auto-post |

Validation (serializer, and `clean()`):
- Exactly one of `category` / `splits` is set, or neither if `payee_name` or `description` is set (a rename-only rule).
- A rename-only rule cannot be `auto_post` in the sense of posting; it applies its renames on match and leaves the row uncategorized.
- `category` and every split category pass `assert_category_allowed`.
- If `category` is a feed account (`has_feed`), `mode` must be `suggest`. Split legs may not be feed accounts.
- A rule needs at least one of: a condition, a direction other than `any`, an account.
- Limits from section 2.

A rule whose `category` was nulled by account deletion, or whose category no longer passes `assert_category_allowed`,
is treated as inactive by the engine and shown as "Needs attention" on the rules page.

### 4.2 `RuleMatch`

| Field | Type | Notes |
|---|---|---|
| `transaction` | `OneToOneField` → `bank_feed.BankTransaction`, `CASCADE`, `related_name="rule_match"` | |
| `rule` | FK → `Rule`, `SET_NULL`, nullable | |
| `rule_name` | `CharField(100)` | Snapshot, shown after the rule is deleted |
| `status` | `suggested` \| `auto_posted` \| `confirmed` \| `overridden` \| `dismissed` | |
| `held_reason` | `""` \| `unusual_amount` \| `transfer_candidate` \| `closed_period` \| `refused` | Why an auto-post rule only suggested |
| `before` | `JSONField` | `{"merchant_name": ..., "description": ...}` before the rule touched the row |
| `resolved_at` | `DateTimeField`, nullable | |

### 4.3 `RuleProposal`

| Field | Type | Notes |
|---|---|---|
| `signature` | `CharField(255)` | `unique_together = ["book", "signature"]`; see 9.6 |
| `field` | `payee` \| `description` | Which field the signature came from |
| `category` | FK → `accounts.Account`, `CASCADE` | |
| `evidence_count` | `PositiveIntegerField` | |
| `consistency` | `DecimalField(4, 3)` | |
| `status` | `open` \| `accepted` \| `dismissed` | A dismissed row is never re-proposed or re-offered |

## 5. Matching semantics

### 5.1 Conditions

| `field` | `op` | `value` |
|---|---|---|
| `payee` (reads `merchant_name`) | `contains`, `not_contains`, `equals` | string |
| `description` | `contains`, `not_contains`, `equals` | string |
| `amount` | `equals`, `gt`, `lt`, `between` | decimal string; `between` takes `[low, high]`, inclusive |

- Text comparison runs on `normalize()` of both sides (lowercase, punctuation collapsed to spaces).
  `contains` is substring on the normalized strings. A null `merchant_name` is the empty string.
- Amount conditions compare `abs(transaction.amount)`. Sign is expressed only through `direction`.

### 5.2 Rule selection

`engine.first_match(tx, rules)` returns the first active, valid rule in `(priority, id)` order whose direction,
accounts and conditions all hold. It is a pure function over in-memory objects: no queries.
The same function serves ingestion, Test rule, backtest and conflict detection.

### 5.3 Rows the engine never touches

Categorized rows; void rows; transfer mirrors (`is_transfer_mirror`); rows with `source` in
`manual`, `system`, `ynab`; revision-difference rows (`raw` carries `bank_revision.REVISION_OF`);
rows with a `RuleMatch` in status `dismissed`, `overridden` or `confirmed`.

## 6. Services (`apps/rules/services/`)

### 6.1 Prerequisite refactor: `apps/bank_feed/services/edit.py`

Move the per-row writes of `_apply_batch_edit` and the checks of `_batch_edit_refusal` out of the view into
`edit.py` (`apply_fields(tx, *, category=None, payee_name=None, description=None, target_account=None, new_date=None)`
and `refusal(...)`). `batch_edit` calls them; behaviour and its tests are unchanged. Rules call the same functions
with `category`, `payee_name`, `description` only. Do not add a second copy of this logic.

### 6.2 `engine.py`

`first_match` (5.2), `matches(tx, rule)`, and `explain(tx, rule)` returning per-condition pass/fail (for 9.8).

### 6.3 `apply.py::run(book, transactions, *, allow_auto_post=True)`

Takes `book` explicitly (called from Celery, where there is no request book context). Per eligible row, inside one
`transaction.atomic` with `select_for_update` on the row:

1. `rule = first_match(...)`. No match: delete any stale `suggested` `RuleMatch`, stop.
2. Record `before`. Apply `payee_name` / `description` renames immediately, in both modes (they are cosmetic and undoable).
3. If `rule.mode == auto_post` and `allow_auto_post` and no hold applies (6.4): write the category via
   `edit.apply_fields` (→ `categorize_single`) or the splits via `apply_splits` with percent legs converted to amounts
   (round each to cents; the last leg takes the remainder). Status `auto_posted`; bump `times_applied`.
4. Otherwise status `suggested` with `held_reason` set when a hold caused it. No journal entry is created.
5. Update `last_matched_at`.

A refusal raised by any guard (`PeriodLockedError`, `ReconciledLineError`, `SplitError`, `VoidRowError`, `ValueError`)
must never fail the sync: catch, store `suggested` with `held_reason="refused"`.

### 6.4 Auto-post holds

An `auto_post` match is stored as `suggested` when any of these is true:
- the row is in `feed_query.transfer_candidate_ids(book)` (`transfer_candidate`);
- `period_lock` refuses the row's date (`closed_period`);
- the anomaly guard fires (9.5) (`unusual_amount`);
- the rule's category is a feed account (cannot happen after validation; assert it anyway).

### 6.5 Triggers

| Event | Call |
|---|---|
| Plaid sync finishes a batch | `run(book, new rows)` once per sync, after all rows exist (transfer candidates need both legs) |
| CSV `upload_confirm` | `run(book, rows created without a mapped category)` |
| Rule created / edited / deleted / reordered / toggled | Delete `suggested` matches on uncategorized rows, then `run(book, all eligible rows, allow_auto_post=False)` |
| User confirms "Save and apply to N existing transactions" | `run(..., allow_auto_post=True)` restricted to that rule's matches |

Rule edits never auto-post retroactively without that explicit confirmation.
Not triggered by: manual rows, recurring materialization, YNAB import, portability import.

### 6.6 `feedback.py`

Called from every user categorization path on the feed (`categorize`, `update`, `batch_edit`, split save, categorize mode):

| Row's `RuleMatch` | User action | Result |
|---|---|---|
| `suggested` | Accepts unchanged (accept endpoint, or categorizes to the same category) | `confirmed`; `times_confirmed += 1`; `confirm_streak += 1` |
| `suggested` | Categorizes differently | `overridden`; `times_overridden += 1`; `confirm_streak = 0` |
| `suggested` | Dismisses | `dismissed`; `confirm_streak = 0` |
| `auto_posted` | Changes category, decategorizes, or undoes | `overridden`; `times_overridden += 1`; `confirm_streak = 0`; run demotion check (9.4) |

### 6.7 `undo.py`

Undo an `auto_posted` match: decategorize through the existing path, restore `before` fields, mark `overridden`.
Refusals from reconciled-line and period-lock guards surface as 409 with the guard's message.

## 7. API (DRF, `BookModelAccessPermissions`, under `/a/{team}/{book}/rules/api/`)

| Endpoint | Purpose |
|---|---|
| `rules/` list, create, retrieve, update, destroy | CRUD. Create inserts by specificity (9.3) unless `priority` is given |
| `POST rules/reorder/` `{ids: [...]}` | Rewrites priorities to the given order |
| `POST rules/test/` (unsaved rule body) | See 7.1 |
| `POST rules/{id}/apply/` | "Save and apply to N existing" (6.5) |
| `POST rules/draft_from_transaction/` `{transaction_id}` | Draft for create-from-action (9.1) |
| `POST rules/explain/` `{rule: {...}, transaction_id}` | Per-condition pass/fail (9.8) |
| `POST matches/accept/` `{transaction_ids: [...]}` | Accept suggestions (single, or "Accept all") |
| `POST matches/{transaction_id}/dismiss/` | |
| `POST matches/{transaction_id}/undo/` | |
| `proposals/` list; `POST proposals/{id}/dismiss/`; `POST proposals/{id}/accept/` | Learned rules (9.6). Accept returns a draft; the rule is created through `rules/` |

Feed API changes (`apps/bank_feed`):
- Feed row serializer gains `rule_match`: `{rule_id, rule_name, status, held_reason, category_id, category_name, is_split, payee_name}` or `null`. Avoid N+1 (`select_related`).
- `FeedParams` gains `rule=suggested|auto_posted`; `feed_query.counts` gains the two counts.

Regenerate `api-client/` per the CLAUDE.md recipe. No hand-written fetch calls.

### 7.1 `rules/test/` response

```
{
  "pending":  {"count": n, "rows": [first 50 uncategorized rows this rule would win]},
  "backtest": {"matched": n, "agree": n, "differ": n, "differ_rows": [first 20]},
  "conflicts": {
    "shadowed_by": [{"rule_id", "rule_name", "count"}],   // higher-priority rules taking this rule's matches
    "takes_from":  [{"rule_id", "rule_name", "count"}],   // lower-priority rules with a different action losing matches
    "dead": bool                                          // every match is taken by a higher-priority rule
  }
}
```

- `pending`: evaluated with the draft inserted at its priority among the saved rules.
- `backtest`: the draft alone against categorized, non-void, non-mirror rows from the last 24 months.
  `agree` = the row's actual single category equals the rule's category (split rows count as `differ` for a
  single-category rule).
- Conflicts are empirical (computed over the pending and backtest rows), not symbolic.

## 8. UI

React + DaisyUI, following `docs/frontend-guide.md` and `docs/design-document.md`. Reuse `common/Modal.jsx`,
`common/Combobox.jsx`, `SplitEditor.jsx`, and the field components of `BulkEditModal.jsx`.

### 8.1 Rules page (`/a/{team}/{book}/rules/`)

- Linked from the bank feed header and the book navigation.
- List in priority order: name, plain-language summary ("Money out · Chequing · description contains *insurance* → Car Insurance"),
  mode toggle, active toggle, stats (applied / confirmed / overridden), last matched.
- Drag to reorder (keyboard-accessible alternative required).
- "Needs attention" badge for invalid rules (4.1). "Demoted" badge with reason when `demoted_at` is set.
- "Proposed rules" tray at the top when open proposals exist (9.6).
- Empty state explains rules and points to create-from-action.

### 8.2 Rule builder (modal)

- Left: direction, accounts, match all/any, condition rows (add/remove).
- Right: action — category or split (percent), payee rename, description rename; mode (suggest / auto-post).
  Auto-post is disabled with an explanation when the category is a feed account.
- Bottom: live Test panel (debounced `rules/test/`): pending matches, backtest agreement line, conflict warnings.
  This is the "Test rule" feature; an explicit "Test rule" button forces a refresh.
- "Why didn't it match?": pick any transaction (search), show each condition with pass/fail (9.8).
- Saving an auto-post rule with pending matches asks: "Save" or "Save and apply to N existing transactions".

### 8.3 Bank feed and Categorize Mode

- `suggested` row: ghost category chip labelled with the rule name; Enter or one click accepts; a dismiss control.
  When `held_reason` is set, the chip states why ("Unusual amount for this rule").
- "Accept all N suggestions" action when the current view has suggested rows.
- `auto_posted` row: badge on the category cell. "Review auto-posted" filter (`rule=auto_posted`).
- Chip/badge popover: rule name, matched conditions, "Undo" (auto-posted only), "Edit rule".
- A row with a `rule_match` in `suggested` does not request or show history-based suggestions (decision 1).
  Rows without one keep today's behaviour.
- Overriding a rule's result shows a toast: "Update the rule" (opens builder) / "Just this once".

## 9. The nine improvements over QBO

1. **Create from action.** After a manual single-row categorization of a row with no rule match, call
   `draft_from_transaction`. Show a toast "Always categorize *X* as *Y*?" only if the draft's backtest plus pending
   count is ≥ 2 and no `RuleProposal` with that signature is `dismissed`. Dismissing the toast records one.
   Draft: direction from the amount's sign; if `merchant_name` is set, `payee contains normalize(merchant_name)`;
   otherwise `description contains` the normalized description with leading and trailing digit-only and
   `NOISE_TOKENS` tokens stripped. No account or amount condition. Mode `suggest`. `origin = from_action`.
2. **Backtest.** Section 7.1.
3. **Conflict detection and specificity ordering.** Section 7.1. On create without an explicit priority, insert above
   the first rule with a lower specificity score: `len(conditions) + (1 if accounts) + (1 if direction != any)`.
4. **Trust graduation.** When a `suggest` rule's `confirm_streak` reaches `GRADUATE_STREAK`, its category is not a feed
   account and `graduation_declined_at` is null, offer "Auto-post this from now on?". Declining sets the timestamp.
   When `DEMOTE_OVERRIDES` of a rule's last `DEMOTE_WINDOW` `auto_posted`-origin matches are `overridden`, set
   `mode = suggest`, set `demoted_at`, log an audit event, and show a notice on the rules page and the triggering toast.
5. **Anomaly guard.** For an `auto_post` rule with at least `ANOMALY_MIN_SAMPLES` matches in `confirmed` or
   `auto_posted`, hold when `abs(amount) > ANOMALY_MULTIPLE × median(abs(amount) of those matches)`.
   Computed by query from `RuleMatch` → transaction; no extra storage.
6. **Learned rules.** Nightly Celery task (register in `SCHEDULED_TASKS`), per book with categorizations in the last
   30 days. Group categorized single-category rows (same exclusions as `build_history_index`) by signature:
   `normalize(merchant_name)` when present, else the space-joined sorted `signature_tokens(description)`.
   Create or refresh an `open` `RuleProposal` when count ≥ `LEARN_MIN_COUNT`, top-category share ≥
   `LEARN_MIN_CONSISTENCY`, and no active rule already matches the group's most recent row. Never touch `dismissed`
   or `accepted` rows. Accepting opens the builder pre-filled (`origin = learned`, mode `suggest`).
7. **Explain and undo.** Popover in 8.3; `undo.py` in 6.7; override prompt in 8.3.
8. **Why didn't it match?** `rules/explain/`, builder UI in 8.2.
9. **Payee cleanup and percent splits.** `payee_name` / `description` actions (applied through `edit.apply_fields`,
   which get-or-creates the `Payee` as batch edit does); percent splits in 6.3.

## 10. Non-functional requirements

- **Isolation.** Every new URL added to the tables in `apps/books/tests/test_isolation.py`. Every query book-scoped.
  Rule serializers reject `category`, `accounts` and split categories from another book.
- **Write paths.** No direct `JournalLine` / `JournalEntry` writes in `apps/rules`. `NoBypassingWritesTest` and
  `LinesAreWrittenInOnePlaceTest` must stay green.
- **Performance.** Load a book's rules once per `run`. A 5,000-row Plaid backfill against 200 rules must not issue
  per-row rule queries. Feed list query count must not grow per row.
- **Sync safety.** No exception from the rules engine may fail or roll back a Plaid sync or CSV import.
- **Audit.** New `AuditEvent` types: `RULE_CREATED`, `RULE_UPDATED`, `RULE_DELETED`, `RULE_AUTO_POSTED`
  (one event per run, with rule ids and counts), `RULE_DEMOTED`.
- **Portability.** Add `Rule` to book export/import (`apps/portability`) or record it as a known gap in
  `CLAUDE.md` Known Issues. `RuleMatch` and `RuleProposal` are not exported.
- **i18n / a11y.** All strings translated; muted text `text-base-content/70`; dialog rules from CLAUDE.md Traps.
- **Imports.** Nothing heavy at module level in anything the URLconf or models import.

## 11. Phases and acceptance criteria

Each phase is independently shippable and ends with `make test` green, new `TestCase` classes with at least a
happy-path and a permission test per endpoint, and docs updated (section 12).

### Phase 1 — parity

Scope: 4.1, 4.2, section 5, 6.1–6.6, CRUD/reorder/test(pending only)/apply/accept/dismiss endpoints, feed serializer
and filter, 8.1, 8.2 (without backtest, conflicts, explain), 8.3 (without popover undo and override toast).

Accepted when:
- The example rule (money out, amount > 120, description contains "insurance" → Car Insurance) can be created in the UI.
- Its Test panel lists exactly the uncategorized feed rows it would win.
- With two matching rules, the lower `priority` value wins; reordering flips the result.
- In `suggest` mode a new Plaid/CSV row gets a suggestion chip and no journal entry; accepting creates the entry via `categorize_single`.
- In `auto_post` mode a new row is categorized on ingestion and carries the auto badge.
- A transfer-category rule cannot be saved as `auto_post`.
- A row in a closed period, a transfer candidate, a void row and a mirror row are never auto-posted.
- A row with a rule suggestion shows no history-based suggestion; a row without one still does.
- `batch_edit` behaviour is unchanged after the 6.1 extraction.

### Phase 2 — smarter authoring

Scope: 9.1, 9.2, 9.3, 9.7, 9.8, 9.9 (percent splits and renames if not already complete), 6.7.

Accepted when: backtest counts are correct against a fixture history; a dead rule and an overlapping rule each
produce the right warning; the create-from-action toast appears only under the 9.1 conditions and a dismissal is
remembered; undo restores category, payee and description and is refused on a reconciled or locked row;
explain reports the failing condition.

### Phase 3 — learning

Scope: 9.4, 9.5, 9.6, 4.3.

Accepted when: the fifth consecutive unchanged confirmation produces the offer and declining suppresses it for good;
two overrides in the last ten auto-posts demote the rule and log `RULE_DEMOTED`; an amount above 3× the median is
held with `unusual_amount`, and the guard is inactive below five samples; the nightly task proposes for a
4-of-4 consistent signature, does not for 3-of-4, and never resurrects a dismissed proposal.

## 12. Tests and docs

- Backend: `apps/rules/tests/` — engine (pure, table-driven over ops and edge cases: null payee, punctuation, sign,
  `between` bounds), apply, holds, feedback, undo, API permissions, isolation, learning task.
  Settings: `DJANGO_SETTINGS_MODULE=koala_budget.settings_test`.
- E2E (`e2e/`): page object for the rules page and builder; one flow per phase (create rule → import CSV → suggestion → accept;
  auto-post → undo; proposal → accept). Never run E2E and the Django test runner at once.
- Docs: append to `docs/feature-history.md`; update `docs/design-document.md`, `docs/testing-guide.md`,
  `docs/data-model.md`; add to `CLAUDE.md` only the single-writer lines
  ("Rule application: `apps/rules/services/apply.py::run` only", "feed field edits: `apps/bank_feed/services/edit.py`")
  and the `rules` row in the module table.

## 13. Out of scope

- LLM or ML classification.
- Rules for manual, recurring, YNAB-imported or portability-imported rows.
- Regex conditions; conditions on date, memo, Plaid category, or currency.
- Rule actions that move a row between accounts or change its date.
- Auto-posting transfers; transfer legs inside rule splits.
- Sharing rules across books.

## 14. Items for the implementer to verify before coding

- Where a Plaid sync batch ends in `apps/plaid/tasks.py`, so `run` is called once per sync and not per row;
  and that a pending row carried forward by `settle_pending` keeps its `RuleMatch`.
- How `bank_revision` amount changes interact with an auto-posted row (expected: unchanged existing behaviour;
  add a test).
- The exact book-navigation template that needs the Rules link.
- Whether `_decategorize` should move into `edit.py` alongside the 6.1 extraction (preferred) so `undo.py` does not call a view method.
