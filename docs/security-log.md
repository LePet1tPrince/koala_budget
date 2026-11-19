# Security Log

## Open Issues

From the API-first migration review (2026-11-19, entry below). Each needs a product or deployment
decision, so none was changed.

- **S-WP10-08 (Medium) — Team delete has no confirmation, and fails for a team with data.**
  `DELETE /teams/api/teams/{id}/` (`TeamViewSet`, reachable since WP9 made it user-scoped; the Team
  settings page calls `teamsDestroy`) deletes a team and every book in it for any team admin, with
  no typed confirmation or re-authentication — unlike book delete (type the name) and account delete
  (password). Today a team with any ledger data answers 500 (`ProtectedError`: the books' PROTECT
  foreign keys; nothing is deleted), so only an empty team actually goes. Decide the confirmation
  (team name and/or password), then delete through a service that empties each book with `wipe_book`
  as `apps.users.services.delete_user_account` does.
- **S-WP10-09 (Medium) — Changing the sign-in email needs no re-authentication.** The profile page
  and `PATCH /users/api/profile/` send a confirmation link to the new address and switch to it once
  followed. Whoever holds a session or a session token can therefore move the account to their own
  address, then reset the password. Recommend allauth re-authentication (password or MFA) before an
  email change, on both paths.
- **S-WP10-10 (Medium) — The sign-in rate limit trusts `X-Forwarded-For`.**
  `AuthRateLimitMiddleware._get_client_ip` keys on the first `X-Forwarded-For` value, which the
  client chooses; rotating it defeats the 10-per-5-minutes limit on `/accounts/login/` and
  `/_allauth/.../auth/login`. Fix needs the deployment's proxy layout: key on the address the
  trusted proxy appends (the last hop it adds), or on `REMOTE_ADDR` when there is no proxy.
- **S-WP10-11 (Medium) — What an API key may do.** A key acts as its user on every endpoint listing
  `IsAuthenticatedOrHasUserAPIKey`: team rename/delete, invitations (create, edit, resend),
  membership role change and removal, book create/archive/delete/settings, Stripe sessions. A leaked
  key can invite an address its holder controls as an admin and so take over the team, though book
  data endpoints refuse keys. `apps/users/api_views.py` already keeps keys off account-level actions;
  decide whether team membership and destructive book/team actions should need the person too.
- **S-WP10-12 (Medium, not in this diff) — Bank feed CSV/Excel upload has no size limit.**
  `upload_parse`, `upload_preview` and `upload_validate_dates` (`apps/bank_feed/views.py`) read any
  size of file, and an `.xlsx` is a zip, so a decompression bomb reaches openpyxl. Recommend a cap
  (as YNAB/portability's 20 MB) and a decompressed-size check for Excel.
- **S-WP10-13 (Low, known) — The web invitation page doesn't verify email ownership.**
  `teams:accept_invitation` lets any signed-in user accept an invitation by its link; the API
  (`InvitationAcceptView`) requires the invited address, verified, on the account. Product decision.
- **S-WP10-14 (Low, known) — Web checkout allows any member.** `create_checkout_session`
  (`@login_and_team_required`) lets any team member start a Stripe checkout; the API and the portal
  are admin-only. Product decision.
- **S-WP10-15 (Low) — The web account-delete page asks only for the email.** `users:delete_account`
  deletes with the email typed out; the API also needs the password (or a recent re-authentication).
  Product decision whether the page should ask for the password.
- **S-WP10-16 (Low) — Members write list-shaped and create endpoints.** SEC-001 below (2026-09-23)
  now covers every migrated area: `BookModelAccessPermissions` limits only edits of an existing row
  to admins, so members can also create accounts/groups/payees, reorder the board, hide accounts and
  run batch feed edits. Consistent with the web pages (`@login_and_book_required`); still one
  decision for the role model.
- **S-WP10-17 (Low) — Throttle and audit gaps for programmatic clients.** The DRF user throttle
  (1000/hour) now counts every web page's data, since pages load through the API; a heavy session can
  see 429s. API-key writes are not attributed in `AuditLog` (the key's user is set in the DRF
  permission, after `AuditUserMiddleware`); the endpoints keys can reach log `AuditEvent`s from the
  request, so the practical gap is small.

## Resolved Issues

### 2026-11-19 — API-first migration (WP1–WP9, `git diff origin/develop...HEAD`)
**Feature:** Every screen's data through DRF (`docs/api-first-migration-plan.md`): phone session-token
auth, the API in the schema (227 operations), React islands on `api-client`, `json_script` data removed.
**Reviewed by:** WP10 (docs + security review).
**Verdict:** One Critical and one High, both pre-existing and fixed with regression tests; five
smaller fixes; ten items open above.

Fixed (commit, test):

- **S-WP10-01 (Critical) — Join any team through an edited invitation.** `InvitationSerializer.team`
  was writable on update and `InvitationViewSet` checked the team only on create. Anyone can create a
  team (and is its admin), invite their own address, `PATCH` the invitation's `team` to another
  team's id (sequential) with `role: admin`, then accept it (the web page or the new
  `teams:invitation_api`) and join that team as an admin. `perform_update` now refuses a team other
  than the URL's (400), and `is_accepted` is read-only. `36ec10f`; `InvitationEditTest`.
