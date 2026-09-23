# Security Log

## Open Issues

(none)

## Resolved Issues

### 2026-09-23 — Statement reconciliation (`apps.reconciliation`)
**Feature:** Reconcile an asset/liability account against a bank or card statement; statements are recorded, can be undone, and report whether they still hold.
**Verdict:** No Critical or High findings.

- **Team scoping.** Every lookup of an account or statement is `filter(pk=..., team=request.team)`; another team's id is a 404. Ticking re-checks each line id against the draft's own candidate set (same team, same account), so a foreign line id is refused rather than linked (tests: `PermissionTests`).
- **Who may act.** Any authenticated team member (plan D8) — `TeamModelAccessPermissions.has_permission` runs on every action; object-level admin checks are not used because the viewset never calls `get_object()`. Every start/finish/undo writes an `AuditEvent`, and finishing writes an `AuditLog` row per line.
- **Integrity of confirmed data.** Reconciled lines are now guarded on every write path (`services/guards.py`); three of these returned HTTP 200 and silently changed reconciled state before this feature (plan §3).
- **Stale confirmations.** An adjustment is only posted when the client names the difference it showed the user and the server's recomputed figure matches (else 409), so a concurrent edit cannot turn one confirmation into a different posting.
- **Input.** Amounts are DRF `DecimalField`s (2 dp); line-id lists are capped at 5,000; no raw SQL.

**Accepted, low:** the workspace loads every candidate line for the account (not paginated). A first reconciliation of years of unreconciled history can be thousands of rows; "Tick all through" is server-side, so no request carries them all.

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
