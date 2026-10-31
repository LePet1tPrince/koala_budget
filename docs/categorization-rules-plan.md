# Auto-categorization rules, and a slot for AI — plan

**Status: built.** §13 lists where the build differs from the plan below.

A rule says "a bank transaction that looks like *this* is *that*", and either
files it the moment it arrives (`auto`) or offers it as the top suggestion in
categorize mode (`suggest`). Rules are the first of an ordered list of
**categorization providers**; history (`similar_transactions`) is the second,
and an AI provider can be appended later without touching anything else. This
plan builds the rules feature and the provider seam. **It does not build the
LLM call** — §10 is the guide for whoever does.

## 1. Current state

| Piece | Location | Behaviour |
|---|---|---|
| History suggestions | `apps/bank_feed/services/similar_transactions.py` | Three tiers (payee / description / token-set Jaccard ≥ 0.6) over the book's last 2,000 categorized rows. Suggests; never writes. |
| Endpoint | `GET bankfeed/api/feed/similar_categories/?ids=…` | Flat list `{transaction_id, category_id, category_name, count, match_type, payee}`, ranked per transaction. ≤ 50 ids. |
| Categorize mode | `CategorizeMode.jsx` | Prefetches suggestions for the next 8 cards; merges them with a client-side "account named in the memo" check (`findAccountNamedInText`), named match first. |
| Write path | `apps/bank_feed/services/categorize.py` | `categorize_single` / `create_entry` / `repoint_category` — guards, `sync_transfer`, the audit signals. |
| Arrival | `apps/plaid/tasks.py::_sync_item`, `csv_upload.create_transactions` | Rows land uncategorized (CSV may carry an explicit `category_id` from the Map Categories step). |

The gap: a suggestion is a prompt, not a decision. A user who has filed
"BLUE BOTTLE" as Coffee forty times still confirms it the forty-first time.
And upcoming business features add two more decisions per transaction
(business vs personal, a sales-tax code), so whatever replaces the prompt has
to carry *decisions*, not just a category.

## 2. Where the code lives

A new app, **`apps.categorization`** (label `categorization`), rather than
more modules in `apps/bank_feed/services/`:

- it owns two models, its own URLs, page, API, migrations and portability
  file — enough to be an app;
- it keeps edits to the files other work is changing (`categorize.py`,
  `csv_upload.py`, `bank_feed/views.py`) to a few lines each: arrival hooks are
  one call, and the write path is *called*, never edited.

URLs mount at `/a/{team}/{book}/bankfeed/rules/` (namespace `categorization`)
so the address reads as part of the Inbox; the page renders inside the
Settings shell under **This book → Categorization rules**, like the audit log.

```
apps/categorization/
  models.py        CategorizationRule, CategorizationDecision
  matching.py      pure: does a rule match a row? (reuses similar_transactions' normalize / signature_tokens)
  actions.py       the action registry: category, payee rename, description rename (room for more)
  providers/
    base.py        Suggestion, ProviderContext, CategorizationProvider protocol
    rules.py       RuleProvider
    history.py     HistoryProvider (wraps similar_transactions)
    ai.py          AIProvider stub (returns nothing) — the owner's
  pipeline.py      provider registry, merge/dedupe, suggest(), auto_categorize()
  policy.py        may_auto_apply(): when a suggestion may file a row by itself
  apply.py         writes: one row through categorize.py, decisions, audit, preview/apply-to-existing
  serializers.py, views.py, urls.py, admin.py
```

## 3. The rule model

`CategorizationRule(BaseBookModel)`, `unique_together = ["book", "name"]`,
`for_book` manager, ordering `("priority", "id")`.

**Conditions** (ANDed; at least one of payee, description or amount is set, so
no rule matches everything):

| Field | Meaning |
|---|---|
| `payee_match` + `payee_value` | against the row's `merchant_name`. `""` = any. |
| `description_match` + `description_value` | against the row's `description`. |
| `amount_min`, `amount_max` | on the **magnitude**; equal = exact; either may be blank (open range). |
| `direction` | `any` / `outflow` (amount > 0, Plaid convention) / `inflow`. |
| `account` | optional feed account the row must be in (`CASCADE`: a rule scoped to a deleted account means nothing). |

