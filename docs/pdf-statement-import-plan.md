# PDF bank statement import — plan

Extend the Inbox's CSV upload wizard so a user can drop in a **PDF bank or credit-card statement** and get the same
result as a CSV: reviewed `BankTransaction` rows in the selected account's feed, with duplicates flagged, and nothing
written until they confirm.

Status: plan. Nothing here is built.

---

## 1. Principles

1. **The statement checks itself.** A PDF statement prints an opening balance, a closing balance and usually a running
   balance per row. `opening ± Σ rows = closing` is a deterministic gate on whatever the extractor produced. A missed,
   doubled or wrong-signed row fails it. The LLM is never trusted on its own: its output is validated and balanced, then
   the user reviews it.
2. **Extraction is one stage, and it can be swapped.** `bytes → StatementExtraction` (header + rows) is the only
   non-deterministic step. Everything after it is pure, testable code that doesn't know how the rows were read.
3. **The wizard's back half is shared.** Duplicate review, preview, confirm and the import itself are the CSV wizard's
   existing steps and endpoints. A PDF skips only the steps a PDF doesn't need: column mapping and category mapping.
4. **Nothing is written until confirm**, same as CSV. Extraction results are held on a staging row, not in the feed.
5. **The statement is sensitive data.** Store as little as possible, for as short a time as possible, and tell the
   user before any of it leaves the server.

---

## 2. User flow

Inbox → select account → **Upload** (existing button, `CSVUploadWizard`).

| # | Step | CSV today | PDF |
|---|------|-----------|-----|
| 1 | Upload | `.csv,.xls,.xlsx` | also `.pdf`. Before upload: a one-line disclosure that the statement is read by an AI service |
| 2 | Map Columns | yes | **skipped** |
| 2p | **Reading statement** | — | progress bar (Celery task); page *n* of *N* |
| 3p | **Check statement** | — | statement header, balance check, an editable row table (§6) |
| 3 | Map Categories | yes | **skipped**: statements carry no category column. Rows land uncategorized; categorize mode's similar-transaction suggestions handle them |
| 4 | Review Duplicates | yes, when any | yes, when any (reused) |
| 5 | Preview / Import | yes | yes (reused), plus an optional checkbox: **"Start reconciling this statement"** (§8) |

The step indicator is already built from a list (`CSVUploadWizard.jsx` `steps`), so the PDF branch adds its entries
and drops Map Columns and Map Categories.

---

## 3. Extraction pipeline

`apps/bank_feed/services/pdf_statement/` (new package):

```
validate.py   magic bytes, size, page count, encryption → PdfRejected(message)
text.py       per-page text layer (pdfplumber, layout=True); classifies each page text|scanned
schema.py     pydantic models the LLM must return (StatementHeader, StatementRow, PageResult)
llm.py        pydantic-ai Agent(output_type=PageResult); text path and document path
dates.py      resolve_year(date_text, period_start, period_end); pure
checks.py     balance check, running-balance walk, printed-totals check, hints; pure
extract.py    orchestration: validate → text → per-page LLM → merge → dates → checks → StatementExtraction
```

### 3.1 Text layer first, document input as fallback

- **Text-layer PDFs** (downloaded from online banking, the common case): `pdfplumber` `extract_text(layout=True)` per
  page. Layout mode keeps the column alignment, which makes the LLM's job reading a table rather than guessing at one.
  Pure Python, no system packages, so it works on the `python:3.12-slim` image.
- **Scanned / image PDFs:** a page with fewer than ~50 non-whitespace characters is treated as scanned. That page is sent
  to the model as a document/image (`BinaryContent`) instead of as text. There is **no local OCR** (no tesseract/poppler
  in `Dockerfile.web`). The configured model must accept PDF/document input for this path. If it can't, the upload
  is refused with "This statement is a scanned image; download the PDF from online banking instead."

### 3.2 Chunking

A statement is split per page. **Page 1 and the last page** are asked for the header too (period, opening and closing
balances, printed totals). Every page is asked for its rows. Pages run concurrently (bounded, e.g. 4) inside the Celery
task. The benefits:

- Output size per call stays small; a 30-page card statement never hits an output-token ceiling.
- Progress is real (`pages_done / pages`), reported through `apps/utils/progress.py::ProgressChannel`, like the YNAB
  and portability imports.
- A failed page is retried alone (pydantic-ai `retries=2` on validation failure) rather than restarting the statement.

