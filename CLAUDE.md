# Koala Budget — Claude Code Context

## Architecture

**Stack:** Django 6 (Python 3.12) backend · Django REST Framework · PostgreSQL 17 · Celery + Redis · React 19 + Alpine.js frontend · Tailwind CSS 4 + DaisyUI 5 · Vite 7 · TypeScript 5 · Playwright E2E tests

**Folder layout:**
```
apps/              # 19 Django apps (accounts, journal, budget, bank_feed, plaid, chat, ai, teams, users, …)
assets/javascript/ # React/Alpine.js components embedded in Django templates
frontend/          # Standalone React SPA (auth flows only)
templates/         # Django server-rendered templates
api-client/        # Auto-generated TypeScript API client (from OpenAPI schema)
e2e/               # Playwright + pytest E2E tests (Page Object Model)
docs/              # Developer documentation
context/           # context/CLAUDE.md — detailed LLM reference guide
deploy/            # Docker Compose and DigitalOcean configs
```

**Key modules:**
| App | Responsibility |
|-----|---------------|
| `accounts` | Chart of accounts — Account, AccountGroup, Payee, Institution |
| `journal` | Double-entry bookkeeping — JournalEntry, JournalLine |
| `budget` | Monthly budgets and savings goals — Budget, Goal, GoalAllocation |
| `bank_feed` | Transaction import staging — BankTransaction |
| `plaid` | Plaid live-sync integration — PlaidItem, PlaidAccount |
| `chat` / `ai` | AI chat interface and pydantic-ai agents |
| `teams` | Multi-tenancy — Team, Membership, Invitation |
| `users` | Custom user model, avatars, preferences |
| `api` | API key auth — UserAPIKey, hybrid permissions |
| `subscriptions` | Stripe billing via dj-stripe |
| `reports` | Income statements, balance sheets, Sankey diagrams |

**Account number convention:** 1000s = assets · 2000s = liabilities · 3000s = equity/goals · 4000s = income · 5000s = expenses

**URL pattern:** `/a/{team_slug}/{app}/{path}/`

---

## Conventions

**Python:**
- Double quotes, 4-space indent, 120-char line limit (Ruff enforced)
- All financial models extend `BaseTeamModel`
- Custom querysets for complex queries (e.g. `GoalQuerySet.with_progress()`)
- Team-scoped manager: `Model.for_team.all()` auto-filters by current team
- Views use `@login_and_team_required` or `@team_admin_required`
- DRF ViewSets with `TeamModelAccessPermissions` for API endpoints
- `unique_together = ["team", "field"]` on team-scoped unique fields
- Amounts: `Decimal(max_digits=15, decimal_places=2)`, positive = outflow

**TypeScript/React:**
- 2-space indent, single quotes, semicolons
- Functional components with hooks
- Auto-generated API client from OpenAPI schema — never hand-write fetch calls
- Components self-mount via `document.getElementById('id').render(<Component />)`
- Props passed via `window.COMPONENT_PROPS` JavaScript variable

**Django templates:**
- 2-space indent
- Always use `{% translate %}` or `{% blocktranslate trimmed %}`
- Vite assets via `{% vite_asset 'path/to/asset.tsx' %}`

**Testing:**
- Backend: Django `TestCase` with `setUpTestData()` class fixtures
- E2E: Playwright POM pattern — page objects in `e2e/pages/`, tests in `e2e/tests/`
- Run: `make test` (backend) · `make test-e2e` (E2E)
- Coverage threshold: 50% minimum

---

## Recent Changes

