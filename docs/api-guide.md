# API Guide

Every screen of the signed-in app reads and writes through this API (the API-first migration,
`docs/api-first-migration-plan.md`). The web app and a phone app share it: the same DRF endpoints,
the same OpenAPI schema, the same generated TypeScript client in `api-client/`.

- Interactive docs: Swagger UI `/api/schema/swagger-ui/`, ReDoc `/api/schema/redoc/`; the schema
  itself is `/api/schema/` (or `manage.py spectacular --file schema.yml`).
- The [endpoint index](#endpoint-index) at the end lists every endpoint, generated from that schema.

## Authentication

Three ways in. Which one an endpoint accepts is its permission classes (see
[Permissions](#permissions)).

| Client | How | CSRF |
|---|---|---|
| Web app (browser) | Django session cookie (`SessionAuthentication`) | Required on writes (`X-CSRFToken` header, from the `csrftoken` cookie) |
| Phone app | allauth headless `app` client session token, sent as `X-Session-Token` | Not needed |
| Scripts / integrations | `Authorization: Api-Key <key>` (`UserAPIKey`) | Not needed |

HTTP Basic auth is **not** accepted: an email and password on every request would skip MFA and the
sign-in rate limit (security log, WP10).

### Phone app: session token

**1. Sign in** through allauth headless's `app` client (`HEADLESS_CLIENTS = ("browser", "app")`):

```bash
curl -X POST https://app.example.com/_allauth/app/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "me@example.com", "password": "..."}'
# 200 → {"status": 200, "data": {"user": {...}}, "meta": {"is_authenticated": true, "session_token": "<token>"}}
```

An account with MFA gets a 401 whose `data.flows` asks for the second factor
(`POST /_allauth/app/v1/auth/2fa/authenticate`); the token comes with the response that completes
sign-in. Signup, email verification, password reset, password change, re-authentication and MFA are
allauth's own endpoints under `/_allauth/app/v1/` (allauth's headless OpenAPI spec documents them).
Sign-in attempts are rate-limited per IP (`AuthRateLimitMiddleware`, `POST /_allauth/...`).

**2. Send the token** on every other request, with no cookies and no CSRF token:

```bash
curl -H "X-Session-Token: <token>" https://app.example.com/api/me/
```

With the generated client:

```typescript
import { Configuration, ApiApi } from 'api-client';

const config = new Configuration({
  basePath: 'https://app.example.com',
  apiKey: (name) => (name === 'X-Session-Token' ? token : ''), // OpenAPI scheme `XSessionTokenAuth`
});
const me = await new ApiApi(config).meRetrieve();
```

**3. Sign out:** `DELETE /_allauth/app/v1/auth/session` with the token. The token's session is
deleted; allauth answers 401 (signed out, with the sign-in flows), and the token is refused from then on.

How the token is handled (`apps/api/middleware.py`, `apps/api/authentication.py`):

- **What a token is.** allauth's session-token strategy: the token is the key of a Django session
  that allauth signed the user into. `apps.api.authentication.resolve_session_token` looks it up
  (allauth refuses an inactive user) and also checks the session's auth hash against the user's
  password, as Django does for every cookie session. A password change or reset therefore ends every
  token issued before it. allauth's own change-password call moves the session to a new key: use the
  `meta.session_token` in its response from then on.
- **`SessionTokenMiddleware`** runs right after `AuthenticationMiddleware` and before
  `AuditUserMiddleware`, `TeamsMiddleware` and `BooksMiddleware`. It sets `request.user` from the
  token, so audit rows written by the request are attributed to the token's user, membership is
  resolved for that user, and plain Django pages (`@login_and_book_required`) work with a token too.
  For that request `request.session` is the token's own session (the last-opened team and book are
  remembered per token); no `Set-Cookie` is sent.
- **CSRF is waived only for a request authenticated by the header token.** A browser never adds a
  custom header on its own, so a cross-site forgery cannot carry one. A cookie session is never
  exempted.
- **A cookie session wins.** A request that is already signed in by cookie is left exactly as it is
  (CSRF enforced, the cookie's user), whatever token it also carries. DRF agrees
  (`SessionTokenAuthentication` returns nothing then), so DRF and the audit log never disagree about
  who made a request.
- **A bad token is a 401.** A token that resolves to nobody (unknown, expired, signed out, from
  before a password change) gets `401` with `WWW-Authenticate: X-Session-Token` from any DRF
  endpoint, so the client knows to sign in again. A plain page redirects to the sign-in page. A
  request with no credentials at all is a `403`.
- **allauth's own `app` endpoints** (`/_allauth/app/...`) are left to allauth, which swaps in the
  token's session itself. `HeadlessAppUserMiddleware` (after `HijackUserMiddleware`) makes sure they
  see the token's user.

Tests: `apps/api/tests/test_token_auth.py`.

### API keys

A signed-in user creates keys on the API keys page or with `POST /users/api/api-keys/` (the key is
in that response only; `POST /users/api/api-keys/{prefix}/revoke/` revokes one). Send it as:

```bash
curl -H "Authorization: Api-Key <key>" https://app.example.com/api/me/
```

A key acts as its user, but only on endpoints that list `IsAuthenticatedOrHasUserAPIKey`
(`apps/api/permissions.py`): `GET /api/me/`, the team endpoints (`/teams/api/...`,
`/a/{team}/team/api/...`), the books API (`/a/{team}/books/api/...`, `…/settings/api/`) and the
subscription endpoints. Book data endpoints (`BookAccessPermissions` / `BookModelAccessPermissions`
alone) and the account endpoints under `/users/api/` refuse a key (`403`): changing the sign-in
email, minting keys, deleting the account and accepting an invitation need the person, by session
or session token.

### `GET /api/me/`

Who is signed in and where they work: the user (id, email, names, display name, avatar URL,
language, timezone), every team with the user's `role` and its books (`slug`, `name`,
`is_archived`, `is_default`, `base_url`), and `default: {team, book}`, where the web app would land
(`apps.books.helpers.landing_team_and_book`). A phone app calls it after sign-in to build its
team/book switcher. Session, token or API key.

### `GET /a/{team}/{book}/api/nav-state/`

The app chrome for one book: `inbox_count`, `feed_institutions` (the Inbox submenu's accounts by
institution), `unassigned` (this month: `month`, `amount`, `state`, `label`, `expected_income`) and
`onboarding_rail.visible`. The same functions the sidebar's context processors call
(`apps/bank_feed/services/nav.py`, `apps.budget.unassigned.current_unassigned`,
`apps/onboarding/services/rail.py`); call it again after a write to refresh the chrome. Book members.

## Conventions

### URLs

| Scope | Prefix | Examples |
|---|---|---|
| Book data | `/a/{team_slug}/{book_slug}/{app}/api/...` | `…/budget/api/month/`, `…/bankfeed/api/feed/` |
| Book, no one app | `/a/{team_slug}/{book_slug}/api/...` | `…/api/nav-state/`, `…/api/home/` |
| Team data | `/a/{team_slug}/{area}/api/...` | `/a/{team}/books/api/books/`, `/a/{team}/team/api/memberships/` |
| User / global | `/api/...`, `/users/api/...`, `/teams/api/...`, `/subscriptions/api/...` | `/api/me/`, `/users/api/profile/` |

There is no `/v1/` prefix: the web app and the API ship together (add one when a released phone app
needs it). `GET /api/me/` gives each book's `base_url`; the generated client takes `teamSlug` and
`bookSlug` as separate parameters (`assets/javascript/common/book.js` builds them from the page's
`book-base`). `api` is a reserved book slug.

### Data

- **Months** are `YYYY-MM` strings, in the query (`?month=2026-03`), the path or a body. A bad month
  is a `400 {"month": ["Enter a month as YYYY-MM."]}`. Helpers: `apps/api/base.py`
  (`parse_month_param`, `month_query_param`, `MonthField`, `month_parameter`). No API reads the web
  app's remembered month (`session["budget_month"]`): the month is in the request or it is the
  default the endpoint documents.
- **Dates** are `YYYY-MM-DD`.
- **Money** is a decimal string with two places (`"42.50"`), never a float. Positive is an outflow on
  feed rows, as in the ledger (`CLAUDE.md`); figures documented as "natural" are signed the way the
  account type reads.
- **Ids, not markup.** Responses carry ids and structured data, never rendered HTML, DOM keys or URL
  query strings.
- **Lists** from model viewsets are paginated (`PageNumberPagination`, 100 a page:
  `{count, next, previous, results}`, `?page=`); page-shaped endpoints (a month, a board, a page's
  pickers) return one object. The schema says which.

### Errors

| Status | Body | When |
|---|---|---|
| 400 | `{"<field>": ["message", ...]}` or `{"non_field_errors": [...]}` | Validation (a serializer's, a query parameter's, a refused action) |
| 401 | `{"detail": "..."}` + `WWW-Authenticate: X-Session-Token` | An `X-Session-Token` that resolves to nobody |
| 403 | `{"detail": "..."}` | No credentials; not a member of the URL's team; a member without the role a team write needs; missing CSRF on a cookie-session write |
| 404 | `{"detail": "Not found."}` | Another book's or team's row; a book the team doesn't have; a book-admin endpoint for a non-admin |
| 409 | `{"detail": "..."}` | A stale confirmation (e.g. a reconciliation adjustment computed differently now) |
| 429 | `{"detail": "..."}` | Throttled (DRF: 1000/hour per user, 100/hour anonymous; 10/hour for `users/api/delete-account/`) |

A few older bank-feed actions answer `{"error": "..."}` instead of the field shape (the schema shows
it). `assets/javascript/api.js::apiErrorMessage` picks the user-facing message from any of these.

### Permissions

| Class | Who | Used by |
|---|---|---|
| `BookAccessPermissions` (`apps/books/permissions.py`) | Members of the URL's team, on one of its books | Book `APIView`s (`apps.api.base.BookAPIView`) |
| `BookModelAccessPermissions` | Members read; on an existing row only admins write; the row's book must be the URL's | Book model viewsets |
| `BookAdminWritePermissions` | Members read, only admins write (no object to check) | e.g. rule create/reorder, Plaid link |
| `BookAdminPermissions` | Team admins only, reads included; anyone else gets **404** (as `@book_admin_required`) | Book settings, data export/import |
| `TeamMemberPermissions` (`apps/teams/permissions.py`) | Members of the URL's team | Memberships (the view decides role changes and removals) |
| `TeamAdminWritePermissions` | Members read, admins write (403 otherwise) | The books API |
| `TeamAdminPermissions` | Team admins only (403 otherwise) | Stripe checkout and portal |
| `TeamModelAccessPermissions` | Members read, admins edit an existing row | Team invitations |

What a client sees:

- **Not a member of the team:** `403`. Anonymous: `403` (`401` with a bad token).
- **Another book** (of a team the user is in, or not): its URL is a `404`, and an id of another
  book's row is a `404` (or a `400` naming the field, for an id in a body). Every book URL is in the
  isolation tables of `apps/books/tests/test_isolation.py`, which assert this for each.
- **A non-admin on an admin-only book endpoint:** `404`. On a team write that needs an admin: `403`.

### File uploads

Uploads are `multipart/form-data`; the file parts are `format: binary` in the schema
(`apps.api.base.UploadField`), so the generated client takes a `Blob`. Every other endpoint takes
JSON.

| Endpoint | Part | Limits |
|---|---|---|
| `POST /users/api/profile/avatar/` | `avatar` | Image extension (jpg, png, tif, webp, bmp), 5 MB |
| `POST …/ynab-import/api/upload/` | `files` (repeated, the register and the plan) | 20 MB each; only the first four parts are read |
| `POST …/data/api/upload/` | `file` (a Koala Budget export `.zip`) | 20 MB; 300 MB once decompressed (book admins) |
| `POST …/bankfeed/api/feed/upload_parse/`, `upload_preview/`, `upload_validate_dates/` | `file` (CSV or Excel) | See the security log (open item) |

### Frontend use

React islands and page scripts load and write through `api-client`, never `fetch` by hand and never
data in `json_script` (only config ids such as `book-base`; `apps/api/tests/test_api_surface.py`
holds the allowlist). Helpers in `assets/javascript/api.js`:

- `getApiConfiguration(window.location.origin)`: a `Configuration` that sends the CSRF header.
- `apiCall(request)`: awaits a client call; a failure becomes an `Error` with the server's message,
  `status` and parsed `payload`.
- `apiJson(request)`: the same for a `...Raw()` call, returning the parsed body.
- `apiErrorMessage(payload, response)`: the message alone.

```javascript
import { BudgetApi } from 'api-client';
import { apiCall, getApiConfiguration } from '../api';
import { readBook } from '../common/book';

const book = readBook();
const api = new BudgetApi(getApiConfiguration(window.location.origin));
const month = await apiCall(api.budgetMonthRetrieve({ ...book.params, month: '2026-03' }));
```

### Adding an endpoint

DRF only (`apps/api/tests/test_api_surface.py` fails for a plain Django view that answers JSON or a
DRF view missing from the schema). Request and response serializers so the schema is typed
(`test_schema.py` requires zero drf-spectacular warnings). Book scoping in `get_queryset`, the
permission class above, the URL in `test_isolation.py`, and tests for the happy path, a permission
refusal and a validation error. `apps/api/base.py`'s module docstring shows the shape of a book
`APIView`.

## Regenerating `api-client`

After any endpoint or serializer change, regenerate and commit `api-client/` (never hand-edit it):

```bash
OPENAPI_GENERATOR_JAR=/path/to/openapi-generator-cli-7.9.0.jar scripts/build_api_client.sh
# or: make build-api-client-local   (the same script)
# or: make build-api-client         (Docker, against a running dev server)
```

The script writes the schema with `manage.py spectacular` (no server needed), clean-regenerates
`api-client/` with openapi-generator 7.9.0 `typescript-fetch`, and keeps `api-client/package.json`.
Then `npx vite build` (or `npm run type-check`). New enum names go in
`SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]`; never rename an existing one.

## Webhooks

Not for clients: Stripe posts to `/stripe/webhook/` (dj-stripe), Plaid to `/plaid/webhook/` (signed
JWT, global because Plaid can't know team or book slugs).

## Endpoint index

Every endpoint in the OpenAPI schema, by area: 227 operations. `…/` is `/a/{team_slug}/{book_slug}/`;
`/a/{team}/` is `/a/{team_slug}/`. The purpose is the operation's own description (or the CRUD verb,
for plain model routes); the schema has the request and response types. Regenerate this table when
endpoints change: `manage.py spectacular --file schema.yml`, then each path's URL name is
`django.urls.resolve(path).view_name`.

#### User / global: api

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `/api/me/` | `api:me` | The signed-in user, every team they belong to with their role and its books, and the team and book the web app would open --… |

#### User / global: subscriptions

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `/subscriptions/api/active-products/` | `subscriptions:products_api` | The plans on offer, with their prices: what a client shows before `create_checkout_session`. |

#### User / global: teams

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `/teams/api/invitations/{invitation_id}/` | `teams:invitation_api` | A team invitation, for the person it was sent to: `GET` describes it, `POST` accepts it. |
| POST | `/teams/api/invitations/{invitation_id}/` | `teams:invitation_api` | Join the invitation's team. |
| GET | `/teams/api/teams/` | `teams:team-list` | List teams. |
| POST | `/teams/api/teams/` | `teams:team-list` | Create one (teams). |
| GET | `/teams/api/teams/{id}/` | `teams:team-detail` | Retrieve one (teams). |
| PUT | `/teams/api/teams/{id}/` | `teams:team-detail` | Replace one (teams). |
| PATCH | `/teams/api/teams/{id}/` | `teams:team-detail` | Change part of one (teams). |
| DELETE | `/teams/api/teams/{id}/` | `teams:team-detail` | Delete one (teams). |
| GET | `/teams/api/user-invitations/` | `teams:user_invitations_api` | Open invitations to the signed-in user's email addresses. |

#### User / global: users

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `/users/api/api-keys/` | `users:api-key-list` | The user's API keys that still work; a revoked key is gone from the list. |
| POST | `/users/api/api-keys/` | `users:api-key-list` | Create an API key. |
| POST | `/users/api/api-keys/{prefix}/revoke/` | `users:api-key-revoke` | Revoke one of the user's API keys. |
| POST | `/users/api/delete-account/` | `users:api_delete_account` | Permanently delete the signed-in user's account (`services.delete_user_account`: teams they are the only member of go with it,… |
| GET | `/users/api/profile/` | `users:api_profile` | The signed-in user's profile. |
| PATCH | `/users/api/profile/` | `users:api_profile` | Change the profile; fields left out keep their value. |
| POST | `/users/api/profile/avatar/` | `users:api_profile_avatar` | Upload a profile picture (multipart, an image of up to 5 MB). |
| GET | `/users/download-data/` | `users:download_data` | All the user's data as a ZIP archive (GDPR data portability). |

#### Team: books

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `/a/{team}/books/api/books/` | `books_team:book-list` | Every set of books in the team, archived ones included (so they can be restored). |
| POST | `/a/{team}/books/api/books/` | `books_team:book-list` | Create a set of books (admins). |
| GET | `/a/{team}/books/api/books/{slug}/` | `books_team:book-detail` | Retrieve one (books). |
| POST | `/a/{team}/books/api/books/{slug}/archive/` | `books_team:book-archive` | Archive the book (admins). |
| POST | `/a/{team}/books/api/books/{slug}/delete/` | `books_team:book-delete` | Delete the book and every row in it (admins). |
| POST | `/a/{team}/books/api/books/{slug}/restore/` | `books_team:book-restore` | Restore an archived book (admins). |

#### Team: subscription

| Method | Path | URL name | Purpose |
|---|---|---|---|
| POST | `/a/{team}/subscription/stripe/api/create-checkout-session/` | `subscriptions_team:api_create_checkout_session` | A Stripe Checkout session for the team to subscribe to `price_id`: the URL to send the user to. |
| POST | `/a/{team}/subscription/stripe/api/create-portal-session/` | `subscriptions_team:api_create_portal_session` | A Stripe Customer Portal session for the team's subscription: the URL to send the user to. |

#### Team: team

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `/a/{team}/team/api/invitations/` | `single_team:invitation-list` | List invitations. |
| POST | `/a/{team}/team/api/invitations/` | `single_team:invitation-list` | Create one (invitations). |
| GET | `/a/{team}/team/api/invitations/{id}/` | `single_team:invitation-detail` | Retrieve one (invitations). |
| PUT | `/a/{team}/team/api/invitations/{id}/` | `single_team:invitation-detail` | Replace one (invitations). |
| PATCH | `/a/{team}/team/api/invitations/{id}/` | `single_team:invitation-detail` | Change part of one (invitations). |
| DELETE | `/a/{team}/team/api/invitations/{id}/` | `single_team:invitation-detail` | Delete one (invitations). |
| POST | `/a/{team}/team/api/invitations/{id}/resend/` | `single_team:invitation-resend` | Email the invitation again (admins). |
| GET | `/a/{team}/team/api/memberships/` | `single_team:membership-list` | The team's members, by email. |
| GET | `/a/{team}/team/api/memberships/{id}/` | `single_team:membership-detail` | Retrieve one (memberships). |
| PATCH | `/a/{team}/team/api/memberships/{id}/` | `single_team:membership-detail` | Change a member's role (admins; never your own). |
| DELETE | `/a/{team}/team/api/memberships/{id}/` | `single_team:membership-detail` | Remove a member (admins), or leave the team (anyone, their own membership). |

#### Book: accounts

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/accounts/api/accounts/` | `accounts:account-list` | The book's accounts (never budget buckets: they belong to the app). |
| POST | `…/accounts/api/accounts/` | `accounts:account-list` | Create one (accounts). |
| GET | `…/accounts/api/accounts/{id}/` | `accounts:account-detail` | Retrieve one (accounts). |
| PUT | `…/accounts/api/accounts/{id}/` | `accounts:account-detail` | Replace one (accounts). |
| PATCH | `…/accounts/api/accounts/{id}/` | `accounts:account-detail` | Change part of one (accounts). |
| DELETE | `…/accounts/api/accounts/{id}/` | `accounts:account-detail` | Delete the account; refused with a 400 when its references forbid it. |
| GET | `…/accounts/api/accounts/{id}/activity/` | `accounts:account-activity` | The account's transactions over a range, signed so positive means its balance (or total) grew, with a running balance for… |
| GET | `…/accounts/api/accounts/{id}/charts/` | `accounts:account-charts` | The balance-over-time chart (balance accounts) and the budget chart (budgeted categories, goals). |
| GET | `…/accounts/api/board/` | `accounts:board` | The chart-of-accounts board: type sections -> groups -> account rows, in board order. |
| POST | `…/accounts/api/board/create-account/` | `accounts:board-create-account` | An account at the bottom of a group; assets and liabilities get a feed. |
| POST | `…/accounts/api/board/create-group/` | `accounts:board-create-group` | A group at the bottom of its type's section. |
| POST | `…/accounts/api/board/reorder-accounts/` | `accounts:board-reorder-accounts` | Persist account ordering (and moves between groups of the same type). |
| POST | `…/accounts/api/board/reorder-groups/` | `accounts:board-reorder-groups` | Persist the group order within one account type. |
| POST | `…/accounts/api/board/set-hidden/` | `accounts:board-set-hidden` | Hide or show an account (the board's eye toggle). |
| GET | `…/accounts/api/groups/` | `accounts:account-group-list` | The book's account groups (never the budget group). |
| POST | `…/accounts/api/groups/` | `accounts:account-group-list` | Create one (groups). |
| GET | `…/accounts/api/groups/{id}/` | `accounts:account-group-detail` | Retrieve one (groups). |
| PUT | `…/accounts/api/groups/{id}/` | `accounts:account-group-detail` | Replace one (groups). |
| PATCH | `…/accounts/api/groups/{id}/` | `accounts:account-group-detail` | Change part of one (groups). |
| DELETE | `…/accounts/api/groups/{id}/` | `accounts:account-group-detail` | Delete the group; refused with a 400 when its references forbid it. |
| GET | `…/accounts/api/institutions/` | `accounts:institution-list` | The book's institutions. |
| POST | `…/accounts/api/institutions/` | `accounts:institution-list` | Create one (institutions). |
| GET | `…/accounts/api/institutions/{id}/` | `accounts:institution-detail` | Retrieve one (institutions). |
| PUT | `…/accounts/api/institutions/{id}/` | `accounts:institution-detail` | Replace one (institutions). |
| PATCH | `…/accounts/api/institutions/{id}/` | `accounts:institution-detail` | Change part of one (institutions). |
| DELETE | `…/accounts/api/institutions/{id}/` | `accounts:institution-detail` | Delete the institution; refused with a 400 when its references forbid it. |
| GET | `…/accounts/api/institutions/{id}/accounts/` | `accounts:institution-accounts` | The checklist of accounts an institution can hold (this book's assets and liabilities). |
| POST | `…/accounts/api/institutions/{id}/accounts/` | `accounts:institution-accounts` | Set which accounts the institution holds. |
| GET | `…/accounts/api/payees/` | `accounts:payee-list` | The book's payees, with how often their transactions count. |
| POST | `…/accounts/api/payees/` | `accounts:payee-list` | Create one (payees). |
| GET | `…/accounts/api/payees/{id}/` | `accounts:payee-detail` | Retrieve one (payees). |
| PUT | `…/accounts/api/payees/{id}/` | `accounts:payee-detail` | Replace one (payees). |
| PATCH | `…/accounts/api/payees/{id}/` | `accounts:payee-detail` | Change part of one (payees). |
| DELETE | `…/accounts/api/payees/{id}/` | `accounts:payee-detail` | Delete the payee; refused with a 400 when its references forbid it. |

#### Book: api

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/api/home/` | `book_api:home` | The dashboard of this book: net worth, income − expenses year to date, what the open goals still need and the first few of… |
| GET | `…/api/nav-state/` | `book_api:nav_state` | What the app chrome shows for this book: the Inbox badge, the Inbox submenu's feed accounts, the Unassigned pill (always this… |

#### Book: audit

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/audit/api/events/` | `audit:audit-event-list` | The book's audit events (and the team's own), newest first; `?event_type=`. |
| GET | `…/audit/api/events/{id}/` | `audit:audit-event-detail` | One audit event. |

#### Book: bankfeed

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/bankfeed/api/feed/` | `bank_feed:bank-feed-list` | Get unified bank feed, optionally filtered by account. |
| POST | `…/bankfeed/api/feed/` | `bank_feed:bank-feed-list` | Create a new manual bank transaction with associated journal entry. |
| GET | `…/bankfeed/api/feed/account_groups/` | `bank_feed:bank-feed-account-groups` | Return all account groups for the book, for use in account creation. |
| POST | `…/bankfeed/api/feed/batch_delete/` | `bank_feed:bank-feed-batch-delete` | Permanently delete voided bank transactions. |
| POST | `…/bankfeed/api/feed/batch_duplicate/` | `bank_feed:bank-feed-batch-duplicate` | Batch duplicate multiple bank transactions. |
| PATCH | `…/bankfeed/api/feed/batch_edit/` | `bank_feed:bank-feed-batch-edit` | Bulk edit multiple bank transactions. |
| POST | `…/bankfeed/api/feed/batch_restore/` | `bank_feed:bank-feed-batch-restore` | Restore voided bank transactions, with their entries and their transfers' other legs. |
| POST | `…/bankfeed/api/feed/batch_void/` | `bank_feed:bank-feed-batch-void` | Void bank transactions: they and their journal entries count toward nothing. |
| POST | `…/bankfeed/api/feed/categorize/` | `bank_feed:bank-feed-categorize` | Categorize one or more bank transactions. |
| GET | `…/bankfeed/api/feed/category_suggestions/` | `bank_feed:bank-feed-category-suggestions` | Suggest a category per merchant based on the most recent categorization. |
| POST | `…/bankfeed/api/feed/create_account/` | `bank_feed:bank-feed-create-account` | Create a new account for use in the CSV upload category mapping step. |
| GET | `…/bankfeed/api/feed/feed_accounts/` | `bank_feed:bank-feed-feed-accounts` | Return feed accounts with up-to-date balances and review counts. |
| GET | `…/bankfeed/api/feed/locate/` | `bank_feed:bank-feed-locate` | Which page of the current list a row is on, or `page: null` when the filters hide it. |
| GET | `…/bankfeed/api/feed/pickers/` | `bank_feed:bank-feed-pickers` | What the Inbox's and Categorize mode's pickers offer: every account a transaction can be categorized to (goal accounts with… |
| GET | `…/bankfeed/api/feed/sample_csv/` | `bank_feed:bank-feed-sample-csv` | Download a sample bank statement CSV. |
| GET | `…/bankfeed/api/feed/selection/` | `bank_feed:bank-feed-selection` | Every row matching the filters, as the batch bar reads it: "select all N matching". |
| GET | `…/bankfeed/api/feed/similar_categories/` | `bank_feed:bank-feed-similar-categories` | Suggest categories for uncategorized transactions from how similar ones were categorized before — matching on payee, on… |
| GET | `…/bankfeed/api/feed/transfers/` | `bank_feed:bank-feed-transfer-suggestions` | List likely-duplicate transfer pairs (a transfer reported by both banks). |
| POST | `…/bankfeed/api/feed/transfers/dismiss/` | `bank_feed:bank-feed-transfer-dismiss` | Dismiss a suggested pair as 'not a duplicate' so it stops being suggested. |
| POST | `…/bankfeed/api/feed/transfers/match/` | `bank_feed:bank-feed-transfer-match` | Match a duplicate transfer: keep one leg, archive the other. |
| POST | `…/bankfeed/api/feed/upload_confirm/` | `bank_feed:bank-feed-upload-confirm` | Create BankTransaction records from confirmed transactions. |
| POST | `…/bankfeed/api/feed/upload_parse/` | `bank_feed:bank-feed-upload-parse` | Parse an uploaded CSV/Excel file and return headers + sample rows. |
| POST | `…/bankfeed/api/feed/upload_preview/` | `bank_feed:bank-feed-upload-preview` | Apply column mapping to uploaded file and return parsed transactions. |
| POST | `…/bankfeed/api/feed/upload_validate_dates/` | `bank_feed:bank-feed-upload-validate-dates` | Check every row's date cell against the chosen date format. |
| PUT | `…/bankfeed/api/feed/{id}/` | `bank_feed:bank-feed-detail` | Update an existing bank transaction and its associated journal entry. |
| PATCH | `…/bankfeed/api/feed/{id}/` | `bank_feed:bank-feed-detail` | Update part of a bank transaction and its journal entry. |
| GET | `…/bankfeed/api/recurring/` | `bank_feed:recurring-schedule-list` | The book's recurring schedules. |
| DELETE | `…/bankfeed/api/recurring/{id}/` | `bank_feed:recurring-schedule-detail` | Stop a recurring schedule (rows it wrote stay). |

#### Book: budget

| Method | Path | URL name | Purpose |
|---|---|---|---|
| POST | `…/budget/api/amount/` | `budget:api_amount` | Set one category's budget for a month (replacing what was there; blank clears it). |
| POST | `…/budget/api/autofill/` | `budget:api_autofill` | Auto-Assign: set every reached category's budget for the month at once -- last month's budget, last month's activity, zero, or… |
| POST | `…/budget/api/categories/{id}/visibility/` | `budget:api_category_visibility` | Hide a category from the budget page, or bring it back. |
| POST | `…/budget/api/cover/` | `budget:api_cover` | Cover an overspent expense category (docs/goals-envelopes-plan.md §4.4). |
| GET | `…/budget/api/goals/` | `budget:api_goals` | The goals page for a month: each goal's card, their totals and Unassigned. |
| POST | `…/budget/api/goals/` | `budget:api_goals` | Create a goal, with the accounts its money lives in (validated as the goal form is). |
| POST | `…/budget/api/goals/contributions/{line_pk}/` | `budget:api_goal_contribution` | Change or undo a past month's manual contribution, named by its line on the month's budget entry (`line_id` in the goal's… |
| POST | `…/budget/api/goals/link-preview/` | `budget:api_goal_link_preview` | What saving the goal form's linked accounts and outflow setting would do -- to the goal and to Unassigned -- without writing… |
| POST | `…/budget/api/goals/links/{link_pk}/unlink/` | `budget:api_goal_unlink` | Stop an account feeding its goal. |
| GET | `…/budget/api/goals/{id}/` | `budget:api_goal` | The goal page for a month: the card, linked accounts, spending and drift. |
| PUT | `…/budget/api/goals/{id}/` | `budget:api_goal` | Change a goal's settings and (with `links`) its linked accounts. |
| PATCH | `…/budget/api/goals/{id}/` | `budget:api_goal` | Change some of a goal's settings; the rest stay. |
| DELETE | `…/budget/api/goals/{id}/` | `budget:api_goal` | Delete a goal for good -- open, closed or archived -- with its contributions and account links, freeing its name and its… |
| GET | `…/budget/api/goals/{id}/activity/` | `budget:api_goal_activity` | Everything that moved the goal, newest first: contributions, linked money, spending. |
| POST | `…/budget/api/goals/{id}/allocate/` | `budget:api_goal_allocate` | Set the goal's allocation for a month (replacing it), as the no-JS "Set month" form does. |
| POST | `…/budget/api/goals/{id}/archive/` | `budget:api_goal_archive` | Archive the goal: it leaves every list. |
| POST | `…/budget/api/goals/{id}/assign/` | `budget:api_goal_assign` | Add money to the goal for a month (added to the month's allocation). |
| POST | `…/budget/api/goals/{id}/close/` | `budget:api_goal_close` | Close the goal: anything left goes back to Unassigned this month. |
| POST | `…/budget/api/goals/{id}/complete/` | `budget:api_goal_complete` | Mark the goal funded: it stops asking for money but keeps what it holds. |
| POST | `…/budget/api/goals/{id}/withdraw/` | `budget:api_goal_withdraw` | Take money back out of the goal, recorded against the month (whose allocation may go negative; past months stay as they were). |
| GET | `…/budget/api/grid/` | `budget:api_grid` | The multi-month grid editor's data: a row per (visible) budgeted category, its budget for each month of the range, and three… |
| POST | `…/budget/api/grid/save/` | `budget:api_grid_save` | Save a batch of grid edits, all or nothing: one unknown category or bad amount rejects the whole batch. |
| GET | `…/budget/api/month/` | `budget:api_month` | Every figure the budget page shows for one month: a section per tab (income, when the book budgets it, then expenses), each… |
| GET | `…/budget/api/unassigned/` | `budget:api_unassigned` | Unassigned for a month (default: this month, the figure the sidebar pill shows): net worth less what the expense envelopes and… |

#### Book: data

| Method | Path | URL name | Purpose |
|---|---|---|---|
| POST | `…/data/api/apply/` | `portability:api_apply` | Start the import: the book is wiped and replaced by the uploaded archive. |
| GET | `…/data/api/safety-export/` | `portability:api_safety_export` | The pre-wipe copy of the book, as a .zip download, while `SAFETY_EXPORT_WINDOW` has not yet elapsed; a 404 after it, or before… |
| GET | `…/data/api/state/` | `portability:api_state` | What the page opens on: the export warning's count, and an import to pick back up -- one uploaded or running, the most recent… |
| GET | `…/data/api/status/` | `portability:api_status` | Where the import has got to. |
| POST | `…/data/api/upload/` | `portability:api_upload` | Parse and validate the uploaded archive, and show what it will replace. |

#### Book: journal

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/journal/api/journal-entries/` | `journal:journal-entry-list` | List journal entries. |
| POST | `…/journal/api/journal-entries/` | `journal:journal-entry-list` | Create one (journal entries). |
| GET | `…/journal/api/journal-entries/{id}/` | `journal:journal-entry-detail` | Retrieve one (journal entries). |
| PUT | `…/journal/api/journal-entries/{id}/` | `journal:journal-entry-detail` | Replace one (journal entries). |
| PATCH | `…/journal/api/journal-entries/{id}/` | `journal:journal-entry-detail` | Change part of one (journal entries). |
| DELETE | `…/journal/api/journal-entries/{id}/` | `journal:journal-entry-detail` | Delete one (journal entries). |
| GET | `…/journal/api/journal-entries/{id}/audit/` | `journal:journal-entry-audit` | Return the row-level audit history for this journal entry and its lines. |
| POST | `…/journal/api/journal-entries/{id}/post_entry/` | `journal:journal-entry-post-entry` | Post a draft journal entry (change status to posted). |
| POST | `…/journal/api/journal-entries/{id}/void_entry/` | `journal:journal-entry-void-entry` | Void a posted journal entry. |
| GET | `…/journal/api/lines/` | `journal:line-list` | List lines. |
| POST | `…/journal/api/lines/` | `journal:line-list` | Create one (lines). |
| GET | `…/journal/api/lines/{id}/` | `journal:line-detail` | Retrieve one (lines). |
| PUT | `…/journal/api/lines/{id}/` | `journal:line-detail` | Replace one (lines). |
| PATCH | `…/journal/api/lines/{id}/` | `journal:line-detail` | Change part of one (lines). |
| DELETE | `…/journal/api/lines/{id}/` | `journal:line-detail` | Delete one (lines). |
| POST | `…/journal/api/lines/{id}/recategorize/` | `journal:line-recategorize` | Recategorize a journal line to a different account/category. |
| GET | `…/journal/api/transactions/` | `journal:transaction-list` | Journal entries flattened into transaction rows, and the edits made to them. |
| POST | `…/journal/api/transactions/batch_delete/` | `journal:transaction-batch-delete` | Remove transactions. |
| POST | `…/journal/api/transactions/batch_status/` | `journal:transaction-batch-status` | Void transactions so they drop out of every balance, or restore them. |
| PATCH | `…/journal/api/transactions/edit/` | `journal:transaction-edit` | Apply one partial edit to one or more transactions. |
| GET | `…/journal/api/transactions/facets/` | `journal:transaction-facets` | List the values one column offers, with the row count behind each. |
| GET | `…/journal/api/transactions/pickers/` | `journal:transaction-pickers` | The edit modal's account and payee pickers, for any page that hosts it (Transactions, an account's activity). |
| GET | `…/journal/api/transactions/{id}/` | `journal:transaction-detail` | One transaction as the edit modal needs it, with what may be changed. |

#### Book: monthly review (`reports/monthly-review/`)

| Method | Path | URL name | Purpose |
|---|---|---|---|
| POST | `…/reports/monthly-review/api/complete/` | `monthly_review:api_complete` | Mark the month reviewed (once): the client opens the month's dashboard. |
| POST | `…/reports/monthly-review/api/dismiss/` | `monthly_review:api_dismiss` | Skip the month's review (once): the dashboard stops nudging for it. |
| GET | `…/reports/monthly-review/api/review/` | `monthly_review:api_review` | The whole review of one month, every comparison baseline precomputed (a client reslices it per baseline without asking again),… |
| POST | `…/reports/monthly-review/api/step/` | `monthly_review:api_step` | Record the step the user is on and the baseline they chose (each optional); starts the review. |

#### Book: onboarding

| Method | Path | URL name | Purpose |
|---|---|---|---|
| POST | `…/onboarding/api/answers/` | `onboarding:api_answers` | Save answers and advance. |
| GET | `…/onboarding/api/catalog/` | `onboarding:api_catalog` | The question catalog: prompts, options and answer shapes, with the chart-of-accounts rules left behind on the server. |
| POST | `…/onboarding/api/complete/` | `onboarding:api_complete` | Build the chart of accounts, apply the user's edits to it, and finish. |
| GET | `…/onboarding/api/opening-balances/` | `onboarding:api_opening_balances` | The accounts worth asking an opening balance for, with net worth now. |
| POST | `…/onboarding/api/opening-balances/` | `onboarding:api_opening_balances` | Save opening balances. |
| POST | `…/onboarding/api/preview-coa/` | `onboarding:api_preview_coa` | The chart of accounts these answers would produce, without writing anything. |
| POST | `…/onboarding/api/skip/` | `onboarding:api_skip` | Skip the questionnaire: the stock chart of accounts is applied instead. |
| GET | `…/onboarding/api/state/` | `onboarding:api_state` | Where this book is in the walkthrough, and what the takeover greets the user with. |
| POST | `…/onboarding/api/task/` | `onboarding:api_task` | Record a guided task as done, or put the rail back (`resume`), or dismiss it. |
| GET | `…/onboarding/api/tasks/` | `onboarding:api_tasks` | The guided tasks with their current state. |

#### Book: plaid

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/plaid/api/accounts/` | `plaid:plaid-account-list` | List accounts. |
| GET | `…/plaid/api/accounts/{id}/` | `plaid:plaid-account-detail` | Retrieve one (accounts). |
| PATCH | `…/plaid/api/accounts/{id}/` | `plaid:plaid-account-detail` | Change part of one (accounts). |
| POST | `…/plaid/api/exchange-token/` | `plaid:exchange-public-token` | Exchange a public token for an access token and create PlaidItem and PlaidAccount records. |
| GET | `…/plaid/api/items/` | `plaid:plaid-item-list` | List items. |
| GET | `…/plaid/api/items/{id}/` | `plaid:plaid-item-detail` | Retrieve one (items). |
| POST | `…/plaid/api/items/{id}/link-token/` | `plaid:plaid-item-link-token` | A Link token in update mode for this item: the user signs in to the bank again, renews consent, or shares accounts Plaid found… |
| POST | `…/plaid/api/items/{id}/refresh/` | `plaid:plaid-item-refresh` | After Link's update mode succeeds: mark the connection healthy, add any accounts the user just shared (returned for mapping),… |
| POST | `…/plaid/api/items/{id}/remove/` | `plaid:plaid-item-remove` | Disconnect this bank. |
| POST | `…/plaid/api/items/{id}/sync/` | `plaid:plaid-item-sync` | Trigger transaction sync for this Plaid item. |
| POST | `…/plaid/api/link-token/` | `plaid:create-link-token` | Create a Plaid Link token for initializing Plaid Link. |
| GET | `…/plaid/api/transactions/` | `plaid:imported-transaction-list` | List transactions. |
| GET | `…/plaid/api/transactions/{id}/` | `plaid:imported-transaction-detail` | Retrieve one (transactions). |

#### Book: reconcile

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/reconcile/api/reconciliations/` | `reconciliation:reconciliation-list` | One account's draft statement and history (`?account=<id>`). |
| POST | `…/reconcile/api/reconciliations/` | `reconciliation:reconciliation-list` | Start a draft statement for an account (ticks what it can). |
| GET | `…/reconcile/api/reconciliations/accounts/` | `reconciliation:reconciliation-accounts` | The hub: every reconcilable account and where it stands. |
| GET | `…/reconcile/api/reconciliations/page/` | `reconciliation:reconciliation-page` | What one account's reconcile page opens on (`?account=<id>`). |
| GET | `…/reconcile/api/reconciliations/{id}/` | `reconciliation:reconciliation-detail` | A statement: a draft's workspace or a finished one. |
| PATCH | `…/reconcile/api/reconciliations/{id}/` | `reconciliation:reconciliation-detail` | Change a draft statement's date or ending balance. |
| DELETE | `…/reconcile/api/reconciliations/{id}/` | `reconciliation:reconciliation-detail` | Discard a draft statement. |
| POST | `…/reconcile/api/reconciliations/{id}/finish/` | `reconciliation:reconciliation-finish` | Finish the statement (posts an adjustment when asked to). |
| POST | `…/reconcile/api/reconciliations/{id}/tick/` | `reconciliation:reconciliation-tick` | Tick or untick lines on a draft statement. |
| POST | `…/reconcile/api/reconciliations/{id}/tick_through/` | `reconciliation:reconciliation-tick-through` | Tick every line through a date. |
| POST | `…/reconcile/api/reconciliations/{id}/undo/` | `reconciliation:reconciliation-undo` | Undo a finished statement: its lines become unreconciled and any adjustment is voided. |
| POST | `…/reconcile/api/reconciliations/{id}/untick_all/` | `reconciliation:reconciliation-untick-all` | Untick every line of a draft statement. |

#### Book: reports

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/reports/api/budget-and-goals/` | `reports:api_budget_goals` | Budget & Goals for one month: where every dollar of net worth is going -- each goal, the budget envelopes in total, and what… |
| GET | `…/reports/api/home/` | `reports:api_home` | What the reports home shows beside its links: whether last month has been reviewed. |
| GET | `…/reports/api/net-worth/` | `reports:api_net_worth` | Net Worth: what you own and owe at the end of a range of whole months and what changed since its start, by section, group and… |
| GET | `…/reports/api/spending/` | `reports:api_spending` | Income & Spending: money in and out over a range -- summary stats, the statement by group and account with per-period figures,… |

#### Book: rules

| Method | Path | URL name | Purpose |
|---|---|---|---|
| POST | `…/rules/api/matches/accept/` | `rules:rule-match-accept` | Accept suggestions as offered. |
| POST | `…/rules/api/matches/{transaction_id}/dismiss/` | `rules:rule-match-dismiss` | Dismiss a rule's suggestion on one feed row. |
| POST | `…/rules/api/matches/{transaction_id}/undo/` | `rules:rule-match-undo` | Undo a rule's auto-post on one feed row. |
| GET | `…/rules/api/proposals/` | `rules:rule-proposal-list` | Rules the book's history proposes (`services.learning`). |
| POST | `…/rules/api/proposals/{id}/accept/` | `rules:rule-proposal-accept` | The rule this proposal stands for, as a draft for the builder. |
| POST | `…/rules/api/proposals/{id}/dismiss/` | `rules:rule-proposal-dismiss` | Dismiss a proposed rule. |
| GET | `…/rules/api/rules/` | `rules:rule-list` | The book's rules, in priority order (lower wins). |
| POST | `…/rules/api/rules/` | `rules:rule-list` | Create one (rules). |
| POST | `…/rules/api/rules/decline_draft/` | `rules:rule-decline-draft` | Don't offer a rule for this merchant again -- the create-from-action toast's No. |
| POST | `…/rules/api/rules/draft_from_transaction/` | `rules:rule-draft-from-transaction` | The rule a just-made categorization suggests, and whether it is worth offering. |
| POST | `…/rules/api/rules/explain/` | `rules:rule-explain` | Why a draft rule does or does not match one transaction. |
| GET | `…/rules/api/rules/page/` | `rules:rule-page` | What the Rules page opens on: whether the user may edit, the categories and the feed accounts. |
| GET | `…/rules/api/rules/prompts/` | `rules:rule-prompts` | Things to ask the user: rules ready for auto-post, rules demoted, proposals waiting. |
| POST | `…/rules/api/rules/reorder/` | `rules:rule-reorder` | Put the book's rules in this order (ids first to last; any left out keep their order after). |
| POST | `…/rules/api/rules/test/` | `rules:rule-test` | What a draft rule would match now, how it would have done on history, and what it collides with. |
| GET | `…/rules/api/rules/{id}/` | `rules:rule-detail` | Retrieve one (rules). |
| PUT | `…/rules/api/rules/{id}/` | `rules:rule-detail` | Replace one (rules). |
| PATCH | `…/rules/api/rules/{id}/` | `rules:rule-detail` | Change part of one (rules). |
| DELETE | `…/rules/api/rules/{id}/` | `rules:rule-detail` | Delete one (rules). |
| POST | `…/rules/api/rules/{id}/apply/` | `rules:rule-apply` | Save and apply to N existing transactions: post this auto-post rule's current matches. |
| POST | `…/rules/api/rules/{id}/graduate/` | `rules:rule-graduate` | Answer "auto-post this from now on?": yes switches the rule to auto-post, no stops asking. |

#### Book: settings

| Method | Path | URL name | Purpose |
|---|---|---|---|
| GET | `…/settings/api/` | `books:api_settings` | This book's name, address, future-income setting, household size, report timeframe and closed period. |
| PATCH | `…/settings/api/` | `books:api_settings` | This book's name, address, future-income setting, household size, report timeframe and closed period. |

#### Book: ynab-import

| Method | Path | URL name | Purpose |
|---|---|---|---|
| POST | `…/ynab-import/api/apply/` | `ynab_import:api_apply` | Start the import (`choices`, when given, replace the saved ones). |
| POST | `…/ynab-import/api/preview/` | `ynab_import:api_preview` | What the import will produce, given the answers so far, checked against YNAB's own numbers. |
| GET | `…/ynab-import/api/state/` | `ynab_import:api_state` | Where the wizard opens. |
| GET | `…/ynab-import/api/status/` | `ynab_import:api_status` | Where the import has got to. |
| POST | `…/ynab-import/api/upload/` | `ynab_import:api_upload` | Take both exports, work out which is which, and hand back what we found. |

