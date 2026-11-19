# API-first migration: implementation plan

Goal: every screen of the authenticated app reads and writes through the DRF API (in OpenAPI,
typed in `api-client/`), so a phone app and the web app share one backend contract. Assessment and
estimates: `docs/mobile-api-plan.md`.

Integration branch: `claude/django-templates-api-migration-h7weqh` (off `develop`). Each work
package below is built on its own branch and merged into the integration branch. `develop` is
merged only after a full review.

## Decisions (apply to every work package)

| Topic | Decision |
|---|---|
| URL prefix | Keep the existing per-app pattern: `/a/{team}/{book}/{app}/api/...` for book data, `/a/{team}/api/...` for team data, `/api/...` for user/global data. No `/v1/` prefix (the app and API ship together; add one when a released phone app needs it). |
| View style | DRF only: `ViewSet`/`GenericViewSet` with `@action`, or `APIView`. No new `JsonResponse` views. Every endpoint has a serializer (request and response) so drf-spectacular types it; use `@extend_schema` where inference fails. |
| Permissions | Book data: `BookAccessPermissions` / `BookModelAccessPermissions` (existing). Admin-only actions: the book-admin equivalent. Team data: team permissions in `apps.teams`. |
| Auth | Session (web) + `X-Session-Token` (allauth headless `app` client, phone) + `UserAPIKey`. Built in WP1. |
| Business logic | Views call existing services (`ledger.py`, `voiding.py`, `write_lines`, `compute_unassigned`, `edit.py`, etc. — see `CLAUDE.md` write paths). No logic moves into serializers except validation that a Django form currently owns; that validation moves to a shared function used by both the form and the serializer while both exist. |
| Response shape | Structured data with ids, never DOM keys (`row:<pk>:available`), rendered HTML, or URL query strings. Money as decimal strings. Months as `YYYY-MM`. |
| Session state | APIs take month/book explicitly (URL or query). Web pages may keep writing `session["budget_month"]` for their own convenience; no API reads it. |
| Old JSON URLs | Replaced by the DRF endpoint. Keep the URL path and name when the new endpoint is a drop-in; otherwise remove the old URL in the same work package and update every caller. |
| Frontend | React islands stop receiving data via `json_script` and stop hand-writing `fetch`: they load and mutate through `api-client` (via `assets/javascript/api.js` / `common/book.js`). Only non-data config (URLs not derivable from `book-base`, feature flags) may stay in `json_script`. Show a loading state while the first request is in flight. |
| Server-rendered pages without React (budget month, goals, reports, dashboard, CRUD pages) | Get their API in this migration; the templates themselves are not rewritten here (Phase 5). |
| Tests | Per endpoint: happy path, permission (other book / non-member / anonymous), validation error. Every new book URL is classified in `apps/books/tests/test_isolation.py`. |
| Generated client | `scripts/build_api_client.sh` (WP1) regenerates `schema.yml`-equivalent output into `api-client/`, keeping `api-client/package.json`. Never hand-edit `api-client/`. |

## Phases and work packages

### Phase 1 — platform (sequential, blocks everything)

**WP1 Platform**
- Token auth: allauth headless `app` client enabled; DRF `XSessionTokenAuthentication` in
  `DEFAULT_AUTHENTICATION_CLASSES`; middleware after `AuthenticationMiddleware` that resolves the
  token into `request.user` and exempts header-token requests from CSRF, so `AuditUserMiddleware`
  attributes token writes. Tests: token request authenticated, CSRF not required for token, CSRF
  still required for session, audit row attributed to the token user, bad token → 401.
- `GET /api/me/`: user, teams (role), books per team (slug, name, archived), default team/book.
- `GET /a/{team}/{book}/api/nav-state/`: inbox count, nav feed accounts, Unassigned pill,
  onboarding rail — reusing the context-processor logic (extract shared functions; processors call them).
- `apps/api/` helpers for book-scoped API views: month query/path parsing (`YYYY-MM`, via
  `apps/utils/months.py`), standard validation-error shape.
- `scripts/build_api_client.sh`: `manage.py spectacular` → `openapi-generator-cli` 7.9.0
  `typescript-fetch` → `api-client/`, preserving `package.json`. Jar path from `OPENAPI_GENERATOR_JAR`.
- Test `apps/api/tests/test_schema.py`: schema generates with zero errors.

### Phase 2 — per-area API parity + frontend switch (parallel)