- **S-WP10-02 (High) — HTTP Basic auth skipped MFA and every rate limit.** `BasicAuthentication` was
  in `DEFAULT_AUTHENTICATION_CLASSES`: an email and password on any API request signed in without
  the second factor, outside `AuthRateLimitMiddleware`, and a failed attempt raised before DRF's
  throttles ran, so password guessing was unlimited. Removed (keys and session tokens remain);
  api-client regenerated. `c39238a`; `BasicAuthRefusedTest`.
- **S-WP10-03 (Medium) — Session tokens outlived a password change.** allauth's token lookup does not
  check the session auth hash, so a token issued before a password change or reset kept working
  while every cookie session ended. `apps.api.authentication.resolve_session_token` (middleware and
  DRF) checks it and flushes a stale token. `0a8865c`; `test_a_password_change_ends_the_token`.
- **S-WP10-04 (Medium) — allauth's `app` endpoints ignored a valid token.** `HijackUserMiddleware`
  wraps a copy of the user resolved from the empty cookie session, so allauth's re-evaluation inside
  `/_allauth/app/...` came back anonymous: the phone could not read its session, change its
  password, re-authenticate (which delete-account needs for passwordless users) or manage MFA.
  `HeadlessAppUserMiddleware`, after hijack. `0a8865c`;
  `test_a_password_changed_through_the_token_hands_back_a_new_one`.
- **S-WP10-05 (Medium) — Zip bomb in the data import.** `portability.services.read.read_archive` read
  every member whole; a 20 MB upload could expand to gigabytes in the web worker (any user can be a
  book admin of their own team). Refused above 300 MB declared uncompressed size (zipfile never reads
  past the declared size). `b407f89`; `test_an_archive_that_decompresses_past_the_cap_is_refused`.
- **S-WP10-06 (Low) — Delete-account as a password oracle.** `POST /users/api/delete-account/`
  checks the password under the general 1000/hour throttle; now scoped `password_check`, 10/hour.
  `c39238a`; `test_password_guesses_are_throttled`.
- **S-WP10-07 (Low) — An edit could mark an invitation accepted.** Part of S-WP10-01's fix.

Checked, and what the code does about it:

- **Token middleware.** `SessionTokenMiddleware` sits right after `AuthenticationMiddleware`, before
  `AuditUserMiddleware`, `TeamsMiddleware` and `BooksMiddleware`, so audit rows, membership and the
  remembered book follow the token's user (tests: `test_token_writes_without_csrf_and_the_audit_row_names_the_user`,
  `test_token_plain_form_post_skips_csrf_and_is_audited_as_the_user`). CSRF is waived
  (`_dont_enforce_csrf_checks`) only after a header token resolved; a request already signed in by
  cookie is returned untouched, and DRF's `SessionTokenAuthentication` defers to the cookie the same
  way (`test_a_cookie_session_wins_over_a_token_and_keeps_csrf`, `test_a_session_post_without_csrf_is_still_refused`).
  A bad token is a 401 on DRF and anonymous on pages. No `Set-Cookie` carries the token session.
  `X-Session-Token` is not in `CORS_ALLOW_HEADERS`, so no other origin's page can send one.