### 3.3 Output schema (what the model must return)

```python
class StatementRow(BaseModel):
    date_text: str                      # exactly as printed ("Mar 04", "04/03")
    date: date | None                   # model's reading; server re-resolves the year (§3.4)
    description: str
    amount: Decimal = Field(gt=0)       # magnitude only
    direction: Literal["out", "in"]     # relative to the account holder: purchase/withdrawal/fee = out
    running_balance: Decimal | None     # as printed, statement sign
    
class StatementHeader(BaseModel):
    institution: str | None
    account_name: str | None
    account_last4: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None     # statement sign (a card prints balance owed as positive)
    closing_balance: Decimal | None
    total_in: Decimal | None            # printed totals, when present
    total_out: Decimal | None
    currency: str | None

class PageResult(BaseModel):
    header: StatementHeader | None      # only requested on first/last page
    rows: list[StatementRow]
```

**Magnitude + direction, never a signed amount.** Banks disagree on the sign of everything (the CSV wizard needed a
"Swap + and −" box for this reason), and "out/in from the holder's point of view" is the same question for a chequing
account and a card. The server converts to the app convention (positive = outflow) in one place.

The prompt tells the model to leave out non-transactions: "balance forward", page subtotals, interest-rate tables,
and repeated headers. A server-side filter backs this up by dropping rows whose description matches balance-forward
patterns.

### 3.4 Dates

Statements often print `Mar 04` with no year, and a December–January statement spans two years.
`dates.resolve_year()` picks the year that puts the date inside `[period_start − 7d, period_end + 7d]`. The model's
`date` is used only when `date_text` carries a year. A row whose date can't be placed inside the period window is
flagged `error_field="date"`, reusing the CSV preview's error vocabulary.

### 3.5 Model configuration

New settings, beside the existing `DEFAULT_AGENT_MODEL`:

```python
STATEMENT_EXTRACTION_MODEL = env("STATEMENT_EXTRACTION_MODEL", default=DEFAULT_AGENT_MODEL)  # pydantic-ai model string
STATEMENT_PDF_MAX_BYTES = 10 * 1024 * 1024
STATEMENT_PDF_MAX_PAGES = 40
STATEMENT_PDF_PAGES_PER_MONTH = 200     # per book; see §9
```

`STATEMENT_EXTRACTION_MODEL = "test"` selects a pydantic-ai `FunctionModel` that returns canned JSON fixtures keyed
by file sha256. Unit tests and E2E use it, so neither ever calls a provider.

---

## 4. The integrity gate (`checks.py`, pure)

Work in **ledger sign**, using the selected account's type. Don't use the model's guess at the account kind.
`apps/reconciliation/services/signs.py::to_ledger` already does the conversion, so a card's positive "balance owed"
and a chequing account's positive balance fall out of the same equation:

```
app_amount(row)   = +amount if direction == "out" else −amount      # positive = outflow
expected_change   = −Σ app_amount
balanced          ⇔ to_ledger(closing) − to_ledger(opening) == expected_change   (to the cent)
```

Returned as `StatementCheck`:

| Field | Meaning |
|-------|---------|
| `status` | `balanced` · `off` · `unverifiable` (no opening/closing found) |
| `difference` | statement-sign amount the rows are off by |
| `flagged_rows` | rows the checks below point at |
| `hints` | plain-language suggestions, capped at 5 |

The checks, in order:

1. **Running-balance walk.** When rows carry `running_balance`, walk them. The first row where
   `prev_balance ± amount ≠ printed balance` is flagged; that is almost always the misread or missing row. The walk
   also catches a row the model put on the wrong page or in the wrong order.
2. **Printed totals.** If `total_in`/`total_out` were found, compare them with Σ in / Σ out separately. This says
   which side is wrong.
3. **Difference hints** (same pure heuristics as `apps/reconciliation/services/diagnose.py`):
   - difference = 2 × a row's amount → that row's direction is probably flipped.
   - difference divisible by 9 → possible transposed digits.
   - difference equals one row's amount → possible duplicate.
   - difference equals no row's amount → possibly a missing row. Name the gap between running balances if one exists.
4. **Period.** Rows outside the period window (§3.4).
5. **Cross-page duplicates.** The same date + amount + description on adjacent pages (a row repeated at a page break).

