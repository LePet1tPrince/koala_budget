# Plaid Account Mapping - Implementation Summary

## Problem Statement
When users link a bank account via Plaid, the `PlaidAccount` records were being created with `account=None`, but the database model didn't allow null values. This caused the token exchange to fail.

## Solution Implemented
Made the `PlaidAccount.account` field nullable and added validation to ensure accounts are mapped before syncing or categorizing transactions.

---

## Changes Made

### 1. Database Model (`apps/plaid/models.py`)

#### Updated Field Definition
```python
account = models.ForeignKey(
    "accounts.Account",
    on_delete=models.PROTECT,
    null=True,        # ✅ ADDED
    blank=True,       # ✅ ADDED
    related_name="plaid_accounts",
    help_text="Ledger account this Plaid account feeds into",
)
```

#### Added Helper Methods
```python
@property
def is_mapped(self):
    """Check if this Plaid account is mapped to a ledger account."""
    return self.account is not None

def can_sync_transactions(self):
    """
    Check if this account is ready to sync transactions.
    Requires both a mapped ledger account and an active Plaid item.
    """
    return self.is_mapped and self.item.is_active
```

#### Updated String Representation
```python
def __str__(self):
    if self.account:
        return f"{self.name} ({self.mask}) → {self.account.name}"
    return f"{self.name} ({self.mask}) [Unmapped]"
```

---

### 2. Sync Endpoint Validation (`apps/plaid/views.py`)

Added validation to `PlaidItemViewSet.sync()` to prevent syncing unmapped accounts:

```python
# Check if all accounts are mapped to ledger accounts
unmapped_accounts = plaid_item.accounts.filter(account__isnull=True)
if unmapped_accounts.exists():
    return Response(
        {
            "error": "Cannot sync transactions. Please map all bank accounts to ledger accounts first.",
            "unmapped_accounts": PlaidAccountSerializer(unmapped_accounts, many=True).data,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )
```

**Response when unmapped accounts exist:**
- HTTP 400 Bad Request
- Error message explaining the issue
- List of unmapped accounts with full details

---

### 3. Categorization Validation (`apps/plaid/views.py`)

Added validation to `create_journal_from_import()` to prevent categorizing transactions from unmapped accounts:

```python
# Validate that the Plaid account is mapped to a ledger account
if not imported_tx.plaid_account.is_mapped:
    raise ValueError(
        f"Cannot categorize transaction: Plaid account '{imported_tx.plaid_account.name}' "
        f"is not mapped to a ledger account. Please map the account first."
    )
```

**Error handling in categorize endpoint:**
```python
try:
    for row in rows:
        if row["source"] == "plaid":
            create_journal_from_import(...)
        elif row["source"] == "ledger":
            update_simple_line_category(...)
except ValueError as e:
    return Response(
        {"error": str(e)},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

---

## User Flow

### 1. Link Bank Account
```
User clicks "Link Bank Account"
    ↓
Plaid Link opens
    ↓
User authenticates with bank
    ↓
Backend creates PlaidItem and PlaidAccount records
    ↓
PlaidAccount.account = NULL ✅ (Now allowed!)
    ↓
Account mapper modal appears
```

### 2. Map Accounts
```
User sees list of unmapped accounts
    ↓
User selects ledger account for each Plaid account
    ↓
Frontend sends PATCH requests to update account field
    ↓
PlaidAccount.account = {selected_account_id} ✅
    ↓
Page reloads with mapped accounts
```

### 3. Sync Transactions
```
User selects account and clicks "Refresh"
    ↓
Backend checks if all accounts are mapped
    ↓
If unmapped: Return error with list of unmapped accounts ❌
If mapped: Start sync task ✅
```

### 4. Categorize Transactions
```
User categorizes a transaction
    ↓
Backend checks if PlaidAccount is mapped
    ↓
If unmapped: Return error message ❌
If mapped: Create journal entry ✅
```

---

## Benefits

### ✅ Data Integrity
- Prevents syncing transactions without knowing which ledger account they belong to
- Prevents creating journal entries with incomplete data
- Clear error messages guide users to fix the issue

### ✅ User Experience
- Users can link accounts and map them in one flow
- Modal provides clear interface for mapping
- Validation prevents confusing errors later

### ✅ Flexibility
- Accounts can be created without immediate mapping
- Users can map accounts at their convenience
- Easy to identify unmapped accounts in admin panel

### ✅ Maintainability
- Helper methods (`is_mapped`, `can_sync_transactions`) make code more readable
- Validation is centralized and reusable
- Clear error messages make debugging easier

---

## Migration

### Created Migration
```bash
python manage.py makemigrations plaid
# Creates migration to add null=True, blank=True to account field

python manage.py migrate
# Applies the migration
```

### Migration Details
- **Operation:** `AlterField` on `PlaidAccount.account`
- **Changes:** Added `null=True, blank=True`
- **Backwards Compatible:** Yes (existing records already have account values)
- **Data Loss:** None

---

## Testing

See `PLAID_ACCOUNT_MAPPING_TESTING.md` for comprehensive testing guide.

### Quick Test
1. Link a bank account via Plaid Link
2. Verify account mapper modal appears
3. Map all accounts and save
4. Verify accounts appear in selection grid
5. Click refresh to sync transactions
6. Verify transactions appear

---

## API Endpoints Affected

### `POST /a/{team}/plaid/api/items/{id}/sync/`
- **New Behavior:** Validates all accounts are mapped before syncing
- **Error Response:** HTTP 400 with unmapped accounts list

### `POST /a/{team}/plaid/api/bank-feed/categorize/`
- **New Behavior:** Validates account is mapped before categorizing
- **Error Response:** HTTP 400 with error message

### `PATCH /a/{team}/plaid/api/accounts/{id}/`
- **Existing Behavior:** Updates PlaidAccount fields including `account`
- **No Changes:** Already working as expected

---

## Future Enhancements

- [ ] Add bulk mapping endpoint to map multiple accounts at once
- [ ] Add auto-mapping based on account type and name matching
- [ ] Add warning in UI when accounts are unmapped
- [ ] Add admin action to identify and fix unmapped accounts
- [ ] Add periodic task to notify users of unmapped accounts
- [ ] Add ability to remap accounts after initial mapping

---

## Documentation Updated

- ✅ `PLAID_FRONTEND_INTEGRATION.md` - Added sections for model changes and validation
- ✅ `PLAID_ACCOUNT_MAPPING_TESTING.md` - Comprehensive testing guide
- ✅ `PLAID_ACCOUNT_MAPPING_SUMMARY.md` - This document

---

## Conclusion

The account mapping functionality is now fully implemented and validated. Users can:
1. Link bank accounts via Plaid
2. Map them to ledger accounts via the UI
3. Sync transactions only after mapping
4. Categorize transactions only from mapped accounts

All validation is in place to ensure data integrity and provide clear error messages.