Match kinds, all over the **same normaliser and tokeniser as history**
(`similar_transactions.normalize`, `signature_tokens`) — no second notion of
"the same text":

- `equals` — `normalize(row) == normalize(value)`; "Blue Bottle Coffee" equals "BLUE-BOTTLE coffee".
- `contains` — the normalized value appears in the normalized text **on word
  boundaries** ("bottle" matches "sq blue bottle 4417", "bot" does not).
- `words` — every meaningful word of the value (digits, < 3 letters and bank
  boilerplate dropped) is among the row's meaningful words. This is the kind a
  rule made from a card defaults to when the payee is blank, because it ignores
  the terminal number that changes every time — `SQ *BLUE BOTTLE 4417` makes a
  rule matching `SQ *BLUE BOTTLE 9920`.

**Actions**: `category` (FK `Account`, `SET_NULL` — see §5), `set_payee`,
`set_description` (blank = leave alone).

**Behaviour**: `mode` = `auto` | `suggest` (default `auto` — the affordance
that creates most rules says "Always…"), `is_enabled`, `priority` (lower runs
first; the list page reorders it).

`is_archived` / `archived_at` from `BaseModel` are removed (`= None`), as on
`BankTransaction`: `is_enabled` is the one "off" switch.

**Room for more decisions.** `actions.py` is a registry of `RuleAction`s, each
owning its columns, how it's validated, how it's applied to a row before/after
the category is filed, and how it's described. A business flag or a tax code is
a new nullable column plus one registered action; the matcher, pipeline,
serializer loop and UI summary don't change. `Suggestion.decisions` (§8) is the
provider-side twin: a dict a provider may fill with future decisions
(`{"is_business": True, "tax_code": "GST"}`) that nothing reads yet.

**Ordering semantics: first match wins.** Rules are checked top to bottom and
the highest-priority enabled rule that matches *is* the rule for that row. A
`suggest` rule above an `auto` rule therefore stops the auto rule — that is the
point of putting it above.

## 4. Where rules apply

| Trigger | When | Which rows |
|---|---|---|
| Plaid sync | after `_sync_item`'s atomic block commits | rows created by this sync, still uncategorized |
| CSV upload | end of `create_transactions` | rows created uncategorized (a row the user mapped to a category in the wizard keeps that choice) |
| Apply to existing | the rule page's **Apply** button, after a preview count | uncategorized rows this rule matches (whatever its mode or priority — the user asked for this rule) |

