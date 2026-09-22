# Split Transactions in the UI — Requirements & Implementation Plan

**Status:** proposal. No code written yet. Implement §12 in order.
**Priority:** P1.1 in `docs/feature-priority-report.md` — the highest-value single item there.
**Prerequisite reading:** this document only. Everything you need is quoted inline.

---

## 1. What this feature is

A **split transaction** is one bank transaction apportioned across two or more
categories. A $210.40 Costco receipt that is $160.00 groceries and $50.40 household
goods. A paycheque that is gross income less tax less pension. A $500 credit-card
payment where $480 is the payment and $20 is an annual fee.

Today the user cannot create one, cannot edit one, cannot see one on the Transactions
page, and — if one already exists — **editing it corrupts the ledger**. See §4.

---

## 2. Why this is the top-priority feature

1. **We already import splits we cannot author.** `apps/ynab_import/services/build.py`
   creates them (83 split groups on the reference export). A YNAB migrant arrives with
   splits in their ledger and can neither edit them nor make another.
2. **YNAB migration is our primary acquisition channel** (`docs/marketing-plan.md`, Step
   3b). A migrant hits this in week one.
3. **It is a live data-corruption bug**, not just a missing feature (§4.1).

---

## 3. The canonical data shape — read this twice

There is **no new model and no migration.** `JournalEntry` + `JournalLine` already
express splits; the API already validates them
(`apps/journal/serializers.py:105-120` enforces ≥2 lines and balanced debits/credits).
The gaps are entirely in the UI and in code that *assumes* two lines.

### 3.1 The shape

**One line on the bank account carrying the total; one counter line per split leg.**

