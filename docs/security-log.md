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
