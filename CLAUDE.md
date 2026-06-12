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

---

## Known Issues

- `PlaidItem.access_token` stored in plaintext — needs field-level encryption in production
- E2E tests require `make start-bg` (Vite dev server) before running
- Coverage threshold set at 50% — many apps have minimal test coverage
- `STRICT_TEAM_CONTEXT` disabled by default; enable in production for stricter data isolation
- Bank feed list endpoint returns all rows in one response (`next: null` envelope) — needs real DRF pagination as data grows (frontend already follows `next` pages when present)
- `budget_month_view` bulk-creates Budget rows on GET — browsing far-future months inserts rows as a side effect of viewing

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
