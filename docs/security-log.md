# Security Log

## Open Issues

(none)

## Resolved Issues

### 2026-09-19 — YNAB import (`apps.ynab_import`)
**Feature:** Import a YNAB export (two CSVs) into an empty team: chart of accounts, full transaction history, budgets, goals and opening balances.
**Verdict:** No Critical or High findings.

Checked, and what the design does about it:

- **Uploads.** Both files are parsed with the stdlib `csv` module — no `eval`, no shell, no spreadsheet macro surface — and refused above `MAX_UPLOAD_BYTES` (20 MB). Only the first four files in a request are read, so a multipart flood cannot pull an unbounded number of file bodies into memory.
- **Stored financial data.** The exports are held as text on `YnabImport` so the Celery worker reads the same bytes the browser sent, and **cleared on success** (`register_csv`/`plan_csv` set to `""`): a user's entire financial history does not sit in a staging table after it has been imported into the ledger. A failed import keeps them so the user can retry; they go with the row.
- **Team scoping.** Every endpoint is `@login_and_team_required`, and every lookup of an import is `filter(team=request.team, id=...)` — never by id alone. A cross-team id returns 404 (test: `TeamScopingTest`).
- **Client input is a set of *choices*, not a chart of accounts.** `parse_choices` reads the payload over server-computed defaults and drops anything the export does not contain; an account type outside `asset`/`liability`, a category kind outside the three known ones, or a payee the analysis never saw all fall back rather than being accepted. `is_system` cannot be client-set, and an account cannot be smuggled into the system equity group.
- **Idempotency.** `apply_plan` refuses a team with any non-void `JournalEntry`, inside the same transaction that would write, and the Celery task refuses an import that is not in the `uploaded` state — two clicks, or two workers, cannot write the history twice.
- **Audit.** `AuditEvent.YNAB_IMPORT_STARTED` on upload and `AuditEvent.YNAB_IMPORT` on completion, the latter recording what was written and every inference the user accepted. Row-level `AuditLog` entries are deliberately skipped (`bulk_create`), which is noted at the call site and in the testing guide.

**Accepted, low:** an import holds one team's export in memory while it runs (~1.4 MB for the sample). Concurrency is bounded by the Celery worker pool rather than by the app.

### 2026-06-04 — Account Type Filter Persistence (return_type param)
**Feature:** Persist `?type=` filter across account detail/edit/delete navigation.
**Reviewed by:** Agent 05 (Security Reviewer)
**Verdict:** Approved — no Critical or High findings.

**SEC-001 (Low):** `return_type` query parameter is accepted and reflected without server-side whitelist validation against `ACCOUNT_TYPE_CHOICES`. Django auto-escaping prevents XSS in all templates; the value is only appended as a `?type=` query param to an internal hard-coded URL (no open redirect). Functional impact is limited to an unrecognised filter value returning an empty or unfiltered account list. Recommend adding a whitelist check in `AccountDetailView`, `AccountUpdateView`, and `AccountDeleteView` `get_context_data` / `get_success_url` as a defence-in-depth measure.

All other checklist items passed: no open redirect, no XSS, no SQL injection, no CSRF gap, no hardcoded secrets, no PII in URLs, all views protected by `LoginAndTeamRequiredMixin`.

## Recurring Patterns to Watch

- **Unvalidated pass-through query parameters:** This feature introduced `return_type` as a reflected query param with no whitelist check. If this pattern is reused in other views (e.g. `return_url`, `next`, `redirect_to`), open-redirect or XSS risk increases substantially. Any future parameter that influences redirect targets must be validated against an allowlist.

### 2026-09-23 — Editable transactions on the Transactions page
**Feature:** Edit, split, delete and void a journal entry from `/a/{slug}/journal/transactions/`.
**Verdict:** No Critical or High findings. One accepted Medium, recorded below.

Checked, and what the design does about it:

- **Team scoping.** Every write loads its entries through `TransactionViewSet.editable_queryset()`, which is `JournalEntry.for_team` — never a lookup by id alone. An id the team cannot see refuses the *whole* batch rather than being skipped, so a request cannot be used to probe which ids exist by watching which ones "worked" (`test_another_teams_id_is_refused_not_edited`).
- **Account references.** `account_id`, `category_id` and every split leg's category are resolved with an explicit `Account.objects.filter(team=team, ...)`, not through the ambient `for_team` manager. Another team's account reads as *"That category no longer exists."* — the same message a deleted one gets — rather than a refusal that confirms it exists.
- **Client input is a partial edit, not a ledger.** The client never sends debit and credit amounts. It sends a signed total and, optionally, legs; `apps.bank_feed.services.splits.write_lines` decides which side each amount lands on and refuses to write an entry that does not balance. So a crafted payload cannot produce an unbalanced entry, and cannot set `is_reconciled`, `is_cleared`, `budget` or `source` at all — none is in the request serializer.
- **Destructive actions are asked for, never inferred.** Collapsing a split requires `remove_split`; deleting requires the id list; voiding requires an explicit status. A payload that merely omits `splits` is refused rather than being read as "drop the apportionment".
- **Reconciled data.** Amount and account changes, and deletion, are refused while the home line is reconciled — enforced in the service, not just hidden in the modal, and the modal's capability flags are computed from the same predicates so the two cannot disagree.
- **Audit.** Lines are mutated in place rather than deleted and recreated, so the row-level `AuditLog` records a field diff a reader can follow; a multi-row edit also writes one `AuditEvent.BULK_EDIT` with the fields touched.

**SEC-001 (Medium, accepted):** `TeamModelAccessPermissions.has_object_permission` — which restricts writes to team admins — is only consulted by DRF on *detail* routes. `transactions/edit/`, `transactions/batch_delete/` and `transactions/batch_status/` are list-shaped actions, so they fall through to `has_permission`, which admits any authenticated team member. This matches `BankFeedViewSet.batch_edit`, `batch_archive` and `batch_delete`, which have behaved this way since the feed shipped, so it is the app's existing posture rather than a new gap — a member who can already recategorize in the Bank Feed can now do the same here. Worth revisiting as one decision across both apps: if transaction writes should be admin-only, the check belongs in a shared permission class, not bolted onto one viewset.