The client recomputes `balanced`/`difference` live as the user edits rows (§6), using the same formula. The server
recomputes on preview and confirm, and the server's answer is the one that counts.

---

## 5. Data model

`apps/bank_feed/models.py::StatementUpload(BaseBookModel)`. It follows `YnabImport`/portability's pattern: the web
and Celery containers don't share a filesystem on DigitalOcean App Platform, so the upload lives in the database, not
`MEDIA_ROOT`.

| Field | Notes |
|-------|-------|
| `account` | FK `Account` (the feed account the wizard was opened on) |
| `filename`, `sha256`, `page_count`, `byte_size` | |
| `pdf` | `BinaryField`, **cleared** on import, on discard, or after 24h (§9) |
| `status` | `uploaded` · `extracting` · `ready` · `failed` · `imported` · `discarded` |
| `task_id`, `progress`, `started_at` | same semantics as `YnabImport` (clamped-to-99 while running, dead-worker detection) |
| `extraction` | `JSONField`: header + rows + per-page mode (`text`/`document`) |
| `check` | `JSONField`: last `StatementCheck` |
| `model_name`, `input_tokens`, `output_tokens` | cost accounting |
| `error` | user-facing message on failure |
| `imported_count`, `imported_at`, `created_by` | |

`BankTransaction.SOURCE_PDF = "pdf"` ("PDF statement"). `journal_source` maps it to `JournalEntry.SOURCE_IMPORT`,
like CSV. Each row keeps `raw = {"pdf": {"upload": id, "page": n, "date_text": …}}`. Migrations: the new model, plus
a choices-only migration on `BankTransaction.source`.

New `AuditEvent` types (audit migration): `PDF_STATEMENT_UPLOADED`, `PDF_STATEMENT_EXTRACTED` (pages, rows, status,
model, tokens), `PDF_STATEMENT_FAILED`. The import itself keeps using the existing `CSV_UPLOAD_*` events with
`metadata.source="pdf"`, since it is the same writer.

**Portability:** `StatementUpload` is staging, not books. Leave it out of the export and list it in
`apps/portability/services/schema.py`'s documented omissions so `test_schema.py` keeps passing.

---

## 6. Backend: endpoints and the shared tail

### 6.1 New viewset: `StatementUploadViewSet` at `bankfeed/api/statements/`

`BookModelAccessPermissions` applies throughout; the queryset is `StatementUpload.for_book`.

| Method | Path | Does |
|--------|------|------|
| POST | `statements/` | multipart `file`, `account_id`. Runs `validate.py`, refuses a same-sha256 upload already imported into this book ("You imported this statement on {date}"), checks the quota, creates the row, queues the task. → `{id, status}` |
| GET | `statements/{id}/` | status, progress, eta, header, rows, check (the Reading step polls this) |
| POST | `statements/{id}/preview/` | body: the user's edited rows. Re-runs `checks.py` and duplicate flagging. → `UploadPreviewResponseSerializer` shape plus `check` |
| POST | `statements/{id}/discard/` | clears bytes and rows; status `discarded` |

All four go in `apps/books/tests/test_isolation.py`: create/preview/discard in `WRITES`, detail in `OBJECTS`.

### 6.2 Refactor `csv_upload.py` so both sources share one tail

Today `preview_transactions()` re-reads the file on every call and does parsing, duplicate flagging and category
aggregation in one loop. Split it:

- `rows_from_file(file, filename, column_mapping, date_format) → list[ParsedTransaction]` (CSV/Excel only)
- `flag_duplicates(transactions, book, account_id, *, fuzzy_days=0) → duplicate_count` (shared)
- `aggregate_unmapped_categories(...)` (CSV only)

`preview_transactions()` becomes composition over these, so its behaviour and tests are unchanged.

**Duplicate rule for PDF: `fuzzy_days=3`, exact amount, description ignored.** The CSV rule (same date + amount +
iexact description) misses the obvious case. A PDF row "AMAZON.CA*2K4" posted Mar 4 is the same transaction as the
Plaid row "Amazon" dated Mar 3. Match one-to-one, closest date first (the greedy pattern in
`transfer_detection.py`), so two identical $5 coffees on the statement don't both claim one existing row.

### 6.3 Confirm

Reuse `upload_confirm`/`create_transactions`, with two optional fields added to `UploadConfirmRequestSerializer`:

