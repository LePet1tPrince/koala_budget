# Security Log

## Open Issues

(none)

## Resolved Issues

### 2026-06-04 — Account Type Filter Persistence (return_type param)
**Feature:** Persist `?type=` filter across account detail/edit/delete navigation.
**Reviewed by:** Agent 05 (Security Reviewer)
**Verdict:** Approved — no Critical or High findings.

**SEC-001 (Low):** `return_type` query parameter is accepted and reflected without server-side whitelist validation against `ACCOUNT_TYPE_CHOICES`. Django auto-escaping prevents XSS in all templates; the value is only appended as a `?type=` query param to an internal hard-coded URL (no open redirect). Functional impact is limited to an unrecognised filter value returning an empty or unfiltered account list. Recommend adding a whitelist check in `AccountDetailView`, `AccountUpdateView`, and `AccountDeleteView` `get_context_data` / `get_success_url` as a defence-in-depth measure.

All other checklist items passed: no open redirect, no XSS, no SQL injection, no CSRF gap, no hardcoded secrets, no PII in URLs, all views protected by `LoginAndTeamRequiredMixin`.

## Recurring Patterns to Watch

- **Unvalidated pass-through query parameters:** This feature introduced `return_type` as a reflected query param with no whitelist check. If this pattern is reused in other views (e.g. `return_url`, `next`, `redirect_to`), open-redirect or XSS risk increases substantially. Any future parameter that influences redirect targets must be validated against an allowlist.