- Initial project setup: Django + React + Tailwind + Plaid + Stripe multi-tenant budget app
- Double-entry journal with debit/credit balance enforcement
- Goal savings system with auto-created equity accounts
- Plaid live bank feed integration with incremental sync
- AI chat interface with pydantic-ai + LiteLLM multi-backend
- CSV bank import as fallback to Plaid
- dj-stripe subscription billing
- Playwright E2E test suite with Page Object Model
- Accounts: persist `?type=` filter across account detail/edit/delete navigation via `return_type` query param
- Security: `TeamAccessPermissions`/`TeamModelAccessPermissions` now enforce authenticated team membership at the view level (`has_permission`), closing anonymous/cross-tenant access to list/create/custom actions
- Correctness: voided journal entries are excluded from all balances, budget actuals, net worth, and reports; bank feed account moves no longer unbalance journal entries; re-categorizing keeps a single journal entry per bank transaction
- Frontend: timezone-safe date handling for transaction dates (no more off-by-one-day saves/displays across timezones)
- Bank feed: real DRF pagination on the feed list (page size 200; frontend follows `next` pages)
- Bank feed: payee autocomplete (from team payees) and category suggestions (most recent category per merchant via `category_suggestions` endpoint) in the edit/bulk-edit modals
- Plaid: `last_synced_at` on PlaidItem with "last synced" indicator in the bank feed UI; global webhook receiver at `/plaid/webhook/` queues incremental syncs on `SYNC_UPDATES_AVAILABLE`
- Budget: amounts auto-save on change (no per-row Save button; `<noscript>` fallback); Budget rows created lazily on first save instead of on GET
- UI: shared `currency` template filter (`{% load currency_tags %}`) replaces hardcoded `$…|floatformat:2`; loading skeletons on the Transactions and Bank Feed React mounts
- CSV upload "Map Categories" step: responsive multi-column card grid; each card shows per-category inflow/outflow totals + transaction count; category dropdown renders in a body portal (fixed-positioned, no longer clipped by the modal) and notes an account's institution when set; deterministic `suggest_account_for_category()` (in `apps/bank_feed/services/csv_upload.py`) pre-fills a best-guess account (flagged "Suggested — please verify", direction-aware so a bare "Interest" resolves to income vs expense by net cash flow). `SimpleAccountSerializer` now exposes `institution_name`
- UX: style audit + layout redesign (see `docs/style-audit.md`). Team home is now a real dashboard (net worth hero, review banner, budget/goals snapshot, recent activity, onboarding checklist for new teams). Nav restructured: Home → Inbox (Bank Feed, with uncategorized-count badge via `apps.bank_feed.context_processors.inbox_count`) → Transactions → Budget → Goals → Reports, with chart-of-accounts admin under a Settings group. Accounts home is a grouped account list with balances + tab row to Groups/Payees/Institutions (`accounts/components/manage_tabs.html`); Reports home is a simple link list. Breadcrumbs removed from app pages; Pegasus demo links (Examples Gallery, Example App, Subscription Demo) removed from nav; mobile bottom dock added in `app_base.html`
- Audit: new `apps.audit` app provides a two-track audit trail. `AuditLog` records row-level field diffs for `JournalEntry`/`JournalLine` via `pre_save`/`post_save`/`post_delete` signals (`apps/audit/signals.py`), with `journal_entry_id` denormalized for fast history lookups and frozen FK snapshots (`{id, name}`) so renames don't rewrite history. `AuditEvent` records operation-level events (logins, CSV uploads, Plaid syncs, bulk feed ops) via `log_event()` in `apps/audit/utils.py`. Both are plain `models.Model` (nullable team) — not `BaseTeamModel`. The request user is propagated to signals through thread-local storage set by `AuditUserMiddleware` (after `AuthenticationMiddleware`). Read-only API at `/a/{slug}/audit/api/events/` (team-scoped, `TeamModelAccessPermissions`) plus a per-entry history action `GET /a/{slug}/journal/api/journal-entries/{id}/audit/`. Frontend: the bank-feed edit modal (`assets/javascript/bank_feed/react/EditTransactionModal.jsx`) gains a Details|History tab strip; History lazy-loads the audit endpoint into a timeline (`TransactionHistory.jsx`) with human-readable field diffs. Bank-feed `batch_archive`/`batch_unarchive` now use per-instance saves (not `QuerySet.update()`) so signals fire and `updated_at` bumps.
- Bank feed: transfer double-count review. A transfer between two of the team's own accounts is reported by both banks, so it lands in the feed twice; categorizing both legs creates two journal entries and double-counts the movement in every balance and on the balance sheet. `apps/bank_feed/services/transfer_detection.py::find_transfer_candidates()` flags likely pairs (different account, equal magnitude + opposite direction, posted within `BANK_FEED_TRANSFER_WINDOW_DAYS` (default 5), neither archived nor voided, not the two legs of one entry, not previously dismissed; greedy one-to-one, closest-date wins) — covering both uncategorized *and* already-categorized pairs so existing double-counted history can be cleaned up. Endpoints on `BankFeedViewSet`: `GET transfers/` (suggestions), `POST transfers/resolve/` `{archive_id, keep_id}` (archives the duplicate leg and **voids** its journal entry so it drops out of balances via `NOT_VOID`; refuses reconciled legs; also archives any mirror leg), `POST transfers/dismiss/` `{transaction_a, transaction_b}` (records a `TransferMatchDismissal` so the pair stops being suggested). New `AuditEvent` types `transfer_dup_resolved`/`transfer_dup_dismissed`. Frontend: `TransferSuggestions.jsx` is a notification button (count badge) in the Select Account toolbar that opens a MUI review modal; each pair shows both legs' payee/memo and a "Reconciled" badge, and the archive button for a reconciled leg is disabled (mirrors the server guard). Transfer API helpers added to `getBatchOperationsApi` in `assets/javascript/bank_feed/bank_feed.js`.
- Bank feed: transfer mirror legs. Categorizing a bank transaction as a transfer to another **feed** asset/liability account (e.g. checking → credit card) now surfaces the transfer in *both* account feeds. `apps/bank_feed/services/transfer_mirror.py::sync_transfer()` creates/moves/removes a linked "mirror" `BankTransaction` (new `is_transfer_mirror` flag, `source=system`) in the counterpart account pointing at the **same** `JournalEntry` with the opposite-signed amount — so there's one entry (no double-count), the mirror shows in the counterpart feed via the existing per-account query (no feed/frontend change), and the two legs reconcile independently (per-`JournalLine` `is_reconciled`). `sync_transfer` is idempotent and symmetric, and runs from every categorization/edit path (`_create_journal_from_bank_transaction`, manual `create`, `update`, `_update_journal_category`, `batch_edit`, CSV `_auto_categorize_transaction`): it creates the mirror on first categorization, keeps date/amount/description/payee in lockstep when either leg is edited, removes the mirror if re-categorized away from a transfer, and — **fully transversable** — re-pointing *either* leg's category to another feed account moves the counterpart leg to follow (editing the mirror relocates the primary, and vice-versa). The one guarded case: pointing the **mirror** leg at a non-feed category (e.g. an expense) would orphan the real primary, so `would_orphan_primary()` makes `update`/`batch_edit` reject it with "edit the original transaction instead". `batch_delete` removes both legs + the shared entry; `find_transfer_candidates` skips two legs that share an entry so a primary+mirror is never flagged as a duplicate. Only mirrors targets with `has_feed=True` (expense/income categories never mirror).
- Bank feed: since account cards collapse and hide balances once an account is selected, `LineApp.jsx` now shows the selected account's categorized (= journal) balance and reconciled balance under the "Lines for …" header, and the To Review/Reconciled/Archived toggle buttons (`LineTableMaterial.jsx`) carry MUI `Badge` superscripts with each section's transaction count (computed from all loaded `lines`, independent of the active filter/date range).
- Bank feed: archiving/unarchiving one leg of a transfer (primary or mirror — they share one `JournalEntry`) now archives/unarchives the other leg too, in either direction. `apps/bank_feed/services/transfer_mirror.py::linked_legs()` finds the counterpart leg(s) sharing the same entry; `BankFeedViewSet.batch_archive`/`batch_unarchive` (`apps/bank_feed/views.py`) apply the same reconciled-guard to the linked leg (skip it silently if reconciled, but still archive the requested leg) and skip legs already in the target state.