- `statement_upload_id`: sets `source=SOURCE_PDF` and `raw`. After the last batch, the client posts `statements/{id}/`
  completion (or the confirm endpoint marks it when `final=true`), which marks the upload `imported` and clears
  `pdf`/`extraction`, keeping header + counts for the audit trail.
- `start_reconciliation` (§8).

The unbalanced policy is enforced here (decision D2 in §12): if the latest server-side check is `off`, confirm
requires `acknowledge_difference` equal to the current difference. This is the same "you saw this number" guard as
reconciliation's `finish(adjust=True, expected_difference=…)`.

### 6.4 Celery task

`apps/bank_feed/tasks.py::extract_statement(upload_id)`: sets the book context var (and resets it, as the Plaid sync
task does), runs `extract.py`, and writes `extraction`/`check`/tokens/status. Progress goes to a `ProgressChannel`
subclass bound to `StatementUpload`. A failure message names the page ("Couldn't read page 7").

---

## 7. Frontend

In `assets/javascript/bank_feed/react/CSVUploadWizard/`:

- **`Step1FileUpload.jsx`** — `accept` gains `.pdf` and `application/pdf`. For a PDF, the wizard calls
  `statementsCreate` instead of `uploadParse` and branches. The AI disclosure line sits under the drop zone and is
  always visible, not buried in a tooltip.
- **`StepReadStatement.jsx`** (new) — progress bar, polling `statements/{id}/`. It reuses `Step6Apply.jsx`'s rules
  (monotonic bar, gentle creep, "nothing has picked this up" after 12s naming the background worker).
- **`StepCheckStatement.jsx`** (new) — the core screen:
  - Header card: institution · account ····1234 · period, then Opening → Closing and a status badge: **Balanced**
    (success), **Off by $X** (error), **Can't verify** (warning, no balances found).
  - Hints list (§4), each hint scrolling to and flashing its row (`.feed-row-flash`).
  - Row table: page · date (`DateField`) · description · Money out / Money in (`AmountInput`, twin boxes that clear
    each other, as in the edit modals) · running balance · delete. Flagged rows are tinted; an "Add row" row sits at
    the bottom. The balance check recomputes live on every edit.
  - **"View page n"** opens `URL.createObjectURL(file) + '#page=n'` from the `File` still held in the browser, so the
    user can compare against the original with no server round trip and no stored copy.
  - Continue → `statements/{id}/preview/` → Duplicates (if any) → Preview.
- `Step4DuplicateReview.jsx` and `Step5Preview.jsx` are reused unchanged. Preview gains the reconciliation checkbox
  and, when unbalanced, the acknowledgement.
- API helpers: add to `getBatchOperationsApi` in `bank_feed.js`, and regenerate `api-client/`
  (`manage.py spectacular` + generator).

---

## 8. Reconciliation hand-off

The statement already carries what `apps/reconciliation/services/session.py::start()` needs: `statement_date =
period_end` and `statement_balance = closing_balance` (statement sign, which is what `start` expects). When the user
ticks "Start reconciling this statement" and the check is `balanced`, confirm calls:

```python
start(account, period_end, closing_balance, user, preselect_line_ids=…)
```

`preselect_line_ids` is empty: the imported rows are uncategorized, so they have no journal lines yet. The redirect
target is the reconcile workspace. The user categorizes the rows in the Inbox; each row then has a line, and the
workspace's live difference guides the rest. If a draft is already open for the account, `start` joins it, which is
already the correct behaviour.

This turns "upload a PDF" into "import a month and have the statement to reconcile against", which a CSV can't do,
because a CSV has no closing balance.

---

## 9. Privacy, security, cost

| Concern | Handling |
|---------|----------|
| Statement leaves the server | Disclosure on step 1. Book setting `allow_ai_statement_reading` (default on, D4). Model provider named in the privacy policy |
| Account numbers | Before the text path sends a page, mask digit runs ≥ 8 except the last 4 (`•••• 1234`). The document path can't be masked; the disclosure covers it |
| Retention | `pdf` bytes cleared on import/discard. A celery-beat task, `purge_stale_statement_uploads`, clears bytes and rows of any upload older than 24h that isn't `imported` |
| Prompt injection (a PDF is untrusted input) | The agent has **no tools** and a schema-validated output, so the worst case is wrong rows, which §4 and the review step exist to catch |
| Malformed/hostile files | Checks `%PDF-` magic, size ≤ 10 MB, pages ≤ 40, parse in the worker only. Encrypted → refused ("remove the password and try again"; password entry is a later version) |
| Cost | Per-book `STATEMENT_PDF_PAGES_PER_MONTH` quota counted from `StatementUpload.page_count`. Same-sha256 re-upload reuses the existing extraction. Tokens recorded per upload |
| Permissions | Any book member can upload, as with CSV |

