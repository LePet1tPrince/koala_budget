# Plaid overhaul (Oct 2026)

Investigation and overhaul of the Plaid integration (`apps/plaid/`), on branch
`claude/plaid-overhaul`. Each fix is its own commit; this page says what was
found, what changed, and what was deliberately left.

## How sync works now

```
Plaid webhook ──verify JWT──► plaid_webhook_view ──► sync_plaid_transactions.delay(item)
Refresh button ──────────────► items/{id}/sync/    ──►            "
Hourly beat (minute 23) ─────► sync_all_plaid_items ─► stale items, staggered, scheduled=True

sync_plaid_transactions(item):
  claim the item's sync lock ─ busy? webhook/manual: ask the runner to go again; scheduled: skip
  fetch every /transactions/sync page from the saved cursor
      (TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION → restart from the saved cursor, ≤3×)
  one transaction: added → modified → removed, then the cursor (only if unchanged since start)
  item error (ITEM_LOGIN_REQUIRED …) → record on PlaidItem.status, return; don't raise
  release the lock ─ a rerun was requested? go round again (≤3×)
```

## Required outcomes

### 1. Canadian banks — fixed (`0fa11b2`, `d377567`)

| Found | Fix |
|---|---|
| `create_link_token` offered `country_codes=["US"]` only | `PLAID_COUNTRY_CODES` (default `CA,US`) |
| `get_institution` looked institutions up as US, so a Canadian bank was "not found" **after** the token exchange, failing the whole link with the item already created at Plaid | Same setting; a failed lookup falls back to Link's own institution name |
| Link language hard-coded `en` | Follows the user's active language when Plaid supports it (`PLAID_LINK_LANGUAGES`, default `en,fr`) |
| **The link token carried no `webhook`**, so Plaid never sent this app a webhook: items only ever synced on Refresh | `PLAID_WEBHOOK_URL`, else derived from the Site domain |
| No `redirect_uri` (needed by OAuth institutions) | `PLAID_REDIRECT_URI` (blank sends none) |
| Plaid's default 90 days of history | `PLAID_TRANSACTIONS_DAYS_REQUESTED` (default 730) |
| `iso_currency_code` stored, never read: a USD account in Canadian books summed US dollars as Canadian | `BASE_CURRENCY` (default `CAD`); `PlaidAccount.iso_currency_code` from the account's balances; feed rows carry `currency`/`is_foreign_currency`; the Inbox tags a foreign amount and the mapper warns. **Nothing converts** (see Left) |

Products: only `transactions` is requested, and it is available in CA. Nothing
the app uses is US-only.

### 2. Scheduled sync — built (`20928ab`, `9cee9d4`)

- `SCHEDULED_TASKS["plaid-sync-catch-up"]` runs `sync_all_plaid_items` hourly at
  minute 23. It queues only non-archived items not synced in
  `PLAID_SCHEDULED_SYNC_MIN_AGE_HOURS` (6), stalest first, at most
  `PLAID_SCHEDULED_SYNC_BATCH_SIZE` (500) per run, `PLAID_SCHEDULED_SYNC_STAGGER_SECONDS`
  (2 s) apart, and skips items waiting on the user (`login_required`, `revoked`).
- **Lock** (`apps/plaid/sync_lock.py`): `PlaidItem.sync_lock_until`, claimed with one
  conditional `UPDATE`, expiring after 15 min so a killed worker can't hold an
  item. A scheduled sync skips a busy item; a webhook or Refresh sets
  `sync_requested` and the running sync goes round again, so data that arrived
  mid-sync isn't missed. Release and the rerun check are one `UPDATE`.
- `bootstrap_celery_tasks` was broken (popped `schedule` out of the settings
  dict itself; crashed on an invalid schedule) and **nothing ran it on deploy**,
  so no `SCHEDULED_TASKS` entry ever reached celery beat's `DatabaseScheduler`.
  Fixed, and `docker_startup.sh` now runs it after `migrate`.

### 3. Pending → posted — built (`0de9c52`, `84d2005`, `aa14e78`)

The handler is bank-agnostic: `apps/bank_feed/services/bank_revision.py::revise(bank_tx, Revision)`
carries a bank's new figures onto an existing feed row. Plaid's side is
`apps/plaid/tasks.py` (`settle_pending`, `process_modified_transaction`,
`process_removed_transaction`). Decisions, each tested in `apps/plaid/tests/test_pending.py`:

