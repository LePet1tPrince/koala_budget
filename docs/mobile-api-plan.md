# Mobile app: API-first architecture assessment

Goal: the browser app and a phone app both consume one API. This document inventories what is
already API, what is not, what auth needs, and the effort for each piece. Measured against the
codebase as of 2026-11-01.

## 1. Current state

| Layer | State |
|---|---|
| Auth | allauth 65.13 with **headless already installed** (`allauth.headless`, mounted at `/_allauth/`). `frontend/` SPA uses the `browser` client (cookie session). The `app` client (token, `X-Session-Token`) is available but unused. |
| DRF auth | `SessionAuthentication` + `BasicAuthentication`, plus `UserAPIKey`. No token auth for a phone. |
| DRF endpoints | 19 ViewSets/APIViews: bank feed, journal/transactions, reconciliation, plaid, audit, teams, chat, subscriptions products. Typed in OpenAPI → `api-client/`. |
| Plain-Django JSON views | ~40 function views returning `JsonResponse` behind `@login_and_book_required` + `@require_POST`: budget (save-amount, figures, cover, visibility, grid save, autofill, unassigned, goal assign/withdraw/close/unlink/destroy/contribution/link-preview), accounts board (5), onboarding (7), monthly review (3), YNAB import (4), portability (4). **Not in the OpenAPI schema**; frontend calls them with 72 hand-written `fetch`/`postJson` calls (only 5 files use `api-client`). |
| Server-rendered pages | 170 templates. Many React islands get their initial data via `json_script` (24 templates) — that data has **no API**. |

Services are already separated from views almost everywhere (`ReportService`, `BudgetService`,
`compute_unassigned`, `GoalService`, `goal_links`, `build_review`, `spending_report`,
`net_worth_report`, `task_state`, …). Most API work is serializer + view + tests, not logic
extraction.

## 2. Auth: what changes

Complexity: **low–medium**. Dropping Django templates is **not** required for the phone to
authenticate.

1. **Phone login/signup/MFA/password reset/social**: use allauth headless `app` client
   (`/_allauth/app/v1/...`). It returns a session token sent as `X-Session-Token`. allauth 65.13
   also offers a JWT token strategy if stateless access/refresh tokens are preferred. No new auth
   endpoints to write.
2. **DRF**: add `allauth.headless.contrib.rest_framework.authentication.XSessionTokenAuthentication`
   (or the JWT equivalent) to `DEFAULT_AUTHENTICATION_CLASSES`.
3. **Middleware-level token auth is required, not just DRF-level.** Two concrete reasons:
   - `apps/audit/middleware.py::AuditUserMiddleware` reads `request.user` in `__call__`, before any
     DRF authentication runs. A token request would write every `AuditLog` row with `user=None`.
   - The ~40 plain-Django JSON views use `login_and_book_required` (session user) and are subject to
     `CsrfViewMiddleware`. A token client has neither cookie.

   Fix: one middleware after `AuthenticationMiddleware` that resolves the token header into
   `request.user` and sets `request._dont_enforce_csrf_checks = True` for that request (a header
   token is not ambient, so CSRF does not apply). Alternatively convert those views to DRF (§3),
   which handles both, but the audit middleware still needs the user early.
4. **Session-held UI state** must become explicit parameters: `session["budget_month"]`,
   `session["monthly_review_month"]`, `session["book_by_team"]` (last-opened book),
   `session["team"]`. All are conveniences; the API takes the month/book in the URL/query.
5. **Social login on mobile**: Google/GitHub need native SDK → `provider/token` headless flow, or
   in-app browser redirect. Configuration, not code.
6. **Email links** (verify, reset, invitation) need `HEADLESS_FRONTEND_URLS` pointing at
   universal links / app links (`USE_HEADLESS_URLS` already exists). Team invitation acceptance
   (`teams:accept_invitation`, session-based) needs an API flow.

## 3. API work required, by area