---

## 10. Testing

- **Pure units:** `dates.py` (year wrap, missing year, out-of-window), `checks.py` (balanced, off, flipped sign,
  missing row, transposed digits, running-balance walk locating the bad row, card vs chequing sign through
  `to_ledger`), `validate.py` (magic, encrypted, too many pages), the digit masking.
- **Extraction with `FunctionModel`:** multi-page merge, header from first/last page, balance-forward rows dropped,
  a page failing validation and being retried alone.
- **Fixture corpus:** `apps/bank_feed/tests/fixtures/statements/`, small **synthetic** PDFs generated in-repo (e.g.
  by a `reportlab` dev-only script) for one chequing layout, one card layout, one Dec→Jan statement, and one
  image-only page. No real customer statements in the repo.
- **Endpoints:** happy path, cross-book isolation (via the isolation tables), quota, same-sha256 refusal,
  unbalanced-confirm without acknowledgement → 400, `start_reconciliation` opening a draft.
- **Refactor safety:** the existing CSV upload tests must pass untouched after §6.2.
- **E2E** (`e2e/tests/test_pdf_statement.py`, POM in `e2e/pages/`, `STATEMENT_EXTRACTION_MODEL="test"`): upload →
  check shows Balanced → import → rows in the feed with source PDF. Also: edit a flagged row until the badge flips to
  Balanced.
- **Accuracy eval (manual, real provider):** `manage.py eval_statement_extraction <dir>` reads `*.pdf` + `*.expected.json`
  pairs and reports row precision/recall, amount exactness and balance-check pass rate per file. It runs against
  real statements kept **outside** the repo and is used to tune the prompt and choose the model (D1).

---

## 11. Milestones

| M | Scope | Done when |
|---|-------|-----------|
| 1 | `pdf_statement/` pure core: `validate`, `text`, `schema`, `dates`, `checks`, masking | unit tests green; no DB, no network |
| 2 | `llm.py` + `extract.py` with the test model; eval command | extraction tests green; eval runs against a local corpus |
| 3 | `StatementUpload` model, task, endpoints, audit events, isolation tables, quota, purge beat task | endpoint + isolation tests green |
| 4 | `csv_upload.py` split (§6.2) + confirm fields (§6.3) | all existing CSV tests pass unchanged |
| 5 | Frontend: Step 1 branch, Read, Check; reuse Duplicates/Preview; api-client regen | E2E green with the test model |
| 6 | Reconciliation hand-off | test: confirm with `start_reconciliation` opens a draft at period end / closing balance |
| 7 | Scanned-page document path | synthetic image-only page extracts under the eval |
| 8 | `CLAUDE.md` Recent Changes, `docs/testing-guide.md`, `docs/security-log.md` entry | |

M1–M6 is a shippable v1 for text-layer PDFs. M7 can follow.

---

## 12. Decisions needed

| # | Question | Recommendation |
|---|----------|----------------|
| D1 | Which provider/model reads statements, and does the scanned path ship in v1? | Choose by running the §10 eval on 10–20 real statements across 3–4 banks; ship text-layer first (M1–M6), scanned in M7 |
| D2 | Can an **unbalanced** statement be imported? | Yes, with an acknowledgement of the exact difference (§6.3). Blocking would strand a user whose statement genuinely has an odd layout, and the rows are still reviewable in the Inbox |
| D3 | Gate behind a subscription plan / quota size? | Quota for everyone at launch (200 pages/book/month); revisit with real token costs from `StatementUpload` |
| D4 | Consent: a per-book setting, a one-time acknowledgement, or disclosure only? | Disclosure on every upload plus a book-level off switch |
| D5 | Combined statements (chequing + savings in one PDF)? | v1: the schema returns one section; if the header's account doesn't look like the selected account, warn. Multi-section picker in a later version |
| D6 | Keep the original PDF after import (e.g. attach to the reconciliation)? | No, not in v1. Statement storage is a separate feature with its own retention story |
| D7 | Ask the model to suggest categories too? | No. Categorize mode's history-based suggestions are deterministic and already explain themselves |