- **Book isolation.** `test_every_book_url_is_covered` passes: every book URL is in a table of
  `apps/books/tests/test_isolation.py`. Every DRF view under `/a/{team}/{book}/` was enumerated
  from the URLconf: each has `BookAccessPermissions`, `BookModelAccessPermissions`,
  `BookAdminWritePermissions` or `BookAdminPermissions`. Ids taken from a body or query were traced
  to a book filter: budget categories (`budgeted_categories(book)`), autofill `category_ids`
  (intersected with the book's), cover `goal_id`, goal link rows (`Account.filter(book)`),
  contribution lines and goal links (`filter(book=...)`), accounts' `BookRowField`s and board
  reorder/set-hidden, reconciliation `?account=`, rules' `BookAccountField`, the journal
  serializers' scoped querysets, Plaid account mapping (`Account.for_book`), YNAB/portability
  import records (`record(book, id)`), recurring schedules, audit events (the book's, or the team's
  own with no book).
- **Team endpoints.** `TeamViewSet` (WP9) lists only the user's teams; object writes need an admin;
  an outsider's team is a 404 (`TeamViewSetTest`). Memberships: admins change others' roles, nobody
  their own, members may leave, the last admin can't be removed (`services/memberships.py`, shared
  with the pages). The invitation-accept API requires the invited address, verified, on the
  account, and refuses API keys.
- **Destructive actions.** API account delete: the email typed out plus the password, or a recent
  re-authentication for a passwordless account; signs out first. Book archive/delete: admins, the
  book's name typed out, never the team's last open book. Team delete: S-WP10-08 (open).
- **Uploads.** Avatar: image extension and 5 MB (`validate_profile_picture`; extension, not content,
  is checked — accepted, Low: stored and served as a profile image only). YNAB: 20 MB a file, first
  four parts, stdlib `csv`. Portability: 20 MB, now 300 MB uncompressed, book admins only.
  Bank-feed CSV/Excel: S-WP10-12 (open).
- **`celery-progress/` URLs removed (WP9).** They answered any task's state and result to anyone
  holding its id, unauthenticated. Import progress is now the book-scoped `ynab_import:api_status` /
  `portability:api_status`.
- **Audit-log stored XSS (WP9).** The old inline template put user names and event metadata into
  `innerHTML`; `assets/javascript/audit/audit-log.js` sets every value with `textContent`. Other new
  `innerHTML` uses were checked: a static spinner, and the goal form's preview (numbers through
  `escapeHtml`).
- **Admin-only.** Book settings: `BookAdminPermissions` (non-admin 404). Book create/archive/restore/
  delete: `TeamAdminWritePermissions` (member 403). Stripe checkout and portal:
  `TeamAdminPermissions` (`apps/subscriptions/tests/test_api.py`). Data import: `BookAdminPermissions`.

### 2026-11-05 — Recurring transactions (`apps.bank_feed` `RecurringTransaction`)
**Feature:** "Make recurring" on Add Transaction; occurrences written to the feed on their dates (nightly task, bank feed page open, and at creation); list + Stop page.
**Verdict:** No Critical or High findings.

- **Book scoping.** The schedule's account and category are resolved through `Account.for_book` at creation. Occurrences are written under `current_book(rule.book)`, so split legs re-resolve through the book-scoped manager, and a single category is used only when `category.book_id == rule.book_id`. List and Stop filter by `request.book`; another book's id is a 404 (isolation tables: `bank_feed:recurring_list` in READS, `bank_feed:recurring_delete` in OBJECTS).
- **Who may act.** Any team member may start a schedule (as with creating a feed transaction) and stop one (`@login_and_book_required`). Stop is POST-only with `{% csrf_token %}`; it deletes only the schedule, never the rows it wrote.
- **Write amplification.** A schedule may start at most 366 days back, and one pass writes at most 400 occurrences per schedule, so creation or a page load is bounded. Overlapping passes cannot double-write: `materialize` holds `select_for_update` on the schedule row and re-reads `next_date` under it.
- **Invalid templates.** A category deleted, turned into a budget bucket, or a split no longer valid writes the occurrence uncategorized (logged) — never a refused category, never a crash that halts other schedules (`materialize_due` isolates each).
- **Output.** Payee/description render autoescaped; the Stop confirm text goes through `escapejs`.

