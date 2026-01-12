# Plaid Bank Feed Architecture (Django)

This document summarizes the agreed-upon architecture and implementation plan for integrating **Plaid** into the personal finance Django app, based on our discussion. It captures **design decisions, priorities, invariants, models, serializers, and views**, along with recommended next steps.

---

## 1. Stated Priorities & Constraints

From the discussion, the following priorities guide all design decisions:

1. **Ledger correctness comes first**  
   - `JournalEntry` and `JournalLine` remain the authoritative accounting records.
   - All ledger entries must be balanced, explicit, and intentional.

2. **Non‑accountant user experience**  
   - The app should feel simple and intuitive.
   - Avoid QBO‑level complexity (separate reconciliation objects, accountant workflows, etc.).

3. **Unified bank feed UI**  
   - Manual transactions and bank-imported transactions must appear together in one feed.
   - Users should not need to care whether a transaction is “Plaid” or “manual.”

4. **Future‑proofing**  
   - Support batch actions (e.g. categorize 20 transactions as Groceries).
   - Enable future features like rules, matching, reconciliation, and automation.

5. **Explicit state transitions**  
   - Bank transactions should *not* become ledger entries until the user takes action.
   - No silent or automatic mutation of the ledger.

---

## 2. Core Design Decision

> **The bank feed is not the ledger.**  
> **The bank feed is a task list for creating ledger entries.**

### Key implications

- Plaid transactions are stored as **staging objects**.
- Ledger transactions (`JournalEntry` / `JournalLine`) are created **only when the user categorizes or edits** a Plaid transaction.
- The frontend consumes **one unified Bank Feed API**, not raw models.

---

## 3. High-Level Architecture

```
Plaid API
   ↓
ImportedTransaction (staging)
   ↓  (user categorizes / batch action)
JournalEntry
   ↓
JournalLine (2 lines, double-entry)
```

The UI never talks directly to `ImportedTransaction` or `JournalLine`.  
It talks to **Bank Feed Rows**.

---

## 4. Models

### PlaidItem

```python
class PlaidItem(BaseTeamModel):
    plaid_item_id = models.CharField(max_length=255, unique=True)
    access_token = models.CharField(max_length=512)
    institution_name = models.CharField(max_length=255)

    cursor = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
```

Represents a connected bank login.

---

### PlaidAccount

```python
class PlaidAccount(BaseTeamModel):
    plaid_account_id = models.CharField(max_length=255, unique=True)
    item = models.ForeignKey(PlaidItem, on_delete=models.CASCADE)

    account = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        help_text="Ledger account this Plaid account feeds into",
    )

    name = models.CharField(max_length=255)
    mask = models.CharField(max_length=10, blank=True)
    subtype = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
```

Maps a Plaid account to a ledger `Account`.

---

### ImportedTransaction (full Plaid coverage)

```python
class ImportedTransaction(BaseTeamModel):
    plaid_transaction_id = models.CharField(max_length=255, unique=True)
    plaid_account = models.ForeignKey(PlaidAccount, on_delete=models.CASCADE)

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    iso_currency_code = models.CharField(max_length=10, null=True, blank=True)
    unofficial_currency_code = models.CharField(max_length=10, null=True, blank=True)

    date = models.DateField()
    authorized_date = models.DateField(null=True, blank=True)

    pending = models.BooleanField(default=False)
    pending_transaction_id = models.CharField(max_length=255, null=True, blank=True)

    name = models.CharField(max_length=255)
    merchant_name = models.CharField(max_length=255, null=True, blank=True)

    personal_finance_category = models.CharField(max_length=255, null=True, blank=True)
    personal_finance_category_id = models.CharField(max_length=255, null=True, blank=True)
    category_confidence = models.CharField(max_length=50, null=True, blank=True)

    payment_channel = models.CharField(max_length=50, null=True, blank=True)
    transaction_type = models.CharField(max_length=50, null=True, blank=True)

    location = models.JSONField(null=True, blank=True)
    merchant_metadata = models.JSONField(null=True, blank=True)

    raw = models.JSONField()

    journal_entry = models.ForeignKey(
        "journal.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
```

**Critical invariant**: an `ImportedTransaction` may link to **zero or one** `JournalEntry`.

---

## 5. Bank Feed Row (Unified Projection)

This is **not a model**. It is the contract between backend and frontend.

### BankFeedRowSerializer

```python
class BankFeedRowSerializer(serializers.Serializer):
    id = serializers.CharField()
    source = serializers.ChoiceField(choices=["ledger", "plaid"])

    date = serializers.DateField()
    authorized_date = serializers.DateField(allow_null=True)

    description = serializers.CharField()
    merchant_name = serializers.CharField(allow_null=True)

    account = AccountSerializer()
    category = AccountSerializer(allow_null=True)

    inflow = serializers.DecimalField(max_digits=12, decimal_places=2)
    outflow = serializers.DecimalField(max_digits=12, decimal_places=2)

    is_pending = serializers.BooleanField()
    is_cleared = serializers.BooleanField()

    payment_channel = serializers.CharField(allow_null=True)
    confidence = serializers.CharField(allow_null=True)

    journal_line_id = serializers.IntegerField(allow_null=True)
    imported_transaction_id = serializers.IntegerField(allow_null=True)

    is_editable = serializers.BooleanField()
```