Size: S ≈ 1–2 days, M ≈ 3–5 days, L ≈ 1.5–3 weeks (one developer, including tests and the
isolation-table registration in `apps/books/tests/test_isolation.py`).

### 3.1 Platform (do first)

| Item | Size |
|---|---|
| Token auth middleware + DRF class + CSRF exemption for token requests + audit attribution test | S |
| Convert the ~40 `JsonResponse` function views to DRF (`@api_view` or ViewSets) so they are authenticated uniformly, documented in OpenAPI, and in `api-client` | M–L (mechanical; many already return clean JSON) |
| API versioning prefix decision (`/api/v1/a/{team}/{book}/…` vs current per-app `…/api/`) | S |
| `me` endpoint: user, teams, books per team, default team/book (replaces `user_teams`, `book` context processors and `team_home` redirect logic) | S |
| Nav-state endpoint: inbox count, feed accounts, Unassigned pill (exists), onboarding rail (exists) | S |
| Money formatting: client-side formatter matching `currency` filter (`common/amount.js` already has `formatGrouped`) | S |

### 3.2 Per-screen read APIs that do not exist

| Screen | Today | Work | Size |
|---|---|---|---|
| Dashboard (`web.views.book_home`) | Template context assembled inline in the view (~100 lines) | Move to a service; expose JSON | S |
| Budget month (`budget_month_view`) | `_budget_figures()` builds a structured dict, but the only JSON form is `_budget_cells()` keyed to DOM `data-budget-cell` attributes | Serialize `_budget_figures` directly (sections → groups → rows, tabs, hidden group, meters); change save/cover/visibility responses to return structured figures, not DOM cells | M |
| Budget grid | Props via `json_script` | Expose existing props builder | S |
| Goals list / detail / activity | Template + vanilla JS; card progress logic in view helpers (`_goal_card_progress`, `goal_plan`, streaks) | Goal list/detail serializers; activity endpoint | M |
| Goal create/edit (with linked accounts, plan, preview) | Django `GoalForm` + `goal_links.set_links`; preview already JSON | Serializer duplicating `GoalForm` validation (name clash, target/contribution rules) + link rows | M |
| Accounts board | Payload builders exist (`_account_payload`, `_group_payload`), delivered via template | Expose GET; mutations already JSON | S |
| Account detail / activity + charts | CBV; `get_account_activity`, `build_balance_chart_data`, budget chart data exist | Expose JSON | S |
| Groups / Payees / Institutions CRUD | CBVs + Django forms; delete guards (`DeleteGuardMixin`), `BookUniqueNameMixin` | ModelViewSets reusing the same validation and guards | M |
| Institution account checklist | CBV POST | One endpoint | S |
| Reports (Income & Spending, Net Worth, Budget & Goals, home) | `spending_report`/`net_worth_report`/`budget_goals` return dicts; contain model instances (`item["account"]`) and URL query strings | Serializers; replace drill URLs with ids | M |
| Monthly review home | Props via template; step/complete/dismiss already JSON | Expose initial payload | S |
| Onboarding | Catalog/props via template; actions already JSON | Expose catalog + state | S |
| Bank feed / categorize / transactions pages | DRF already; page props (accounts, payees, groups) via `json_script` | Expose props as GET endpoints (mostly existing serializers) | S |
| Reconciliation hub + statement page | Template views; workspace already DRF | Hub list + statement detail endpoints; undo already a service | S |
| Books: list, create, settings, archive/restore/delete | Template + Django forms | ViewSet + `BookSettingsForm` rules in a serializer | S–M |
| Team management | `TeamViewSet`, `InvitationViewSet` exist | Membership role/remove endpoints | S |
| Profile, avatar upload, API keys, data download, delete account | Template + forms | Endpoints; delete-account requires re-auth | S–M |
| Subscription | Stripe Checkout/Portal session creation (server redirect) | Return session URLs as JSON. **App Store/Play policy**: selling a digital subscription inside the app requires IAP unless purchase is kept out of the app; decide before building | S (code) / product decision |
| YNAB import, data portability | Already JSON + file upload | Convert to DRF only; low mobile value | S |
| Audit log page | DRF exists | none | – |
| Chat ("Ask Koala") | DRF + Pegasus demo agents | Skip until it reads budget data | – |