**Never touched:** a row with a journal entry (categorized, split or a
transfer's either leg), a void row, a transfer mirror, or a row whose category
would be its own account. An uncategorized row cannot be reconciled (it has no
lines); the check is still made through the write path's guards.

**Arrival never aborts the sync.** Rule application runs *after* the sync's
rows and cursor commit, each row in its own savepoint; a refusal from the
write path (any `ValueError` — the reconciliation guard, a void row, a future
period lock) is caught per row, counted and logged, and the row stays in the
Inbox. The whole arrival hook is additionally wrapped so even an unexpected
exception is logged rather than re-raised into Celery's retry loop.

## 5. Write path and targets

One row is filed by `apply.apply_to_row(row, suggestion)`:

1. actions that run **before** filing (payee / description rename) set
   `merchant_name` / `description` on the row and save it — so `create_entry`
   copies the new description onto the entry and `sync_transfer` copies both
   onto a mirror;
2. `categorize.categorize_single(row, category)` — the only call that writes
   lines; guards, mirror creation and the audit signals all apply;
3. actions that run **after** filing (payee: `JournalEntry.payee`, as
   `batch_edit` does);
4. a `CategorizationDecision` is written (§6).

`assert_category_allowed` runs at rule save *and* again per row.

**A rule whose category is gone or unusable** is never silently retargeted:

| Category state | At save | At apply |
|---|---|---|
| deleted | — | `category` is `SET_NULL`; the rule stays, flagged "Its category was deleted", and matches nothing until edited |
| archived | refused | skipped, flagged "… is archived" on the rules page |
| budget bucket | refused (`assert_category_allowed`) | refused per row by the same guard |
| hidden (`is_hidden`) | allowed | **applies** — hidden is a display choice, and the rule is an explicit one |
| the rule's own account | refused (a transfer to itself) | a row in that account is skipped |

A flagged rule shows a warning badge on the rules page and is excluded from
the providers (`CategorizationRule.objects.usable()`).

## 6. Traceability

`CategorizationDecision(BaseBookModel)` — one per bank row (one-to-one):
`bank_transaction`, `journal_entry` (`CASCADE`: removing the category removes
the decision), `category`, `source` (`rule` | `history` | `ai`), `provider`
(the provider key), `rule` (`SET_NULL`), `confidence`, `reason`, and the
`original_payee` / `original_description` the bank sent before any rename.

**"Still stands" is derived, not maintained.** A decision is shown only while
the row is still on that entry *and* still in that category. Re-categorizing by
hand needs no hook in any write path: the category no longer agrees, so the
"Rule" badge disappears. That is the undo story — fix the row, the badge goes.

Surfaces:

- **Feed table** — a small `Rule` badge (or `AI`) beside the category, with a
  tooltip naming the rule and the reason (`categorized_by` on the feed row).
- **History tab** — every automatic application writes one
  `AuditEvent.AUTO_CATEGORIZED` per rule (metadata: `source`, `provider`,
  `rule_id`, `rule_name`, `trigger`, `count`, `transaction_ids` (capped),
  `via`), and the `AuditLog` rows the write created are linked to it
  (`AuditLog.event`, an existing, unused FK). `AuditLogSerializer` gains `via`
  (the event's `metadata.via`), shown after the actor: *"System · via rule
  “Coffee”"*.
- **Audit log** — the event itself, plus `CATEGORIZATION_RULE_CHANGED`
  (`{action: created|updated|deleted|reordered, rule_id, name}`).

## 7. Creating and managing rules

- **Categorize mode**: after a card is filed (and no rule already decided it),
  an offer appears above the stack — *"Always categorize ‘Blue Bottle’ as
  Coffee? Create rule"* — opening the shared rule editor prefilled from the card
  (`GET rules/api/rules/draft/?transaction=&category=`).
- **Bank feed edit modal**: a **Create rule…** button opens the same editor,
  prefilled from the row and the modal's current category.
- **Rules page** (`/bankfeed/rules/`): list in priority order with each rule's
  conditions, action, mode, enabled toggle, "applied to N" (decisions that
  still stand), flags; drag/arrow reorder; edit; delete; **Test** (how many
  uncategorized rows it would file now, a sample, and how many already-filed
  rows it matches and how many of those agree with it); **Apply** (after the
  preview). Linked from the Inbox toolbar and the Settings rail.

The editor previews live (debounced, newest-response-wins) against the
**unsaved** conditions, and on save can apply the rule to the matching
uncategorized rows in the same step.

Only book admins write rules (`BookModelAccessPermissions` reads for members,
writes for admins; create/reorder/preview/apply are admin-checked too) — a rule
changes what happens to every future transaction in the book. Members see the
page read-only and the offers are hidden from them.

## 8. The provider seam

```python
@dataclass
class Suggestion:
    category_id: int
    source: str                 # "rule" | "history" | "ai" -- recorded on the decision
    provider: str               # the provider's key
    confidence: float           # 0..1
    reason: str                 # one sentence, user-facing
    auto: bool = False          # the provider asks to file the row itself
    rule_id: int | None = None
    count: int | None = None    # history evidence, for the UI's "N×"
    match_type: str = ""        # the UI contract: payee|description|similar|rule|ai
    payee: str = ""
    decisions: dict = {}        # future per-row decisions (business flag, tax code)

class CategorizationProvider(Protocol):
    key: str                    # "rules", "history", "ai"
    source: str
    can_auto_apply: bool        # may this provider's results ever file a row?
    def suggest(self, context: ProviderContext, rows: Sequence[BankTransaction]) -> dict[int, list[Suggestion]]: ...
```

`ProviderContext` hands every provider the book and, lazily, the book's
pickable categories in `picker_accounts_data()` shape (the same list the
pickers show), plus `allowed_category_ids`.

**Registry**: `settings.CATEGORIZATION_PROVIDERS`, an ordered list of dotted
paths, default `[RuleProvider, HistoryProvider]`. `pipeline.get_providers()`
imports and instantiates them (cached per process; tests override the setting).

**Merge**: per row, providers' lists are concatenated in registry order and
deduped by `category_id` — the earlier provider keeps the position, and a
later provider's evidence for the same category is folded in (a rule
suggestion picks up history's `count`). Then everything is filtered through
the pickable set (no budget buckets, archived accounts or the row's own
account). The client keeps its own "named in the memo" check and slots it
**after** a rule suggestion and before history.

**Policy** (`policy.may_auto_apply(book, provider, suggestion)`):

1. a suggestion from a provider with `can_auto_apply = False` never files a row;
2. a **rule** files a row when `suggestion.auto` (its mode is `auto`);
3. any other provider files a row only when `book_allows_auto(book, provider)`
   *and* `suggestion.confidence ≥ CATEGORIZATION_AUTO_MIN_CONFIDENCE` (0.9).
   `book_allows_auto` is the hook for a future, explicit per-book setting; it
   returns **False** today, so history and AI only ever suggest.

On arrival only providers that *could* auto-apply for this book are run, so a
sync never pays for a history index (or an LLM call) whose result could only
be a suggestion nobody is looking at.

**Endpoint**: `similar_categories` keeps its URL and shape and now returns the
merged pipeline. Existing fields are unchanged (`count` becomes nullable — a
rule with no history behind it has none); new fields `source`, `provider`,
`confidence`, `reason`, `rule_id`, `rule_name`, `auto`; `match_type` gains
`rule` and `ai`.

## 9. Portability — format v8

Rules are user data and travel: **`rules.csv`**, one row per rule
(conditions, actions, mode, enabled, priority; account and category by the
archive's account ids, remapped on import). `FILES_ADDED_IN[rules.csv] = 8`,
`upgrade_7_to_8` gives an older archive an empty list; the reader checks every
`account_id`/`category_id` names an account in `accounts.csv`.

`CategorizationDecision` is a **documented omission**
(`schema.UNEXPORTED_MODELS`, with a test that every model in this app is either
mapped or listed): it is provenance about how a row was filed in *this* book,
like `AuditEvent`, and the category it records travels on the row itself.
After an import the rows read as filed by hand.

`wipe_book` deletes decisions and rules before the raw delete of entries (a
raw `DELETE` does not cascade, so the decision's FK would otherwise block it).

## 10. Adding an AI provider

**The class.** Implement `apps.categorization.providers.ai.AIProvider` (the
stub is already there and returns nothing), or write your own class with the
same four attributes:

```python
class AIProvider:
    key = "ai"
    source = SOURCE_AI          # "ai" — the value recorded on every decision it makes
    can_auto_apply = True       # still gated by the per-book setting, see below

    def suggest(self, context, rows):
        ...
        return {row.id: [Suggestion(category_id=…, source=self.source, provider=self.key,
                                    confidence=0.93, reason="Looks like a coffee shop",
                                    match_type="ai")]}
```

**Register it.** Append its dotted path to `CATEGORIZATION_PROVIDERS` in
`koala_budget/settings.py` (after rules and history, so a rule always outranks
it). Nothing else is wired by hand: the endpoint, categorize mode and arrival
all read the registry.

**What it receives.** `context.book`; `context.categories` — the pickable
categories as dicts (`id`, `name`, `account_type`, `account_group_name`,
`is_goal`, `goal_left`, `is_hidden`, `institution_name`, …, exactly what the
pickers show); `context.allowed_category_ids`; and `rows`, a list of
uncategorized `BankTransaction`s (`id`, `description`, `merchant_name`,
`amount` — positive = money out — `posted_date`, `account`). Batches are small
(categorize mode asks for ≤ 8 at a time, the endpoint caps at 50).

**What it must return.** `{row_id: [Suggestion, …]}`, strongest first, rows
with nothing omitted. `category_id` must be in `context.allowed_category_ids`
— anything else is dropped by the pipeline anyway. `reason` is shown to the
user under the suggestion and stored on the decision. `confidence` in 0..1.
Leave `rule_id` empty. `decisions` is where a future business flag or tax code
goes.

**Rules that still apply.** Whatever the provider says, the pipeline filters
out non-pickable categories; the write path (`categorize_single`) runs every
guard (`assert_category_allowed`, reconciliation, void, period locks); and
`policy.may_auto_apply` keeps AI suggest-only until `book_allows_auto(book,
provider)` returns True — the hook for a per-book "let AI file transactions"
setting, which should be an explicit opt-in with its own threshold. An AI that
files a row records `source="ai"`, its `reason` and `confidence` on the
decision, a feed-table **AI** badge, and an `AUTO_CATEGORIZED` audit event
with `source: "ai"`.

**Do not** touch `apps/ai` or `apps/chat` for this (their future is decided
separately); the provider may *call into* a client you build, but the seam is
this one class.

**How to test it.** `apps/categorization/tests/doubles.py::FakeAIProvider`
returns canned suggestions and records what it was asked. Override the setting:

```python
@override_settings(CATEGORIZATION_PROVIDERS=[*DEFAULT_PROVIDERS, "apps.categorization.tests.doubles.FakeAIProvider"])
```

and call `pipeline.suggest(book, rows)` / `pipeline.auto_categorize(book, rows,
trigger=…)`; `test_pipeline.py` shows the merge order, the drop of a
non-pickable category, and that an AI suggestion never files a row until
`book_allows_auto` is patched to True. Mock the model call itself; never call
a real LLM in a test.

## 11. Tests

- `test_matching.py` — every match kind, normalization, word boundaries,
  amount exact/range/open, direction, account, the at-least-one-condition rule.
- `test_rules_apply.py` — priority/first-match, skip rules (categorized, void,
  mirror, split, own account), payee/description rename, transfer target
  creates the mirror, guard refusal handled per row, decisions, badge "still
  stands", audit event + `AuditLog.event` link.
- `test_arrival.py` — Plaid sync (`apps.plaid.services.*` mocked) and CSV
  upload apply auto rules, ignore suggest rules, and a refusal doesn't fail the sync.
- `test_pipeline.py` — merge order, dedupe, pickable filter, policy with the
  AI test double, the endpoint contract.
- `test_api.py` — CRUD, validation, reorder, preview, apply, draft,
  permissions (member read-only), cross-book.
- isolation tables, `BOOK_MODELS`, portability round trip + upgrade, `wipe_book`
  against a sibling book.
- E2E (`e2e/tests/test_categorization_rules.py`, POM `e2e/pages/rules.py`).

## 12. Decided against

- **Rules as a JSON blob of conditions/actions.** Queryable columns, a real
  form, a portable CSV and a schema test that sees every field beat the
  flexibility; growth goes through the action registry instead.
- **Storing the decision on `BankTransaction`.** Every hand-categorizing path
  would have to clear it, in files other work is rewriting. A separate row whose
  validity is derived needs no hooks.
- **Re-running rules on edit.** A rule decides once, on arrival or when asked.
  Editing a categorized row never re-runs anything.
- **Falling through a matching `suggest` rule to a lower `auto` rule.** First
  match wins; otherwise "suggest" would mean "unless something else says auto".

## 13. As built

- Everything in §§2–11 shipped as described.
- The rule page reorders with up/down buttons (keyboard-reachable, no new drag
  dependency); the accounts board's @dnd-kit was not pulled in for a list.
- "Apply all rules to the Inbox" (a page-level button) was not built: per-rule
  Apply covers it with a preview, and an all-rules run's preview would be a
  table of rules, not a count.
- `api-client/`: hand-patched to the generator's conventions (no generator jar
  in this environment): `BankFeedRow.categorizedBy`, the widened
  `SimilarCategorySuggestion`, and `AuditLog.via`. The rules API is called
  through `common/http.js`, like the other hand-written page APIs.