| Case | What happens |
|---|---|
| Posted transaction names a pending one (`pending_transaction_id`) | The pending row **becomes** the posted one: takes the posted id (so the pending id's removal finds nothing), amount and date. No second row. |
| …row categorized | Category kept; entry re-amounted through `splits.write_lines`; entry re-dated |
| …row's description/payee | Kept on a categorized row (the user may have edited them); an uncategorized row takes the bank's wording |
| Amount changed, a reconciled line on either side (incl. a transfer's other side) | Row keeps its amount. The **difference** arrives as its own uncategorized row on the same account (`raw.revision_of`), so the balance matches the bank once it is categorized and nothing confirmed moves. A later revision adjusts that row; agreeing again deletes it |
| Amount changed on a **split** | Same difference row — there is no honest way to re-apportion the user's legs |
| Re-date past a reconciled statement | Date kept (`assert_date_change_allowed`) |
| Transfer to another feed account | Mirror leg follows amount and date (`sync_transfer`) |
| `modified` on a categorized row | Now revised (it was skipped, so an amended amount never reached the ledger) |
| Cancelled authorization (`removed`, no replacement) | Uncategorized: deleted. Categorized: **voided** with any difference rows (stays in the Voided view; restorable). Reconciled: kept, logged |
| Pending row the user voided, then it settles | Not revived; the posted transaction arrives as a new row |
| Removal arrives on an earlier page than the posted transaction | Fine: every page is read first, and `added` is applied before `removed` |

The sync previously applied each page as it arrived and saved the cursor
outside any transaction; now rows and cursor commit together, and
`MUTATION_DURING_PAGINATION` restarts the read. `PLAID_SYNC_COMPLETED` audit
metadata carries per-outcome counts (`settled`, `revised`, `removed_voided`, …).

The Inbox shows a **Pending** badge (the flag was in the API and unused).

## Other findings

| Area | Found | Done |
|---|---|---|
| Null category | `personal_finance_category: null` raised and failed every later sync | Fixed (`b437b7c`, cherry-picked) |
| **Account mapper** | The exchange response schema declared only `success`, so the generated client dropped `accounts`: the mapper opened empty, Save was enabled (0 of 0), and every newly linked account stayed unmapped | Real response serializer; client regenerated; mapping refused for non asset/liability accounts and for a ledger account another Plaid account already feeds; mapping turns the account's feed on (`ad38ada`) |
| Unmapped accounts | Their transactions were skipped and the cursor moved past them, so mapping later never imported history. Refresh 400'd any item with one unmapped account | Mapping clears the cursor and queues a sync (re-delivery, deduped by id); a sync saves its cursor only if unchanged since it started; `PlaidAccount.is_ignored` ("Don't import"); Inbox alert "N accounts not imported yet" → mapper; Refresh no longer refused (`52affae`) |
| Webhook security | No verification | ES256 JWT verified against Plaid's key (cached, expiry checked), 5-minute replay window, body SHA-256 in constant time; 400 otherwise. `PLAID_VERIFY_WEBHOOKS` only for local dev (`bead7f0`) |
| Access tokens | Plaintext | `EncryptedTextField` (Fernet, `FIELD_ENCRYPTION_KEY`, comma-separated keys rotate); migration encrypts existing, reverse decrypts; admin no longer shows it (`06979f6`) |
| Item errors | Only logged; a login-required item failed and raised on every sync | `PlaidItem.status` + `error_code`/`error_message`/`consent_expiration_time`/`new_accounts_available` from ITEM webhooks (`ERROR`, `PENDING_EXPIRATION`, `PENDING_DISCONNECT`, `USER_PERMISSION_REVOKED`, `LOGIN_REPAIRED` → sync, `NEW_ACCOUNTS_AVAILABLE`) and sync errors; audited (`PLAID_ITEM_STATUS_CHANGED`) (`4bf130a`) |
| Link update mode | None — repairing a connection meant linking again (duplicating every transaction) | `items/{id}/link-token/` (access token, account selection when new accounts exist), `items/{id}/refresh/` (adds shared accounts for mapping, marks healthy, syncs); Inbox Reconnect / Add accounts alerts |
| Duplicate links | Linking the same login twice imported everything twice and doubled Plaid's bill | `PlaidItem.institution_id`; refused (409) **before** the exchange when institution + an account's name/mask match (`b80259a`) |
| Failed link | `@transaction.atomic` with every exception caught: a failure after the item row was written kept a half-linked item; the item at Plaid was never removed | `linking.link_item`: Plaid calls first, one atomic write, `/item/remove` on failure |
| Item removal | No way to disconnect; `wipe_book` (import-replace, book delete, account delete) deleted items without removing them at Plaid (still billed, still sending webhooks) | `items/{id}/remove/` + Disconnect button; `post_delete` signal removes at Plaid on commit for every path (`629ef91`) |
| Permissions | Members could link a bank (`create_link_token`/exchange checked membership only) but not map, sync or remove it (object check: admins edit) | `BookAdminWritePermissions` on both link endpoints (`6dc8ae2`) |
| Account PATCH | Every field writable: `item`, `plaid_account_id`, `name`, `mask` could be rewritten, detaching the account from its transactions | Only `account`/`is_ignored` writable (`931bb64`) |
| `PLAID_ENV` | Documented as `sandbox/development/production`, used as a URL (`settings_e2e`'s `"sandbox"` was an invalid host) | Accepts a name or a URL; refuses retired `development` (`f076dd4`) |
| Uniqueness across books | `plaid_item_id`, `plaid_account_id`, `plaid_transaction_id` are globally unique | **Correct as is.** Plaid issues ids per item, and every Link session creates a new item, so two books linking the same bank get distinct ids. The duplicate check is per book |
| Isolation | — | New routes `plaid-item-link-token`, `plaid-item-refresh`, `plaid-item-remove` in the `OBJECTS` table |
| API client | Missing `institutionName`, exchange `accounts` | Regenerated with openapi-generator 7.9.0 at each endpoint change |

Coverage: `apps/plaid` 96% (tasks 96%, views 96%, services 99%; `bank_revision.py` 97%;
was 17% / 67% / 33%). Backend suite 2,138 tests (was 2,007); `e2e/tests/test_bank_feed.py`
44 tests, all passing.

## Deliberately left — needs the owner

- **Plaid dashboard (code can't change these):** enable **Canada** (and US) for
  the client in production; apply for Production access covering CA; register
  `PLAID_REDIRECT_URI` under *Allowed redirect URIs*; set the webhook URL only if
  `PLAID_WEBHOOK_URL` can't be derived from the Site domain. Plaid bills per item,
  so decide the pricing impact of `PLAID_TRANSACTIONS_DAYS_REQUESTED=730`.
- **OAuth redirect page.** `PLAID_REDIRECT_URI` is sent, but there is no page
  that resumes Link with `receivedRedirectUri`. OAuth institutions need one
  before `PLAID_REDIRECT_URI` is set; leave it blank until then (those banks then
  fall back to non-OAuth or aren't offered).
- **`FIELD_ENCRYPTION_KEY`** must be set in production to a real Fernet key; the
  default derives from `SECRET_KEY`, so rotating `SECRET_KEY` without it would make
  every token undecryptable (it fails loudly, not silently).
- **No currency conversion.** Foreign-currency accounts are flagged, not
  converted, and there is no per-book currency (`BASE_CURRENCY` is global). A
  converted figure would not reconcile against the bank's statement; doing it
  properly needs an FX source and a per-book currency.
- **Cross-source duplicates.** Linking a bank after a CSV or YNAB import of the
  same account imports the overlapping dates again; Plaid rows are deduped only
  against Plaid ids. Matching needs date/amount/description heuristics and a
  review step (the transfer-match UI is a model).
- **Portability.** An export carries Plaid feed rows but not their
  `PlaidTransaction`, and import replaces (and now removes at Plaid) the target
  book's items; re-linking the bank in the imported book re-imports its history.
- **`USER_ACCOUNT_REVOKED`** (one account revoked) is ignored; the item stays healthy.
- **Rate limits** (`RATE_LIMIT_EXCEEDED`) still raise; the hourly catch-up retries.
- Behaviour changes worth knowing: a cancelled categorized authorization is now
  **voided** (it used to stay live); members can no longer link banks.