### 3.3 Mobile-specific server work

| Item | Size |
|---|---|
| Plaid Link on mobile: link token must carry `android_package_name` (Android) and a universal-link `redirect_uri` (iOS OAuth banks); `PLAID_REDIRECT_URI` is currently sent with no resume page | S |
| Push notifications (none exist): device-token model, Celery send on sync/review events | M (optional) |
| Throttling: `user` 1000/hour may be tight for a phone + web user on the same account; review | S |
| CORS: not needed for native apps; only for a separately-hosted web SPA | – |

### 3.4 Totals (API parity, one developer)

| Block | Estimate |
|---|---|
| Platform (§3.1) | 2–3 weeks |
| Read/write parity (§3.2) | 5–7 weeks |
| Mobile-specific (§3.3, without push) | ~1 week |
| **API parity total** | **~8–11 weeks** |

Not included: the phone app UI itself, and rewriting the web UI.

## 4. Dropping the Django templates for the authenticated web app

Not required for "both clients call the same API". It is a separate, optional project.

- Already React-heavy (would port, not rewrite): bank feed (9.1k lines JS), transactions (1.9k),
  reconcile (1.3k), YNAB (2.2k), monthly review (1.6k), onboarding (1.5k), budget grid, accounts board.
- Server-rendered with Alpine/vanilla JS (real rewrites): budget month (2.1k template lines across
  `templates/budget`, plus `budget-autosave.js`, `budget-tabs.js`, `budget-visibility.js`,
  `month-swap.js`), goals pages, reports (0.9k template lines), dashboard + settings + nav shell
  (`templates/web`, 1.9k lines incl. marketing), accounts CRUD (0.9k), books, profile, teams.
- Marketing pages and allauth email templates stay server-rendered regardless.
- Lost in a full SPA: the `<noscript>` fallbacks several pages maintain deliberately.
- Estimate: **~3–4 months** for one developer after API parity, done page by page (strangler):
  each Django page is replaced by an SPA route only once its API exists.

## 5. Recommended order

1. Token auth middleware + DRF auth class (§2.3). Proves the phone can call the existing DRF
   endpoints (bank feed, transactions, reconcile) with no other change.
2. Convert plain JSON views to DRF; regenerate `api-client`; enforce "every endpoint in OpenAPI".
3. Add read endpoints in mobile priority order: `me` → dashboard → bank feed props/categorize →
   budget month → goals → transactions → reports → settings.
4. Migrate existing web React islands from `json_script` props + hand-written fetch to the same
   endpoints as they appear (removes the duplicate data path).
5. Build the phone app. React Native (Expo) shares TypeScript, `api-client`, and pure modules
   (`common/amount.js`, date helpers); DOM/daisyUI components do not transfer.
6. Decide on retiring web templates (§4) after the phone app ships; it is independent of it.

## 6. Risks

| Risk | Detail |
|---|---|
| Audit attribution | Token requests resolved only in DRF leave `AuditLog.user` empty (see §2.3). Needs a test. |
| Lazy team membership | `request.team_membership` is a lazy object on the Django request; correct only if nothing evaluates it before authentication. Test with token auth. |
| Duplicate validation | Django forms (accounts, goals, books) and new serializers can drift. Move rules into shared validators/services when writing the serializers. |
| DOM-coupled responses | Budget/goal endpoints return payloads keyed to template markup (`row:<pk>:available`). Mobile needs structured data; web must be migrated or both shapes kept. |
| Isolation coverage | Every new book URL must be classified in `test_isolation.py` (`test_every_book_url_is_covered` enforces this). |
| Store policy | Subscription purchase flow on iOS/Android (§3.2). |