**Accepted, low:** `bank_feed_home` (a GET) writes due occurrences for its own book. The write takes no request input and is idempotent per date.

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

### 2026-09-23 — Editable transactions on the Transactions page
**Feature:** Edit, split, delete and void a journal entry from `/a/{slug}/journal/transactions/`.
**Verdict:** No Critical or High findings. One accepted Medium, recorded below.

Checked, and what the design does about it:

- **Book scoping.** Every write loads its entries through `TransactionViewSet.editable_queryset()`, which is `JournalEntry.for_book` — never a lookup by id alone. An id the team cannot see refuses the *whole* batch rather than being skipped, so a request cannot be used to probe which ids exist by watching which ones "worked" (`test_another_teams_id_is_refused_not_edited`).
- **Account references.** `account_id`, `category_id` and every split leg's category are resolved with an explicit `Account.objects.filter(book=book, ...)`, not through the ambient `for_book` manager. Another book's account reads as *"That category no longer exists."* — the same message a deleted one gets — rather than a refusal that confirms it exists.
- **Client input is a partial edit, not a ledger.** The client never sends debit and credit amounts. It sends a signed total and, optionally, legs; `apps.bank_feed.services.splits.write_lines` decides which side each amount lands on and refuses to write an entry that does not balance. So a crafted payload cannot produce an unbalanced entry, and cannot set `is_reconciled`, `is_cleared`, `budget` or `source` at all — none is in the request serializer.
- **Destructive actions are asked for, never inferred.** Collapsing a split requires `remove_split`; deleting requires the id list; voiding requires an explicit status. A payload that merely omits `splits` is refused rather than being read as "drop the apportionment".
- **Reconciled data.** Amount and account changes, re-dating past a statement, deletion and voiding are all refused through `apps.reconciliation.services.guards` — the same functions the Bank Feed and the journal API call, so one rule covers every write path. Enforced in the service, not just hidden in the modal, and the modal's capability flags are computed from the same predicates so the two cannot disagree.
- **System accounts.** A bookkeeping account (the equity account opening balances and reconciliation adjustments post to) is refused as a category via `assert_category_allowed`, with `keep_ids` so re-saving an existing adjustment untouched still works.
- **Audit.** Lines are mutated in place rather than deleted and recreated, so the row-level `AuditLog` records a field diff a reader can follow; a multi-row edit also writes one `AuditEvent.BULK_EDIT` with the fields touched.

**SEC-001 (Medium, accepted):** `BookModelAccessPermissions.has_object_permission` — which restricts writes to team admins — is only consulted by DRF on *detail* routes. `transactions/edit/`, `transactions/batch_delete/` and `transactions/batch_status/` are list-shaped actions, so they fall through to `has_permission`, which admits any authenticated member of the book's team. This matches `BankFeedViewSet.batch_edit`, `batch_archive` and `batch_delete`, which have behaved this way since the feed shipped, so it is the app's existing posture rather than a new gap — a member who can already recategorize in the Bank Feed can now do the same here. Worth revisiting as one decision across both apps: if transaction writes should be admin-only, the check belongs in a shared permission class, not bolted onto one viewset.

**Cross-book isolation is enforced by test, not by inspection.** All four endpoints are registered in `apps/books/tests/test_isolation.py` — the detail route in `OBJECTS` (another book's id must 404) and the three writes in `WRITES` (naming another book's rows must leave that book byte-identical). `test_every_book_url_is_covered` fails the suite for any new book URL that is in none of those tables, so this cannot be forgotten on the next endpoint.