Each WP: convert that area's `JsonResponse` views to DRF, add read endpoints for its pages, switch
its React/JS callers to `api-client`, remove its `json_script` data props, register URLs in
`test_isolation.py`, tests.

| WP | Area | Scope |
|---|---|---|
| WP2 | Budget month, grid, Unassigned | `GET` month figures (tabs → sections → groups → rows, meters, hidden group); save-amount, cover, visibility, autofill, grid get/save, unassigned → DRF with structured responses; budget page JS (`budget-autosave.js`, `budget-visibility.js`, `month-swap.js`, `BudgetGrid.jsx`, `ActualTooltip.jsx`) consumes them. |
| WP3 | Goals | List, detail, activity, create/update with linked accounts (shared validation with `GoalForm`), allocate, assign-available, withdraw, complete, close, destroy, unlink, contribution edit, link-preview; `goals-app.js`, `goal-form.js` consume them. |
| WP4 | Accounts | Board `GET` + reorder/create/hide → DRF; account detail, activity, balance/budget chart data; ViewSets for accounts, groups, payees, institutions (reusing delete guards and book-unique-name rules); institution account checklist. `AccountsBoard.jsx`, account detail React consume them. |
| WP5 | Dashboard, reports, monthly review | Book home summary + net-worth chart; spending, net worth, budget & goals reports (ids, not drill URLs); monthly review payload + step/complete/dismiss → DRF; React islands consume them. Exports stay file downloads. |
| WP6 | Onboarding, YNAB import, portability | All JSON actions → DRF (file uploads via `MultiPartParser`); catalog/state/props `GET`s; their React apps consume them. |
| WP7 | Bank feed, transactions, reconciliation, rules | Page props (`json_script`) → `GET` endpoints; recurring stop → DRF; reconciliation hub + statement detail + undo; remaining hand-written fetches → `api-client`. |
| WP8 | Books, teams, users, subscriptions | Book list/create/archive/restore/delete/settings ViewSet (shared validation with `BookSettingsForm`); membership role/remove; invitation accept; profile, avatar, API keys, download data, delete account (re-auth); Stripe checkout/portal URLs as JSON. |

### Phase 3 — enforcement, QA, docs, security (sequential)

**WP9 Enforcement + QA**: test that fails if any book/team URL returns `JsonResponse` outside DRF
or is missing from the schema; remove dead views/templates fragments; regenerate `api-client`;
full backend suite; E2E suite; fix regressions.

**WP10 Docs + security review**: `docs/api-guide.md` (auth for phone clients, endpoint index),
`docs/mobile-api-plan.md` status, `CLAUDE.md` conventions, `docs/feature-history.md`,
`docs/security-log.md` (token auth, CSRF exemption, isolation, re-auth for destructive actions).

### Phase 5 (not in this branch) — retire Django templates

Replace server-rendered authenticated pages with React routes, page by page, once Phases 1–3 are
merged. Requires product decisions (loss of `<noscript>` fallbacks, SPA routing, store-billing
policy). Tracked separately.

## Merge procedure (integration branch)

1. WP branch rebased/merged onto the current integration branch by its author; its own app tests green.
2. Merge into the integration branch; resolve conflicts (`test_isolation.py` tables, `urls.py`,
   docs appends; `api-client/` is regenerated, never conflict-resolved by hand).
3. After each merge: `scripts/build_api_client.sh`, `ruff`, full backend suite, `npm run build`
   (or type check). Commit the regenerated client.

## Status

| WP | Status |
|---|---|
| WP1 | done (platform: token auth, `/api/me/`, nav-state, `apps/api/base.py`, `scripts/build_api_client.sh`) |
| WP2 | done (budget month, grid, Unassigned) |
| WP3 | done (goals) |
| WP4 | done (accounts) |
| WP5 | done (dashboard, reports, monthly review) |
| WP6 | done (onboarding, YNAB import, portability) |
| WP7 | done (bank feed, transactions, reconciliation, rules) |
| WP8 | done (books, teams, users, subscriptions) |
| WP9 | done (enforcement tests in `apps/api/tests/test_api_surface.py`, schema warnings, dead code, full backend + E2E suites, browser QA) |
| WP10 | done (`docs/api-guide.md`, mobile plan status, `CLAUDE.md`; security review in `docs/security-log.md`: 7 fixed, 10 open for decisions) |