This is exactly what the YNAB importer already builds
(`apps/ynab_import/services/build.py:754` — *"One entry for a split: a single line on
the account, one counter line per leg"*). Do not invent a different shape.

```
JournalEntry (id=900, entry_date=2026-09-14, description="Costco", payee=Costco)
├── JournalLine  account=Chequing          dr=0.00     cr=210.40   ← the one bank line
├── JournalLine  account=Groceries         dr=160.00   cr=0.00     ← leg 1
└── JournalLine  account=Household Goods   dr=50.40    cr=0.00     ← leg 2
                                           ───────     ───────
                                  totals   210.40      210.40      ← must be equal
```

One `BankTransaction` points at that entry. There is exactly **one** `BankTransaction`
per split (a split is not a transfer; see §6.3).

### 3.2 The sign convention — the only arithmetic in this feature

The codebase uses the **Plaid convention** throughout: `BankTransaction.amount` is
**positive for an outflow**, negative for an inflow. Keep it.

Define, for a transaction:

```
total = outflow - inflow        # positive = money left the bank
```

Each split leg carries a **signed** `amount` in the same convention:

- `amount > 0` → this leg is in the same direction as a normal outflow
- `amount < 0` → this leg is a refund/credit going the other way

**The two rules that produce the journal lines:**

| Line | Debit | Credit |
|---|---|---|
| **Each leg** (signed `a`, `a ≠ 0`) | `a` if `a > 0` else `0` | `-a` if `a < 0` else `0` |
| **The bank line** (signed `total`) | `-total` if `total < 0` else `0` | `total` if `total > 0` else `0` |

In words: **a leg takes the same side as its own sign; the bank line takes the opposite
side of the total.**

**Balance requirement:** `sum(leg amounts) == total`, exactly, to the cent.

### 3.3 Worked examples — use these as test fixtures

**(a) Plain outflow split.** $210.40 out, groceries $160.00 + household $50.40.
`total = +210.40`, legs `[+160.00, +50.40]`.

| Account | dr | cr |
|---|---|---|
| Chequing (bank) | 0.00 | 210.40 |
| Groceries | 160.00 | 0.00 |
| Household Goods | 50.40 | 0.00 |
| **Totals** | **210.40** | **210.40** ✓ |

**(b) Outflow split with a refund leg.** Net $80.00 out: a $100.00 purchase and a
$20.00 credit. `total = +80.00`, legs `[+100.00, -20.00]`.

| Account | dr | cr |
|---|---|---|
| Chequing (bank) | 0.00 | 80.00 |
| Shopping | 100.00 | 0.00 |
| Refunds | 0.00 | 20.00 |
| **Totals** | **100.00** | **100.00** ✓ |

**(c) Inflow split (a paycheque).** $2,000.00 in, split $1,800.00 salary +
$200.00 bonus. `total = -2000.00`, legs `[-1800.00, -200.00]`.

| Account | dr | cr |
|---|---|---|
| Chequing (bank) | 2000.00 | 0.00 |
| Salary | 0.00 | 1800.00 |
| Bonus | 0.00 | 200.00 |
| **Totals** | **2000.00** | **2000.00** ✓ |

**(d) Gross paycheque with deductions.** $3,000.00 net in; gross salary $4,000.00,
income tax $800.00, pension $200.00. `total = -3000.00`,
legs `[-4000.00, +800.00, +200.00]`.

| Account | dr | cr |
|---|---|---|
| Chequing (bank) | 3000.00 | 0.00 |
| Salary | 0.00 | 4000.00 |
| Income Tax | 800.00 | 0.00 |
| Pension | 200.00 | 0.00 |
| **Totals** | **4000.00** | **4000.00** ✓ |

Check the sums: `-4000 + 800 + 200 = -3000 = total` ✓

---

## 4. Five things that are broken today — fix these before building any UI

Splits already exist in user data. Every one of these is reachable right now. **Do not
build the editor on top of them.** Each has an exact location and an exact fix.

### 4.1 🔴 Editing a split through the feed modal unbalances the ledger

**Location:** `apps/bank_feed/views.py:657-676`, inside `update()`.

```python
for line in lines:
    if line.account == old_account or line.account == bank_account:
        # Bank account line ... (sets the bank line — fine)
    else:
        # Category line
        line.account = category_account      # ← every leg, same account
        if inflow > 0:
            line.dr_amount = Decimal("0")
            line.cr_amount = abs_amount      # ← every leg, the FULL amount
        else:
            line.dr_amount = abs_amount
            line.cr_amount = Decimal("0")
        line.save()
```

**Reproduction:** take example (a) above. Open it in the bank-feed edit modal, change
nothing, click Save. The `else` branch runs for *both* legs, setting each to
`dr = 210.40`. Result: debits 420.80, credits 210.40. **The entry is now unbalanced.**

Nothing catches it. `JournalEntry.clean()` would (`apps/journal/models.py:78-84`) but it
is never called on this path — there is no `full_clean()` in `update()`.

Every downstream figure is now wrong: the balance sheet does not balance, the income
statement overstates by $210.40, net worth is wrong.

**Fix:** §6.1.

### 4.2 🔴 The Transactions page silently hides every split

**Location:** `apps/journal/views.py:348`.

```python
.filter(line_count=2)
```

`TransactionViewSet.base_queryset()` filters the ledger to entries with **exactly two
lines**. A YNAB migrant's 83 split transactions do not appear on the Transactions page at
all — and the column filters, the facet counts and the CSV export all omit them too.

The page presents itself as the ledger. It is silently not.

**Fix:** §8.

### 4.3 🟠 The feed row shows an arbitrary leg as "the category"

**Location:** `apps/bank_feed/serializers.py`, in `bank_transaction_to_feed_row()`:

```python
for line in tx.journal_entry.lines.all():
    if line.account != tx.account:
        category = line.account        # ← no break: ends up the LAST leg
```

A split row in the bank feed reports whichever leg happens to come last in `id` order as
its single category, with no indication a split exists.

**Fix:** §6.2.

### 4.4 🟠 Bulk categorize / batch edit silently re-points one leg

**Location:** `apps/bank_feed/views.py:1317-1336`, `_update_journal_category()`:

```python
for line in journal_entry.lines.all():
    if line.account != bank_tx.account:
        line.account = new_category_account
        line.save()
        break                          # ← only the first leg
```

Selecting a split in the feed and bulk-categorizing it re-points leg 1 and leaves the
rest. The entry stays balanced, so nothing complains — the split is just quietly wrong.

**Fix:** §6.1.

### 4.5 🟠 A split can grow a bogus transfer mirror leg

**Location:** `apps/bank_feed/services/transfer_mirror.py`, `_counterpart_account()`:

```python
for line in entry.lines.all():
    if line.account_id != primary_account.id:
        return line.account            # ← the FIRST leg, arbitrarily
```

If a split's first leg happens to be a feed-enabled asset/liability account,
`sync_transfer()` treats the whole split as a transfer and creates a mirror
`BankTransaction` in that account's feed — a phantom row for the split's full amount.

**Fix:** §6.3.

### 4.6 One thing that is already correct — do not touch it

**Budget actuals and every report already handle splits correctly.** They aggregate
per-`JournalLine` (`apps/budget/services.py:33-63` groups by `account` and sums
`dr_amount`/`cr_amount`), so a leg lands in its own category's actual with no special
casing. Same for the income statement, balance sheet, net worth and Sankey.

`SimpleLineSerializer.update()` is also already correct: it **refuses** a >2-line entry
with a clear message (`apps/journal/serializers.py:305-311`). Leave that refusal in place.

---

## 5. Decisions locked — do not re-litigate these

An implementer should not have to make a judgement call. These are decided.

| # | Decision | Why |
|---|---|---|
| D1 | **No new model, no migration.** | `JournalEntry`/`JournalLine` already express a split and the API already validates it. |
| D2 | **No per-leg memo in v1.** Instead, a split is marked with the word **"Split"** alongside its description everywhere the description is shown. | `JournalLine` has no text field; adding one is a migration for a nicety. Marking the description is what makes a split identifiable without one. See D2a for where the marker lives. |
| D2a | **The "Split" marker is derived at display time, never written into `JournalEntry.description`.** | `description` is user-editable and full-text-searchable. Storing the word there means un-splitting leaves a lie behind, an ordinary description edit silently deletes the marker, and a search for "split" starts matching the marker instead of the user's own text. A derived marker cannot drift from the thing it describes. Rendered as a badge beside the description in the UI, and as a literal `Split — ` prefix in CSV exports, where there is no markup. |
| D3 | **The split editor lives inside the existing `EditTransactionModal`**, as a mode, not a new modal. | It is already the single edit surface for a feed row and already has a Details/History tab strip. A second modal is a second thing to keep in sync. |
| D4 | **Minimum 2 legs, maximum 20.** | A 1-leg "split" is a normal transaction — offer "Remove split" instead. 20 is an abuse ceiling that is also comfortably above any real receipt. |
| D5 | **A leg amount of exactly 0 is rejected.** | It is not a category apportionment; it is a mistake. Use Remove-leg. |
| D6 | **Legs are signed** (§3.2); a negative leg is a refund within the split. | Needed for example (d), which is how every real paycheque looks. |
| D7 | **`sum(legs) == total` is enforced server-side and 400s on mismatch**, even though the client also enforces it. | The bank sets the total. A client that miscomputes must not be able to write an unbalanced entry. |
| D8 | **Re-apportioning legs is allowed on a *reconciled* transaction. Changing the total is not.** | Reconciliation is a fact about the bank line, whose amount does not change when legs are re-apportioned. Freezing categories after reconciling would be wrong and annoying. |
| D9 | **Never delete-and-recreate the bank line.** Update it in place. | It carries `is_reconciled`, `is_cleared` and `is_archived`. Recreating it silently unreconciles. This is why you must **not** reuse `JournalEntrySerializer.update()`, which does `instance.lines.all().delete()` (`apps/journal/serializers.py:147`). |
| D10 | **Bulk operations refuse splits** for the category field, with an explicit error. | Silently collapsing a user's 4-way split because it was caught in a select-all is destructive. Explicit "Remove split" in the editor is the supported path. |
| D11 | **A split is never a transfer.** `sync_transfer()` no-ops on >2-line entries. | See §4.5. A transfer is a 2-line movement between two feed accounts; a split has no single counterpart. |
| D12 | **Categorize mode gets a "Split" button that opens the same editor** — last phase, and droppable. | Keeps the high-volume flow untouched until the editor is proven. |
| D13 | **Amount inputs are `type="text"`, not `type="number"`.** | Matches the precedent set by `BudgetAmountForm`: a number input spends ↑/↓ on its own spinner, and this editor needs arrow keys. Parse with the same tolerance (`$1,234.56`, `(45.50)` → negative). |

---

## 6. Backend — Part 1: make split-safe (Phases 1–2)

### 6.1 New service module: `apps/bank_feed/services/splits.py`

Create this file. It is the **single** place split lines are written. Everything else
calls into it.

```python
"""
Splitting one bank transaction across several categories.

A split is one JournalEntry: a single line on the bank account carrying the
total, and one counter line per leg (the shape `apps.ynab_import` already
builds). The signed-amount convention is the Plaid one used throughout the
feed -- positive is an outflow -- and a leg takes the same side as its own
sign while the bank line takes the opposite side of the total.

Everything that writes split lines goes through `apply_splits`, so the
balance invariant is enforced in one place rather than at each call site.
"""

from decimal import Decimal

from django.db import transaction

from apps.accounts.models import Account
from apps.journal.models import JournalEntry, JournalLine

#: A split with one leg is a plain transaction; offer "remove split" instead.
MIN_LEGS = 2

#: Not a product limit -- an abuse ceiling.
MAX_LEGS = 20

CENT = Decimal("0.01")


class SplitError(ValueError):
    """A split the caller asked for that cannot be written. The message is shown to the user."""


def is_split(entry) -> bool:
    """True when this entry apportions one transaction across several categories."""
    if entry is None:
        return False
    return entry.lines.count() > 2


def leg_lines(entry, bank_account):
    """The entry's category lines -- every line except the bank account's."""
    return [line for line in entry.lines.all() if line.account_id != bank_account.id]


def signed_amount(line) -> Decimal:
    """A line's amount in the feed's signed convention: debit positive, credit negative."""
    return line.dr_amount - line.cr_amount


def parse_legs(raw, team) -> list[tuple[Account, Decimal]]:
    """
    Validate a client's `splits` payload into (account, signed amount) pairs.

    Raises SplitError with a user-facing message. Every rejection is a refusal
    rather than a silent drop: a leg the user entered that vanished without
    explanation is worse than an error they can act on.
    """
    if not isinstance(raw, list):
        raise SplitError("Splits must be a list.")
    if len(raw) < MIN_LEGS:
        raise SplitError(f"A split needs at least {MIN_LEGS} categories.")
    if len(raw) > MAX_LEGS:
        raise SplitError(f"A split cannot have more than {MAX_LEGS} categories.")

    legs = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SplitError(f"Split {index} is not valid.")

        try:
            account = Account.for_team.get(id=item.get("category"))
        except (Account.DoesNotExist, TypeError, ValueError):
            raise SplitError(f"Split {index}: category not found.") from None

        try:
            amount = Decimal(str(item.get("amount"))).quantize(CENT)
        except Exception:
            raise SplitError(f"Split {index}: amount is not a number.") from None

        if amount == 0:
            raise SplitError(f"Split {index}: amount cannot be zero.")

        legs.append((account, amount))

    return legs


@transaction.atomic
def apply_splits(bank_tx, legs, *, total):
    """
    Write `legs` as the category lines of `bank_tx`'s journal entry.

    The bank line is updated in place, never recreated -- it carries
    is_reconciled / is_cleared / is_archived, and recreating it would silently
    unreconcile a transaction the user has already confirmed against a
    statement (D9).

    `total` is signed, positive for an outflow. Raises SplitError when the legs
    do not sum to it: the bank sets the total, so a mismatch is a client bug
    and must not reach the ledger (D7).
    """
    leg_total = sum(amount for _, amount in legs)
    if leg_total != total:
        raise SplitError(
            f"Splits must add up to the transaction total. "
            f"They add up to {leg_total}, but the transaction is {total}."
        )

    bank_account = bank_tx.account
    entry = bank_tx.journal_entry
    if entry is None:
        raise SplitError("This transaction has no journal entry to split.")

    existing = list(entry.lines.all())
    bank_lines = [line for line in existing if line.account_id == bank_account.id]
    if len(bank_lines) != 1:
        # Not a shape this function can safely rewrite: bail rather than guess
        # which line is the bank's.
        raise SplitError("This transaction's ledger entry cannot be split automatically.")
    bank_line = bank_lines[0]

    # Bank line: opposite side of the total, amount unchanged in magnitude.
    bank_line.dr_amount = -total if total < 0 else Decimal("0")
    bank_line.cr_amount = total if total > 0 else Decimal("0")
    bank_line.save()

    # Replace the category lines. These carry no reconciliation state of their
    # own that the user set -- only the bank line does -- so recreating them is
    # safe, and it keeps this function's shape independent of how many legs the
    # entry had before.
    for line in existing:
        if line.id != bank_line.id:
            line.delete()

    for account, amount in legs:
        JournalLine.objects.create(
            journal_entry=entry,
            team=bank_tx.team,
            account=account,
            dr_amount=amount if amount > 0 else Decimal("0"),
            cr_amount=-amount if amount < 0 else Decimal("0"),
        )

    return entry


@transaction.atomic
def collapse_split(bank_tx, category_account, *, total):
    """
    Turn a split back into a plain two-line entry on `category_account`.

    This is what the editor's "Remove split" does. Bulk operations must *not*
    do it implicitly (D10).
    """
    return apply_splits(bank_tx, [(category_account, total)], total=total)
```

> **Note on `collapse_split`:** it passes a single leg, which `apply_splits` would
> reject via `MIN_LEGS` if it went through `parse_legs`. It does not — `parse_legs`
> validates *client* payloads, `apply_splits` writes whatever the server asks for. Keep
> that separation.

### 6.2 Make the read projections split-aware

**File: `apps/bank_feed/serializers.py`**

**(a)** In `bank_transaction_to_feed_row()`, replace the category loop (§4.3) with:

```python
    category = None
    is_reconciled = False
    split_legs = []
    if tx.journal_entry:
        lines = list(tx.journal_entry.lines.all())
        legs = [line for line in lines if line.account_id != tx.account_id]
        for line in lines:
            if line.account_id == tx.account_id:
                is_reconciled = line.is_reconciled

        if len(lines) > 2:
            # A split has no single category. Report the legs and leave
            # `category` null so nothing renders one leg as if it were the whole
            # transaction (see the bug this replaces).
            split_legs = [
                {
                    "category_id": line.account_id,
                    "category_name": line.account.name,
                    "amount": line.dr_amount - line.cr_amount,
                }
                for line in legs
            ]
        elif legs:
            category = legs[0].account
```

and add to the returned dict:

```python
        "is_split": bool(split_legs),
        "split_count": len(split_legs),
        "splits": split_legs,
```

**(b)** Add a leg serializer and three fields to `BankFeedRowSerializer`:

```python
class SplitLegSerializer(serializers.Serializer):
    """One leg of a split: a category and its signed share of the total."""

    category_id = serializers.IntegerField()
    category_name = serializers.CharField()
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Signed share of the transaction total; positive is an outflow",
    )
```

```python
    is_split = serializers.BooleanField(help_text="Whether this transaction is split across categories")
    split_count = serializers.IntegerField(help_text="Number of split legs (0 when not split)")
    splits = SplitLegSerializer(many=True, help_text="The split legs (empty when not split)")
```

**(c) Note on `is_cleared`.** The existing line `"is_cleared": bool(tx.journal_entry)`
is unchanged by this work. Do not touch it.

### 6.3 Stop the bogus transfer mirror

**File: `apps/bank_feed/services/transfer_mirror.py`**

At the top of `sync_transfer()`, after the existing `journal_entry_id is None` guard,
add:

```python
    # A split has no single counterpart: its entry carries one bank line and
    # several category legs, and `_counterpart_account` would pick an arbitrary
    # one. Mirroring it would put a phantom row for the split's full amount in
    # that leg's feed. A transfer is a two-line movement; a split is not one.
    if edited_tx.journal_entry.lines.count() > 2:
        return
```

Also add the same guard to `would_orphan_primary()` — a split's mirror status is
irrelevant, and a split is never a mirror:

```python
def would_orphan_primary(edited_tx, new_category_account):
    if edited_tx.journal_entry_id and edited_tx.journal_entry.lines.count() > 2:
        return False
    return bool(edited_tx.is_transfer_mirror and not is_transfer_target(new_category_account))
```

### 6.4 Make bulk paths refuse splits

**File: `apps/bank_feed/views.py`**

**(a)** In `_update_journal_category()` (line ~1317), before the existing loop:

```python
        if is_split(journal_entry):
            raise SplitError(
                "This is a split transaction. Open it and edit its categories, "
                "or remove the split first."
            )
```

Import `is_split` and `SplitError` from `..services.splits`.

**(b)** `categorize` (line ~268) already catches `ValueError` and returns 400 with the
message. `SplitError` subclasses `ValueError`, so it is handled — **verify this, do not
assume it.**

**(c)** In `batch_edit` (line ~1173), the category branch calls
`_update_journal_category` inside `transaction.atomic()` and does **not** catch
`ValueError`. Add an up-front refusal next to the existing `would_orphan_primary` check,
so the batch is all-or-nothing rather than half-applied:

```python
        if category_account is not None:
            for tx in transactions:
                if is_split(tx.journal_entry):
                    return Response(
                        {
                            "error": "One or more selected transactions are split across "
                            "categories. Open a split transaction to edit its categories."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
```

**(d)** The "Move account" branch of `batch_edit` (line ~1259) is **already correct** for
splits — it matches `line.account == old_account` and `break`s, and a split has exactly
one bank line. Leave it.

**(e)** `_decategorize` (line ~1339) is **already correct** — it deletes the whole entry.
Leave it.

### 6.5 Fix `update()` — the corruption bug

**File: `apps/bank_feed/views.py`**, in `update()`.

Replace the `for line in lines:` block (§4.1) with a branch that dispatches to
`apply_splits` when the request carries legs, and otherwise keeps the existing two-line
behaviour but **only ever touches one category line**:

```python
            elif journal_entry:
                journal_entry.entry_date = data["date"]
                journal_entry.description = data.get("description", "")
                journal_entry.payee = payee
                journal_entry.save()

                if legs is not None:
                    # Split: one bank line at the total, one counter line per leg.
                    apply_splits(bank_tx, legs, total=amount)
                else:
                    lines = list(journal_entry.lines.all())
                    if is_split(journal_entry):
                        # Collapsing a split to a single category is a real
                        # action, but it must be asked for, not implied by an
                        # edit that happens to omit `splits` (D10).
                        return Response(
                            {
                                "error": "This transaction is split across categories. "
                                "Send its splits, or remove the split first."
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    apply_splits(bank_tx, [(category_account, amount)], total=amount)
```

Note what this buys: the two-line case now also goes through `apply_splits`, so there is
exactly one function in the codebase that writes journal lines for a feed transaction.
The old `for line in lines` loop is deleted entirely.

Wrap the `apply_splits` calls so `SplitError` becomes a 400:

```python
        try:
            with transaction.atomic():
                ...
        except SplitError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
```

**Guard the reconciled case (D8).** Before writing, if the bank line is reconciled and
the requested `amount` differs from the current bank-line magnitude, refuse:

```python
        bank_line_reconciled = bool(
            bank_tx.journal_entry
            and bank_tx.journal_entry.lines.filter(account=bank_tx.account, is_reconciled=True).exists()
        )
        if bank_line_reconciled and amount != bank_tx.amount:
            return Response(
                {"error": "This transaction is reconciled. Unreconcile it before changing its amount."},
                status=status.HTTP_400_BAD_REQUEST,
            )
```

Re-apportioning legs while reconciled stays allowed, which is the point of D8.

---

## 7. Backend — Part 2: the write API (Phase 3)

### 7.1 Request contract

`ManualTransactionSerializer` (`apps/bank_feed/views.py:~110`) gains **one** optional
field:

```python
    splits = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Split this transaction across categories. Each item is "
            '{"category": <account id>, "amount": "<signed decimal>"}, positive '
            "for an outflow. The amounts must add up to outflow - inflow. "
            "Mutually exclusive with `category`."
        ),
    )
```

Add to its `validate()`:

```python
        splits = data.get("splits")
        if splits is not None:
            if data.get("category") is not None:
                raise serializers.ValidationError(
                    "Send either a single category or splits, not both."
                )
```

Do **not** validate leg contents here — `parse_legs` owns that, so the rules live in one
place and the error messages are the user-facing ones.

In both `create()` and `update()`, after the serializer validates:

```python
        legs = None
        if data.get("splits") is not None:
            try:
                legs = parse_legs(data["splits"], request.team)
            except SplitError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
```

### 7.2 `create()` with splits

`create()` (line ~422) builds a `BankTransaction` and then a journal entry. The
split path is: create the entry with the bank line only, link it, then call
`apply_splits`. Read the existing method and follow its structure; the new branch is:

```python
        if legs is not None:
            journal_entry = JournalEntry.objects.create(
                team=request.team,
                entry_date=data["date"],
                description=data.get("description", ""),
                payee=payee,
                source=JournalEntry.SOURCE_MANUAL,
                status=JournalEntry.STATUS_POSTED,
            )
            JournalLine.objects.create(
                journal_entry=journal_entry,
                team=request.team,
                account=bank_account,
                dr_amount=Decimal("0"),
                cr_amount=Decimal("0"),
            )
            bank_tx.journal_entry = journal_entry
            bank_tx.save()
            apply_splits(bank_tx, legs, total=amount)
```

The placeholder bank line is created at zero and immediately corrected by
`apply_splits`; that is deliberate, so there is one place that computes the bank line's
sides.

### 7.3 Endpoint summary

No new URLs. The contract changes are:

| Endpoint | Change |
|---|---|
| `POST /a/{slug}/bankfeed/api/feed/` | accepts `splits` |
| `PUT /a/{slug}/bankfeed/api/feed/{id}/` | accepts `splits`; refuses a split-shaped entry sent without `splits` |
| `GET /a/{slug}/bankfeed/api/feed/` | rows gain `is_split`, `split_count`, `splits` |
| `POST .../feed/categorize/` | 400s on a split, with a message |
| `PATCH .../feed/batch_edit/` | 400s on a split when `category_id` is set |

### 7.4 Regenerate the API client

The repo's TypeScript client is generated from the OpenAPI schema and must never be
hand-edited. After the serializer changes:

```bash
make api-client
```

If that target does not exist, find the generation command in the `Makefile` and use it.
Commit the regenerated `api-client/` output with the change.

---

## 8. Backend — Part 3: the Transactions page (Phase 5)

### 8.1 Stop hiding splits

**File: `apps/journal/views.py:348`** — delete `.filter(line_count=2)`.

Update the class docstring (line ~319), which currently says *"Only entries with exactly
2 lines are returned"*.

### 8.2 Make `TransactionRowSerializer` describe a split

**File: `apps/journal/serializers.py`**, class `TransactionRowSerializer`.

Its `_debit_and_credit_lines()` returns `(None, None)` for anything that is not exactly
two lines, so `debit_account`/`credit_account` currently come back null. Replace with a
split-aware version.

A split always has **one line on one side and N on the other** (§3.1), which is what
makes a clean summary possible:

```python
    SPLIT_LABEL = _("Split (%(count)d)")

    def _sides(self, entry):
        """The entry's lines grouped into (debit lines, credit lines)."""
        lines = self._get_lines(entry)
        if len(lines) == 2:
            # Preserve the existing two-line behaviour exactly, including the
            # $0.00 entry where both lines are all-zero and the split falls back
            # to line order.
            first, second = lines
            debit, credit = (first, second) if first.dr_amount >= second.dr_amount else (second, first)
            return [debit], [credit]
        return (
            [line for line in lines if line.dr_amount > 0],
            [line for line in lines if line.cr_amount > 0],
        )

    def _side_label(self, lines):
        if len(lines) == 1:
            return lines[0].account.name
        if not lines:
            return None
        return self.SPLIT_LABEL % {"count": len(lines)}

    def get_debit_account(self, entry):
        debits, _ = self._sides(entry)
        return self._side_label(debits)

    def get_credit_account(self, entry):
        _, credits = self._sides(entry)
        return self._side_label(credits)
```

`get_amount()` is **already correct** — it sums `dr_amount` across all lines, which is
the entry total for any number of lines. Leave it.

Add two fields so the client can render a disclosure:

```python
    line_count = serializers.SerializerMethodField()
    legs = serializers.SerializerMethodField()

    def get_line_count(self, entry):
        return len(self._get_lines(entry))

    def get_legs(self, entry):
        """Every line, for the expandable split view. Empty for a plain entry."""
        lines = self._get_lines(entry)
        if len(lines) <= 2:
            return []
        return [
            {
                "account": line.account.name,
                "debit": str(line.dr_amount),
                "credit": str(line.cr_amount),
            }
            for line in lines
        ]
```

### 8.3 Column filters and sorting — interim behaviour, stated honestly

`apps/journal/filters.py` derives `debit_account_name`, `credit_account_name` and
`amount_value` from scalar subqueries that take **one** line
(`_DEBIT_LINE = ...order_by("-dr_amount", "pk")`, line ~46).

For a split, `_DEBIT_LINE` resolves to the **largest-debit leg**. So once §8.1 lands:

- Splits **appear** in the list. ✓
- Sorting by debit account sorts a split by its largest leg. Acceptable.
- Filtering by a debit account matches a split **only if that account is its largest
  leg**. A $50.40 household leg on a $160.00-groceries split will not match a
  "Household Goods" filter.

That last one is a real limitation. **Ship it anyway**, and make it Phase 7 (§12). It is
strictly better than today, where the split does not appear at all under any filter.

**Do not** try to fix it by widening the subquery. The correct fix is to change
`AccountTree.q()` so an account filter tests *any* line on that side via `Exists`, which
is its own change with its own facet-count implications — and the facet counts are the
part that will bite you, because a split would then be counted under several accounts and
the per-value counts would no longer sum to the row count.

Add a comment at `_DEBIT_LINE` recording this, so the next reader does not think it is an
oversight.

---

## 9. Frontend — the split editor (Phase 4)

### 9.1 Where it lives

`assets/javascript/bank_feed/react/EditTransactionModal.jsx` gains a split mode (D3).

New component: `assets/javascript/bank_feed/react/SplitEditor.jsx` — the leg table only.
The modal owns the state; the editor renders it. This keeps `SplitEditor` reusable from
categorize mode in Phase 7 without moving state around.

### 9.2 State added to `EditTransactionModal`

```js
// Split legs, or null when this transaction has a single category.
// Each leg: { key, categoryId, category, amount }
//   key      – stable client-side id for React (crypto.randomUUID() or a counter)
//   category – the option object from categoryOptions, or null
//   amount   – the raw string the user typed, parsed only on save
const [splits, setSplits] = useState(null);
```

`splits === null` means "not split" and the existing single `category` Combobox renders.
`splits` being an array means split mode, and the single Combobox is replaced by the leg
table.

### 9.3 Initialising from a transaction

Extend the existing `useEffect` that populates the form (line ~62). In edit mode:

```js
      const rowSplits = transaction.splits ?? transaction.split_legs ?? [];
      if (rowSplits.length > 0) {
        setSplits(rowSplits.map((leg) => ({
          key: nextKey(),
          categoryId: leg.categoryId ?? leg.category_id,
          category: categoryOptions.find((o) => o.id === (leg.categoryId ?? leg.category_id)) || null,
          amount: formatLegAmount(leg.amount),
        })));
      } else {
        setSplits(null);
      }
```

Tolerate both camelCase and snake_case exactly as the existing code does for
`journalEntryId` (line ~101) — rows arrive from the generated client in camelCase, but
some callers pass raw API data.

`formatLegAmount` renders a signed decimal as a plain string: `160.00`, `-20.00`.

### 9.4 The total, and what it means

```js
// Signed transaction total, positive for an outflow -- the same convention as
// the server (see the plan's sign-convention table).
const total = useMemo(() => {
  const i = parseAmount(inflow) ?? 0;
  const o = parseAmount(outflow) ?? 0;
  return round2(o - i);
}, [inflow, outflow]);

const legSum = useMemo(
  () => round2((splits ?? []).reduce((acc, leg) => acc + (parseAmount(leg.amount) ?? 0), 0)),
  [splits],
);

const remaining = useMemo(() => round2(total - legSum), [total, legSum]);
```

`round2(x)` is `Math.round(x * 100) / 100`. **Compare with a cent tolerance, never
`===`** — `0.1 + 0.2 !== 0.3` in JavaScript:

```js
const isBalanced = Math.abs(remaining) < 0.005;
```

### 9.5 Layout

Modal `size` becomes `lg` when `splits !== null` (from `sm`), because the leg table needs
the width. The `Modal` component already supports `sm | md | lg`
(`assets/javascript/common/Modal.jsx:13-17`).

```
┌─ Edit Transaction ─────────────────────────────────────────────┐
│  [ Details ]  [ History ]                                      │
│                                                                │
│  Date        [ 2026-09-14        ]                             │
│                                                                │
│  Categories                              [ Remove split ]      │
│  ┌──────────────────────────────┬──────────────┬─────┐         │
│  │ Groceries                  ▾ │  $  160.00   │  ×  │         │
│  │ Household Goods            ▾ │  $   50.40   │  ×  │         │
│  └──────────────────────────────┴──────────────┴─────┘         │
│  [ + Add a category ]                                          │
│                                                                │
│  Transaction total              $210.40                        │
│  Assigned                       $210.40                        │
│  Remaining                       $0.00   ✓                     │
│                                                                │
│  Inflow  [        ]      Outflow  [ 210.40 ]                   │
│  Payee   [ Costco                             ]                │
│  Description [                                ]                │
│                                     [ Cancel ] [ Save ]        │
└────────────────────────────────────────────────────────────────┘
```

In non-split mode the layout is exactly today's, plus one button under the category
Combobox:

```
│  Category (optional)  [ Groceries            ▾ ]               │
│  [ Split this transaction ]                                    │
```

### 9.6 Behaviour, item by item

Implement each of these. They are requirements, not suggestions.

1. **"Split this transaction"** — visible only when `splits === null` and
   `canEditCategory`. On click, seeds two legs: the first carries the current `category`
   (or null) and the **full total** as its amount; the second is empty with a blank
   amount. Seeding the first leg with the full total means `Remaining` starts at `$0.00`
   and goes *negative* as the user types the second leg, which reads correctly as "you
   have over-assigned" — the alternative (both blank) shows a scary full-amount
   `Remaining` before the user has done anything wrong.
2. **"+ Add a category"** — appends `{category: null, amount: ''}`. Disabled at
   `MAX_LEGS` (20) with a tooltip.
3. **Row "×"** — removes that leg. Disabled when only 2 legs remain, with the tooltip
   *"A split needs at least two categories. Use Remove split instead."*
4. **"Remove split"** — collapses to non-split mode: `setSplits(null)` and set
   `category` to the **largest leg by absolute amount** (the user's most likely intent).
   Then the ordinary single-category save path runs.
5. **`Remaining` display** — always visible in split mode.
   `$0.00` with a check icon and `text-success` when balanced; otherwise the signed
   remainder in `text-error`. Use the same `$1,234.50` formatting as the rest of the app,
   **not** `Intl.NumberFormat` with `style: 'currency'` — that renders `CA$1,234.50`,
   a bug already hit and fixed once in `OpeningBalances.jsx`.
6. **"Assign the rest" affordance** — clicking the `Remaining` figure when it is non-zero
   puts the remainder into the **last leg with a blank amount**, or the last leg if all
   are filled. Small, and it is the single most-used action in every competitor's split
   editor.
7. **Save is blocked** while `!isBalanced`, while any leg has no category, or while any
   leg's amount is unparseable or zero. The button is `disabled` and an inline
   `text-error` line names the first problem. Do not rely on the server for this — the
   server check (D7) is a backstop, not the UX.
8. **Amount inputs** are `type="text"` (D13) with `inputMode="decimal"`, parsed by a
   shared `parseAmount` that accepts `1234.56`, `$1,234.56`, `(45.50)` → `-45.50`, and
   `-20`. Blank parses to `null`, not `0`.
9. **Reconciled transactions** (D8): the leg table stays editable; `Inflow`/`Outflow`
   follow the existing `canEditAmounts` rule, which already disables them when
   `transaction.is_reconciled`. Add a hint under the total: *"Amount locked — transaction
   is reconciled. You can still change how it is split."*
10. **Negative legs are allowed** and need no special UI — a leading `-` is simply typed.
11. **Escape** inside a leg input must not close the modal while the input has focus and
    a value the user is mid-edit. Follow the precedent in `categorize`'s payee editor:
    `stopPropagation()` on the input's keydown. Note the `<dialog>` trap recorded in
    CLAUDE.md — Escape closes a `<dialog>` as a **keydown default action**, so
    `stopPropagation()` alone is not enough for a nested dismissible; you need
    `preventDefault()`.

### 9.7 The save payload

Extend `handleSave` (line ~139). When `splits !== null`:

```js
        const updatedData = {
          ...existingFields,
          category: null,
          splits: splits.map((leg) => ({
            category: leg.category.id,
            amount: String(parseAmount(leg.amount)),
          })),
        };
```

`amount` goes over the wire as a **string**, so no float ever reaches the server's
`Decimal`.

### 9.8 Plumb `splits` through the API helper

**File: `assets/javascript/bank_feed/bank_feed.js`**

Both `createTransaction` (line ~176) and `updateTransaction` (line ~210) build an
explicit `JSON.stringify({...})` body. Add to both:

```js
          splits: data.splits ?? null,
```

**File: `assets/javascript/bank_feed/react/LineApp.jsx`**

`handleAddLine` (line ~311) and `handleEditTransaction` (line ~334) both destructure
named fields and rebuild the object. Add `splits` to both destructurings and both
payloads. If you miss this, the modal will send legs that are silently dropped before the
request — it is the likeliest place for this feature to fail quietly.

### 9.9 Show splits in the feed table

**File: `assets/javascript/bank_feed/react/LineTable.jsx`**

The category cell currently renders `row.category?.name`. When `row.isSplit`, render
instead:

```jsx
<span className="badge badge-ghost badge-sm" data-testid={`split-badge-${row.id}`}>
  {interpolate(gettext('Split (%s)'), [row.splitCount])}
</span>
```

with a `title` listing the legs (`Groceries $160.00 · Household Goods $50.40`) so a hover
answers the obvious question without opening the modal.

Use `badge-ghost`, not `badge-soft badge-neutral` — CLAUDE.md records that the latter is
illegible on the dark surface.

**Do not** put the transfer-link button (`arrow-right-left`) on a split row: that button
appears when the category is a feed account, and a split has no single category. Since
`category` is now `null` for splits (§6.2a), the existing condition already excludes
them — **verify this rather than assuming it.**

### 9.10 Show splits on the Transactions page

**File: `assets/javascript/transactions/TransactionsTable.jsx`**

`debitAccount`/`creditAccount` now arrive as `"Split (3)"` for a split, so the table
renders correctly with **no change**. Add only the disclosure:

- When `row.lineCount > 2`, render a chevron button in the first cell.
- Expanded, insert a sub-row per `row.legs` entry: account name, debit, credit, indented
  and `text-base-content/70`.
- Expansion state is local (`useState` of a `Set` of row ids). It does not need to
  survive a filter change or a page load.

Use `/70` for muted text, not `/50` or `/60` — CLAUDE.md records that both fail the
4.5:1 AA contrast floor.

### 9.11 The "Split" description marker (D2 / D2a)

Because a split has no per-leg memo, **the word "Split" is shown alongside the
description wherever a transaction's description appears**, so a split is identifiable
without opening it.

It is **derived, never stored** (D2a). `JournalEntry.description` keeps exactly what the
user typed.

Where it appears, and as what:

| Surface | Rendering |
|---|---|
| Bank feed table (`LineTable.jsx`) | `Split` badge before the description text |
| Transactions table (`TransactionsTable.jsx`) | `Split` badge before the description text |
| Reports account activity (`templates/reports/components/account_activity_section.html`) | `Split` badge before the description text |
| **CSV exports** (`apps/reports/exports.py`) | literal `Split — ` prefix on the description cell — there is no markup in a CSV, and this is the surface where the marker matters most, since a spreadsheet is where someone reconciles by hand |

The badge is `badge badge-ghost badge-sm` (not `badge-soft badge-neutral`, which CLAUDE.md
records as illegible on the dark surface), carrying a `title` that lists the legs.

Server side this needs one thing: the reports' row builders must know the line count.
`ReportService.get_account_activity()` already loads the entry; expose `is_split` on each
transaction dict it returns and let both the template and the exporter read it.

---

## 10. Validation rules — the complete table

Every rule, where it is enforced, and the exact user-facing message.

| # | Rule | Client | Server | Message |
|---|---|---|---|---|
| V1 | ≥ 2 legs | Remove disabled at 2 | `parse_legs` | "A split needs at least 2 categories." |
| V2 | ≤ 20 legs | Add disabled at 20 | `parse_legs` | "A split cannot have more than 20 categories." |
| V3 | Every leg has a category | Save disabled | `parse_legs` | "Split {n}: category not found." |
| V4 | Leg category belongs to the team | n/a | `parse_legs` via `Account.for_team` | "Split {n}: category not found." |
| V5 | Leg amount parses | Save disabled | `parse_legs` | "Split {n}: amount is not a number." |
| V6 | Leg amount ≠ 0 | Save disabled | `parse_legs` | "Split {n}: amount cannot be zero." |
| V7 | `sum(legs) == total` | Save disabled, `Remaining` shown | `apply_splits` | "Splits must add up to the transaction total. They add up to X, but the transaction is Y." |
| V8 | `splits` and `category` are mutually exclusive | UI cannot send both | `ManualTransactionSerializer.validate` | "Send either a single category or splits, not both." |
| V9 | A split entry cannot be bulk-categorized | Batch bar shows the error toast | `_update_journal_category`, `batch_edit` | "One or more selected transactions are split across categories. Open a split transaction to edit its categories." |
| V10 | A split cannot be saved without its legs | UI always sends them | `update()` | "This transaction is split across categories. Send its splits, or remove the split first." |
| V11 | A reconciled transaction's **total** cannot change | Inputs disabled | `update()` | "This transaction is reconciled. Unreconcile it before changing its amount." |
| V12 | A reconciled transaction's **legs** may change | allowed | allowed | — (D8) |
| V13 | Existing: inflow and outflow not both > 0 | existing | existing | unchanged |

**Team scoping:** every account lookup uses `Account.for_team.get(...)`, which is the
team-scoped manager. A cross-team account id must surface as V4's "category not found",
never as a successful write. There is a required test for this (§11.1, T13).

---

## 11. Test plan

House pattern: Django `TestCase` with `setUpTestData()` class fixtures; E2E as Playwright
page objects. Follow `docs/testing-guide.md`.

### 11.1 Backend unit tests — new file `apps/bank_feed/tests/test_splits.py`

**Write T1–T5 FIRST and watch them fail.** They are the four bugs in §4. This is the
contract-first approach the repo used for the MUI removal (CLAUDE.md: tests "written and
proved green against the **old** components ... then required to pass untouched").

| # | Test | Asserts |
|---|---|---|
| T1 | Save a 3-line split through `update()` unchanged | Entry still balanced; `total_debits == total_credits`. **Fails before the fix** (§4.1) |
| T2 | `GET feed/` for a split row | `is_split=True`, `split_count=2`, `category is None`, `splits` carries both legs with correct signed amounts |
| T3 | `POST categorize/` on a split | 400, message names the split; entry unchanged |
| T4 | `PATCH batch_edit/` with `category_id` including a split | 400; **no** transaction in the batch is modified (all-or-nothing) |
| T5 | `sync_transfer` on a split whose first leg is a feed asset account | No mirror `BankTransaction` created |
| T6 | Create a split via `POST feed/` | 1 `BankTransaction`, 1 entry, 3 lines, balanced, amounts match example (a) |
| T7 | Each of examples (a)–(d) in §3.3 | Exact `dr`/`cr` per line, as tabulated |
| T8 | Legs that do not sum to the total | 400 (V7); nothing written |
| T9 | Re-split an existing split (2 legs → 3) | 3 legs after; still balanced; bank line's `id` **unchanged** |
| T10 | Re-apportion a split whose bank line is reconciled | 200; bank line's `is_reconciled` still `True`; its `id` unchanged (D9) |
| T11 | Change the total while reconciled | 400 (V11) |
| T12 | `collapse_split` | 2 lines; the single category is the one requested; bank line's `id` unchanged |
| T13 | A leg naming another team's account | 400 "category not found"; nothing written |
| T14 | Zero-amount leg | 400 (V6) |
| T15 | 1 leg and 21 legs | 400 (V1, V2) |
| T16 | Budget actuals after a split | Each leg's category actual equals its own leg amount (proves §4.6 still holds) |
| T17 | Income statement over a split | Total expense equals the sum of the legs, not the transaction total, and not double-counted |
| T18 | Delete a split (`batch_delete`) | Entry and all lines gone; no orphan lines |
| T19 | `_decategorize` a split | Entry deleted; `BankTransaction` survives as uncategorized |

### 11.2 Journal / Transactions tests — extend `apps/journal/tests.py`

| # | Test | Asserts |
|---|---|---|
| T20 | `GET transactions/` with a split in the ledger | The split **appears**. **Fails before §8.1** |
| T21 | A split's row | `debit_account == "Split (2)"`, `credit_account == "Chequing"`, `amount` equals the entry total, `line_count == 3`, `legs` has 3 items |
| T22 | An inflow split's row | The `"Split (N)"` label lands on the **credit** side |
| T23 | A plain 2-line entry, and the $0.00 entry | Byte-identical output to before the change. **This is the regression guard for §8.2** — the two-line branch must be untouched |
| T24 | Date/search filters with splits present | Splits are included; counts include them |

### 11.3 E2E — new file `e2e/tests/test_splits.py`, page object in `e2e/pages/bank_feed.py`

`e2e/factories.py::feed_transaction` (line 141) builds a **2-line** categorized row. Add
a sibling factory:

```python
def split_feed_transaction(team, account, *, legs, **kwargs):
    """One categorized feed row split across several categories.

    `legs` is [(category_account, signed_amount)] in the feed convention
    (positive is an outflow), matching the plan's sign table.
    """
```

Build the bank line from `sum(legs)` using the same two rules as §3.2 — do not hardcode
`Decimal("25.00")` as the existing factory does.

| # | Test |
|---|---|
| E1 | Open a transaction, click "Split this transaction", assign 2 categories, save → feed row shows a `Split (2)` badge |
| E2 | `Remaining` shows the shortfall and Save is disabled until the legs balance |
| E3 | Reopen a saved split → both legs and their amounts are populated |
| E4 | "Remove split" → the single-category Combobox returns, carrying the largest leg |
| E5 | Add a 3rd leg to an existing split and save → badge reads `Split (3)` |
| E6 | Select a split in the feed and bulk-categorize → error toast; row unchanged |
| E7 | The split appears on the Transactions page and the chevron expands to show 3 legs |
| E8 | A reconciled split can be re-apportioned; the amount fields are disabled |

**E2E note from CLAUDE.md:** the `team` fixture bootstraps a whole chart of accounts, so
a test's own categories need a prefix nothing else carries (`Zed …`) or the category
search matches half the chart.

**E2E also needs Vite** — `make start-bg` before running, like every other React page's
suite.

---

## 12. Implementation order

Each phase is independently shippable and leaves the app in a working state. Do them in
this order; do not skip ahead to Phase 4.

| Phase | Work | Tests | Est. |
|---|---|---|---|
| **0** | Write T1–T5 and T20. Watch them fail. Commit the failing tests on their own branch commit so the bugs are on the record. | T1–T5, T20 | 0.5 d |
| **1** | `services/splits.py` (§6.1). Fix §4.1 `update()`, §4.4 `_update_journal_category`, §4.5 `sync_transfer`, §6.4 bulk refusals. **T1, T3, T4, T5 now pass.** | + T8, T10–T15, T18, T19 | 2 d |
| **2** | Split-aware read projections (§6.2). **T2 passes.** Feed table badge (§9.9). | + T16, T17 | 1 d |
| **3** | The write API (§7): `splits` on the serializer, `create()`/`update()` branches, regenerate the API client. | + T6, T7, T9 | 1.5 d |
| **4** | `SplitEditor.jsx` + `EditTransactionModal` split mode (§9.1–9.8). | manual + E1–E5, E8 | 2.5 d |
| **5** | Transactions page (§8): drop the `line_count=2` filter, split-aware row serializer, disclosure UI. **T20 passes.** | + T21–T24, E7 | 1.5 d |
| **6** | E2E suite (§11.3) green end to end. Update `CLAUDE.md`, `docs/design-document.md` decisions log, `docs/testing-guide.md`. | E1–E8 | 1 d |
| **7** | *Optional.* Categorize-mode "Split" button (D12). Any-line account filtering (§8.3). | + E2E | 1–2 d |

**Total: 10–12 days** for Phases 0–6, which is the 6–9 day estimate in the priority
report plus the bug-fixing surface that report flagged and this document then measured.

### Phase gates

- **Do not start Phase 4** until `make test` is green and T1–T5 pass. A UI over a
  corrupting write path is worse than no UI.
- **Do not skip Phase 0.** The four bugs are the reason the estimate is what it is; if the
  tests are written after the fixes, nobody can tell whether they ever caught anything.

---

## 13. Explicitly out of scope

Named so nobody wonders whether they were forgotten:

- **Per-leg memos** (D2) — needs a `JournalLine` text field and a migration.
- **Split templates** ("my usual Costco split") — a real follow-up, not v1.
- **Percentage-based splits** (60/40) — the "assign the rest" affordance (§9.6.6) covers
  most of the need.
- **Splitting across two *bank* accounts** — that is a transfer plus a split, and it is
  not one transaction.
- **Splitting from the CSV import wizard** — the importer creates single-category rows;
  splitting happens afterwards in the feed.
- **Splits in the AI chat / categorize suggestions** — the similar-transaction matcher
  (`apps/bank_feed/services/similar_transactions.py`) excludes nothing about splits
  today; it will suggest the *largest* leg's category via the feed projection. Acceptable.
  Revisit after Phase 7.
- **Any change to reports, budget or net worth.** They already handle splits (§4.6).
  If you find yourself editing `apps/reports/services.py`, stop — you have the data shape
  wrong.

---

## 14. Acceptance criteria

Tick every box before opening the PR.

**Correctness**
- [ ] Saving an existing split unchanged leaves it balanced (T1)
- [ ] `JournalEntry.is_balanced` is true for every entry the new code writes
- [ ] A split's bank line keeps its `id`, `is_reconciled`, `is_cleared`, `is_archived`
      across every edit (T9, T10, T12)
- [ ] All four §3.3 examples produce exactly the tabulated `dr`/`cr` (T7)
- [ ] No split grows a transfer mirror leg (T5)
- [ ] Two-line entries and the $0.00 entry are byte-identical to before (T23)

**Visibility**
- [ ] Splits appear on the Transactions page (T20)
- [ ] A split's feed row shows `Split (N)`, never one leg masquerading as the category
- [ ] Budget actuals and the income statement attribute each leg to its own category
      (T16, T17)

**Editing**
- [ ] A user can split an uncategorized transaction, and a categorized one
- [ ] A user can re-apportion, add a leg, remove a leg, and remove the split
- [ ] Save is impossible while unbalanced, client *and* server (V7)
- [ ] Bulk categorize refuses splits all-or-nothing, with a message (T4, V9)

**Craft**
- [ ] `make test` green; coverage not below 50%
- [ ] `make test-e2e` green — all existing tests pass **untouched**
- [ ] `ruff` clean (120-char lines, double quotes)
- [ ] No hardcoded Tailwind grays; muted text is `/70`
- [ ] Every user-facing string is inside `{% translate %}` / `gettext()`
- [ ] API client regenerated and committed (§7.4)
- [ ] `CLAUDE.md` Recent Changes, `docs/design-document.md` decisions log and
      `docs/testing-guide.md` all updated
- [ ] Money formatted as `$1,234.50` — no `Intl` `style: 'currency'` (`CA$`) anywhere

---

## 15. Quick reference — every file this touches

| File | Change |
|---|---|
| `apps/bank_feed/services/splits.py` | **new** — `apply_splits`, `parse_legs`, `collapse_split`, `is_split`, `SplitError` |
| `apps/bank_feed/services/transfer_mirror.py` | guard `sync_transfer` + `would_orphan_primary` on >2 lines |
| `apps/bank_feed/serializers.py` | `bank_transaction_to_feed_row` split branch; `SplitLegSerializer`; 3 new row fields; `splits` on `ManualTransactionSerializer` |
| `apps/bank_feed/views.py` | rewrite `update()`'s line loop; `create()` split branch; refusals in `_update_journal_category` + `batch_edit`; reconciled-total guard |
| `apps/journal/views.py` | drop `.filter(line_count=2)`; fix the docstring |
| `apps/journal/serializers.py` | `TransactionRowSerializer._sides`, `_side_label`, `line_count`, `legs` |
| `apps/journal/filters.py` | comment recording the largest-leg limitation (§8.3) |
| `apps/bank_feed/tests/test_splits.py` | **new** — T1–T19 |
| `apps/journal/tests.py` | T20–T24 |
| `assets/javascript/bank_feed/react/SplitEditor.jsx` | **new** — the leg table |
| `assets/javascript/bank_feed/react/EditTransactionModal.jsx` | split mode, state, totals, save payload |
| `assets/javascript/bank_feed/react/LineTable.jsx` | `Split (N)` badge |
| `assets/javascript/bank_feed/react/LineApp.jsx` | pass `splits` through both handlers |
| `assets/javascript/bank_feed/bank_feed.js` | `splits` in both request bodies |
| `assets/javascript/transactions/TransactionsTable.jsx` | expandable leg disclosure |
| `e2e/factories.py` | `split_feed_transaction` |
| `e2e/pages/bank_feed.py` | split editor locators |
| `e2e/tests/test_splits.py` | **new** — E1–E8 |
| `api-client/` | regenerated |
| `CLAUDE.md`, `docs/design-document.md`, `docs/testing-guide.md` | updated |

**No migration.** If you have written one, re-read §3.