---

## 6. Feed Adapters

### JournalLine → Bank Feed Row

```python
def journal_line_to_feed_row(line: JournalLine):
    sibling = next(
        l for l in line.journal_entry.lines.all()
        if l.id != line.id
    )

    inflow = line.dr_amount if line.dr_amount > 0 else Decimal("0")
    outflow = line.cr_amount if line.cr_amount > 0 else Decimal("0")

    return {
        "id": f"ledger-{line.id}",
        "source": "ledger",
        "date": line.journal_entry.entry_date,
        "authorized_date": None,
        "description": line.journal_entry.description,
        "merchant_name": line.journal_entry.payee.name if line.journal_entry.payee else None,
        "account": line.account,
        "category": sibling.account,
        "inflow": inflow,
        "outflow": outflow,
        "is_pending": False,
        "is_cleared": line.is_cleared,
        "payment_channel": None,
        "confidence": "manual",
        "journal_line_id": line.id,
        "imported_transaction_id": None,
        "is_editable": True,
    }
```

---

### ImportedTransaction → Bank Feed Row

```python
def imported_tx_to_feed_row(tx: ImportedTransaction):
    amount = abs(tx.amount)

    return {
        "id": f"plaid-{tx.id}",
        "source": "plaid",
        "date": tx.date,
        "authorized_date": tx.authorized_date,
        "description": tx.name,
        "merchant_name": tx.merchant_name,
        "account": tx.plaid_account.account,
        "category": None,
        "inflow": amount if tx.amount < 0 else Decimal("0"),
        "outflow": amount if tx.amount > 0 else Decimal("0"),
        "is_pending": tx.pending,
        "is_cleared": False,
        "payment_channel": tx.payment_channel,
        "confidence": tx.category_confidence,
        "journal_line_id": None,
        "imported_transaction_id": tx.id,
        "is_editable": True,
    }
```

---

## 7. BankFeedViewSet (replaces SimpleLineViewSet for feed UI)

```python
class BankFeedViewSet(viewsets.ViewSet):
    permission_classes = [TeamModelAccessPermissions]

    def list(self, request, team_slug=None):
        account_id = request.query_params.get("account")

        ledger_lines = (
            JournalLine.for_team
            .filter(account_id=account_id)
            .select_related("account", "journal_entry")
            .prefetch_related("journal_entry__lines__account")
        )

        imported = ImportedTransaction.objects.filter(
            team=request.team,
            plaid_account__account_id=account_id,
            journal_entry__isnull=True,
        )

        rows = []

        for line in ledger_lines:
            rows.append(journal_line_to_feed_row(line))

        for tx in imported:
            rows.append(imported_tx_to_feed_row(tx))

        rows.sort(key=lambda r: r["date"], reverse=True)

        return Response(BankFeedRowSerializer(rows, many=True).data)
```

---

## 8. Categorization & Batch Actions

### Categorize endpoint (single or batch)

```python
@action(detail=False, methods=["post"])
def categorize(self, request, team_slug=None):
    rows = request.data["rows"]
    category_account_id = request.data["category_account_id"]

    for row in rows:
        if row["source"] == "plaid":
            create_journal_from_import(
                imported_tx_id=row["imported_transaction_id"],
                category_account_id=category_account_id,
                team=request.team,
            )
        else:
            update_simple_line_category(
                journal_line_id=row["journal_line_id"],
                category_account_id=category_account_id,
                team=request.team,
            )

    return Response(status=status.HTTP_204_NO_CONTENT)
```

Batch actions work because the **feed row** is the unit of work.

---

## 9. Critical Invariants (Must Not Break)

1. **No duplicate feed rows**  
   - Imported transactions appear **only** when `journal_entry IS NULL`.

2. **Ledger entries are explicit**  
   - No automatic creation of `JournalEntry` without user intent.

3. **Feed is a projection**  
   - Frontend never mutates ledger models directly.

4. **Double-entry rules are always enforced**  
   - Every committed transaction produces exactly two `JournalLine`s.

---

## 10. Recommended Next Steps

Short‑term (next 1–2 iterations):

1. Wire `BankFeedViewSet` into the existing React bank feed table
2. Add batch‑selection UI + categorize modal
3. Implement Plaid `/transactions/sync` job using cursors
4. Add basic duplicate detection (same amount/date/account)

Medium‑term:

5. Rules engine (preview → apply)
6. Matching logic (Plaid ↔ manual entries)
7. Reconciliation workflow using `is_cleared`
8. Confidence‑based auto‑suggestions (no auto‑posting)

Long‑term:

9. Recurring transaction detection
10. Merchant normalization & payee linking
11. Import health & sync diagnostics

---

## 11. Final Mental Model

> **The bank feed is a workflow, not a table.**  
> **The ledger is the source of truth.**  
> **Everything else exists to help users create correct ledger entries with minimal friction.**

This design keeps the system simple, correct, and extensible — without turning your app into accounting software for accountants.