---

## Known Issues

- `PlaidItem.access_token` stored in plaintext — needs field-level encryption in production
- E2E tests require `make start-bg` (Vite dev server) before running
- Coverage threshold set at 50% — many apps have minimal test coverage
- `STRICT_TEAM_CONTEXT` disabled by default; enable in production for stricter data isolation
- Plaid webhook receiver does not verify Plaid's JWT signature — a spoofed request can only trigger an extra sync, but add verification before production

---

## Agent Notes

This repo uses a six-agent AI pipeline for feature development. The pipeline is defined in `.claude/workflows/feature-pipeline.md`. Agent system prompts live in `.claude/agents/`.

**Pipeline order:** Designer → Feature Engineer → QA/Tester → Documentation Updater → Security Reviewer → PR Creator

**Stop conditions:**
- QA No-Go → return to Feature Engineer with bug list
- Security Blocked → return to Feature Engineer with Critical/High findings

**Living documents agents read/update:**
- `CLAUDE.md` (this file) — architecture, conventions, recent changes
- `docs/design-document.md` — UI/UX decisions
- `docs/testing-guide.md` — test patterns and coverage
- `docs/security-log.md` — security findings log

**Key pattern for new features:** Always extend `BaseTeamModel`, always add `TeamModelAccessPermissions`, always write a `TestCase` class with at minimum a happy-path and a permission test.
