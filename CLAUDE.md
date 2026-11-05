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
| `chat` / `ai` | "Ask Koala" AI chat — still the Pegasus demo agents (weather, admin DB/email); no access to budget data |
| `categorization` | Auto-categorization rules and the suggestion-provider pipeline (rules → history → an AI provider slot) |
| `teams` | People and billing — Team, Membership, Invitation |
| `books` | The money tenant — Book (a set of books), request plumbing, legacy redirect, book settings |
| `users` | Custom user model, avatars, preferences |
| `api` | API key auth — UserAPIKey, hybrid permissions |
| `subscriptions` | Stripe billing via dj-stripe |
| `reports` | Income statements, balance sheets, Sankey diagrams |

**Account number convention:** 1000s = assets · 2000s = liabilities · 3000s = equity/goals · 4000s = income · 5000s = expenses

**URL pattern:** `/a/{team_slug}/{book_slug}/{app}/{path}/` for everything in a set of books; team-level pages (members, subscription, team settings, `books/`) stay at `/a/{team_slug}/…`

---

## Conventions

**Python:**
- Double quotes, 4-space indent, 120-char line limit (Ruff enforced)
- All financial models extend `BaseBookModel` (`apps.books.models`) — a `book` FK, no `team` column
- Custom querysets for complex queries (e.g. `GoalQuerySet.with_progress()`)
- Book-scoped manager: `Model.for_book.all()` auto-filters by the current book (`STRICT_BOOK_CONTEXT` raises without one)
- Book views use `@login_and_book_required` or `@book_admin_required` and take `(request, team_slug, book_slug, ...)`; team-level views keep `@login_and_team_required`
- DRF ViewSets with `BookModelAccessPermissions` for book-scoped API endpoints
- `unique_together = ["book", "field"]` on book-scoped unique fields
- Reverse book URLs with both slugs: `reverse(name, args=book.url_args)` / `{% url 'x:y' request.team.slug request.book.slug %}`; the frontend builds from the `book-base` value (`common/book.js`)
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

## Gotchas and single-writer rules

Full history and rationale: `docs/feature-history.md` (grep it; don't read it whole).

**Write paths (never bypass):**
- Balances count only `counted_entries()` (`apps/journal/models.py`); `transaction_entries()` excludes budget entries from anything presented as transactions.
- Void/restore only via `apps/journal/services/voiding.py` (`NoBypassingWritesTest` enforces it).
- Budget amounts and goal allocations live only in `SOURCE_BUDGET` journal entries; write via `apps/budget/ledger.py` only.
- Feed transaction journal lines: `apps/bank_feed/services/splits.py::write_lines` (never delete/recreate lines — it drops `is_reconciled`). Transfer mirrors: `transfer_mirror.sync_transfer`.
- Reconciled-line rules: call `apps.reconciliation.services.guards`; category rules: `apps.accounts.guards.assert_category_allowed`. Don't restate them.
- Unassigned: `apps/budget/unassigned.py::compute_unassigned` is the single source.
- Category suggestions and auto-categorization: a provider in `CATEGORIZATION_PROVIDERS` (`apps/categorization/`); applying one goes through `categorize_single`, and only `policy.book_allows_auto` lets a non-rule provider categorize without the user.

**Shared helpers (don't re-add copies):** `apps/utils/months.py`, `apps/utils/json_views.py`, `apps/utils/progress.py`, `apps/utils/amounts.py`; frontend `common/http.js`, `common/amount.js`, `common/book.js`, `common/Modal.jsx`, `common/Combobox.jsx`, `common/DateField.jsx`, `common/popoverPosition.js`. Icons: `{% icon %}` / `<Icon>`; add new ones via `assets/icons/build_icons.py`.

**Traps:**
- Django `{# … #}` is single-line only; multi-line renders as text. Use `{% comment %}`.
- `{% vite_react_refresh %}` must precede the entry in `page_js`.
- Every `@import` stays at the top of `site-tailwind.css`, theme first; fonts are a separate Vite entry.
- Muted text is `text-base-content/70` (lower fails AA contrast).
- `<dialog>`: nested dismissibles need `preventDefault()` on Escape; portals target `closest('dialog') ?? document.body`.
- No prettier config: use `npx prettier --single-quote --print-width 120`.
- Backend tests: `DJANGO_SETTINGS_MODULE=koala_budget.settings_test` (as `make test` does).
- E2E in a sandbox: don't run `playwright install`; point at the installed browser. Never run E2E and the Django test runner at once (shared test DB).
- Regenerate `api-client`: `manage.py spectacular --file schema.yml`, then `java -jar openapi-generator-cli.jar generate -i schema.yml -g typescript-fetch -o …` (7.9.0); keep `api-client/package.json`.
- Don't import heavy SDKs (`litellm`, `pydantic_ai`, `plaid`) at module level in anything the URLconf or models import — import inside the function. Each adds 1–2s to every dev-server reload.
- Plaid tests: mock at `apps.plaid.services.*`; a `MagicMock` task id in a DRF response hangs the test — set `delay.return_value.id`.

---

## Known Issues

- E2E tests require `make start-bg` (Vite dev server) before running
- Coverage threshold set at 50% — many apps have minimal test coverage
- Plaid: `FIELD_ENCRYPTION_KEY` must be set in production (the default derives from `SECRET_KEY`; rotating that without it makes every access token undecryptable)
- Plaid: `PLAID_REDIRECT_URI` is sent but no page resumes Link after an OAuth redirect (`receivedRedirectUri`) — leave it blank until one exists
- Plaid: Canada must be enabled for the client in the Plaid dashboard, and the redirect URI registered there
- Plaid: foreign-currency accounts are flagged, not converted; there is no per-book currency (`BASE_CURRENCY` is global)
- Plaid: no dedupe against CSV/YNAB history — linking a bank after importing its CSV imports the overlap again
- `PROJECT_METADATA["IMAGE"]` (social share image) is still the Pegasus logo

---

## Agent Notes

This repo uses a six-agent AI pipeline for feature development. The pipeline is defined in `.claude/workflows/feature-pipeline.md`. Agent system prompts live in `.claude/agents/`.

**Pipeline order:** Designer → Feature Engineer → QA/Tester → Documentation Updater → Security Reviewer → PR Creator

**Stop conditions:**
- QA No-Go → return to Feature Engineer with bug list
- Security Blocked → return to Feature Engineer with Critical/High findings

**Living documents agents read/update:**
- `CLAUDE.md` (this file) — architecture, conventions, gotchas (keep it short; it loads every session)
- `docs/feature-history.md` — detailed change log (append new entries here)
- `docs/design-document.md` — UI/UX decisions
- `docs/testing-guide.md` — test patterns and coverage
- `docs/security-log.md` — security findings log

**Key pattern for new features:** Always extend `BaseBookModel`, always add `BookModelAccessPermissions`, add each new book URL to the isolation tables in `apps/books/tests/test_isolation.py`, always write a `TestCase` class with at minimum a happy-path and a permission test.
