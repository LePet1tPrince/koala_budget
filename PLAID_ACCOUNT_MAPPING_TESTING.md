# Plaid Account Mapping - Testing Guide

## Overview
This guide covers testing the account mapping functionality after making the `PlaidAccount.account` field nullable.

## Changes Made

### 1. Database Model
- **File:** `apps/plaid/models.py`
- **Change:** Made `account` field nullable (`null=True, blank=True`)
- **Migration:** Created and applied migration

### 2. Model Methods
- Added `is_mapped` property to check if account is mapped
- Added `can_sync_transactions()` method to validate readiness
- Updated `__str__` method to handle unmapped accounts

### 3. API Validation
- Sync endpoint validates all accounts are mapped before syncing
- Categorize endpoint validates account is mapped before creating journal entries

---

## Testing Checklist

### ✅ Phase 1: Link Bank Account (Create Unmapped Accounts)

1. **Navigate to Journal Lines Page**
   ```
   /a/{team-slug}/journal/lines/
   ```

2. **Click "Link Bank Account" Button**
   - Plaid Link modal should open
   - No errors in browser console

3. **Complete Plaid Link Flow**
   - Select "First Platypus Bank" (sandbox)
   - Username: `user_good`
   - Password: `pass_good`
   - Select accounts to link
   - Click "Continue"

4. **Verify PlaidAccount Records Created**
   ```sql
   SELECT id, name, mask, type, subtype, account_id 
   FROM plaid_plaidaccount 
   ORDER BY created_at DESC;
   ```
   - `account_id` should be `NULL` for newly created accounts ✅

5. **Verify Account Mapper Modal Appears**
   - Modal should show all newly linked accounts
   - Each account should have a dropdown to select ledger account
   - "Save Mappings" button should be disabled until all accounts are mapped

---

### ✅ Phase 2: Map Accounts to Ledger

1. **Select Ledger Account for Each Plaid Account**
   - Use the dropdown to select an appropriate ledger account
   - Verify account details are displayed correctly (name, mask, type, subtype)

2. **Attempt to Save with Unmapped Accounts**
   - Leave one account unmapped
   - Click "Save Mappings"
   - Should show error: "Please map all accounts before saving."

3. **Map All Accounts and Save**
   - Map all accounts
   - Click "Save Mappings"
   - Modal should close
   - Page should reload

4. **Verify Mappings in Database**
   ```sql
   SELECT pa.id, pa.name, pa.mask, a.name as ledger_account_name, a.account_id
   FROM plaid_plaidaccount pa
   LEFT JOIN accounts_account a ON pa.account_id = a.account_id
   ORDER BY pa.created_at DESC;
   ```
   - All `account_id` fields should now have values ✅
   - Ledger account names should match what you selected

5. **Verify Accounts Appear in Selection Grid**
   - Newly linked accounts should appear in the account selection grid
   - Accounts should show bank feed indicator

---

### ✅ Phase 3: Test Sync Validation

1. **Create an Unmapped Account (Manual Test)**
   ```python
   # In Django shell
   from apps.plaid.models import PlaidItem, PlaidAccount
   
   item = PlaidItem.objects.first()
   unmapped = PlaidAccount.objects.create(
       team=item.team,
       plaid_account_id="test_unmapped_123",
       item=item,
       account=None,  # Unmapped
       name="Test Unmapped Account",
       mask="1234",
       type="depository",
       subtype="checking"
   )
   ```

2. **Attempt to Sync Item with Unmapped Account**
   - Select the account in the UI
   - Click "Refresh" button
   - Should receive error response:
     ```json
     {
       "error": "Cannot sync transactions. Please map all bank accounts to ledger accounts first.",
       "unmapped_accounts": [...]
     }
     ```

3. **Map the Account and Retry**
   - Map the unmapped account via PATCH request or admin panel
   - Click "Refresh" again
   - Should succeed and start syncing

---

### ✅ Phase 4: Test Categorization Validation

1. **Create an Imported Transaction for Unmapped Account**
   ```python
   # In Django shell
   from apps.plaid.models import ImportedTransaction
   from decimal import Decimal
   from datetime import date
   
   tx = ImportedTransaction.objects.create(
       team=unmapped.team,
       plaid_transaction_id="test_tx_123",
       plaid_account=unmapped,  # Unmapped account
       amount=Decimal("50.00"),
       date=date.today(),
       name="Test Transaction",
       raw={}
   )
   ```

2. **Attempt to Categorize the Transaction**
   - Try to categorize via the bank feed UI
   - Should receive error:
     ```
     "Cannot categorize transaction: Plaid account 'Test Unmapped Account' 
     is not mapped to a ledger account. Please map the account first."
     ```

3. **Map Account and Retry**
   - Map the account
   - Categorize the transaction again
   - Should succeed

---

### ✅ Phase 5: Test Model Methods

```python
# In Django shell
from apps.plaid.models import PlaidAccount

# Test unmapped account
unmapped = PlaidAccount.objects.filter(account__isnull=True).first()
print(unmapped.is_mapped)  # Should be False
print(unmapped.can_sync_transactions())  # Should be False
print(str(unmapped))  # Should show "[Unmapped]"

# Test mapped account
mapped = PlaidAccount.objects.filter(account__isnull=False).first()
print(mapped.is_mapped)  # Should be True
print(mapped.can_sync_transactions())  # Should be True (if item is active)
print(str(mapped))  # Should show "Account Name (1234) → Ledger Account Name"
```

---

## Expected Behavior Summary

### ✅ Unmapped Accounts
- Can be created via Plaid Link
- Cannot sync transactions
- Cannot categorize transactions
- Show "[Unmapped]" in string representation
- `is_mapped` returns `False`
- `can_sync_transactions()` returns `False`

### ✅ Mapped Accounts
- Can sync transactions (if item is active)
- Can categorize transactions
- Show proper mapping in string representation
- `is_mapped` returns `True`
- `can_sync_transactions()` returns `True` (if item is active)

---

## Cleanup After Testing

```python
# Delete test accounts
PlaidAccount.objects.filter(plaid_account_id__startswith="test_").delete()
ImportedTransaction.objects.filter(plaid_transaction_id__startswith="test_").delete()
```

---

## Common Issues

### Issue: Migration fails
**Solution:** Ensure you've run `python manage.py makemigrations plaid` and `python manage.py migrate`

### Issue: Account mapper doesn't show
**Solution:** Check browser console for errors. Verify PlaidAccountMapper component is imported.

### Issue: PATCH requests fail
**Solution:** Verify CSRF token is being sent. Check that PlaidAccountViewSet allows PATCH.

### Issue: Sync still works with unmapped accounts
**Solution:** Clear cache, restart server, verify validation code is in place.

