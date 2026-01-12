# Plaid Frontend Integration - Implementation Summary

## Overview
This document describes the frontend integration for Plaid bank feeds, including the ability to link bank accounts, map them to ledger accounts, and refresh transaction data.

## Components Created

### 1. PlaidLinkButton Component
**File:** `assets/javascript/journal/react/PlaidLinkButton.jsx`

**Purpose:** Handles the Plaid Link flow for connecting bank accounts

**Features:**
- Fetches a `link_token` from the backend
- Initializes Plaid Link using the `react-plaid-link` library
- Handles the OAuth flow securely
- Exchanges the `public_token` for an `access_token` on the backend
- Triggers the account mapping modal after successful linking

**Security:**
- ✅ Only `link_token` and `public_token` are handled in the frontend
- ✅ `access_token` is created and stored on the backend only
- ✅ Follows Plaid's recommended security practices

### 2. PlaidAccountMapper Component
**File:** `assets/javascript/journal/react/PlaidAccountMapper.jsx`

**Purpose:** Modal for mapping newly linked Plaid accounts to existing ledger accounts

**Features:**
- Displays all newly created Plaid accounts with their details
- Allows users to select a corresponding ledger account for each Plaid account
- Validates that all accounts are mapped before saving
- Updates the PlaidAccount records via PATCH requests

**UI Elements:**
- Account type badges (depository, credit, loan, investment)
- Account details (name, official name, subtype, mask)
- Dropdown to select ledger account
- Save/Cancel buttons

### 3. Updated LineApp Component
**File:** `assets/javascript/journal/react/LineApp.jsx`

**Changes:**
- Added PlaidLinkButton to the account selection section
- Added refresh button to the lines table section
- Implemented `handleRefresh()` to sync transactions from Plaid
- Implemented `handlePlaidSuccess()` to reload page after linking

**New Features:**
- Users can link new bank accounts directly from the journal lines page
- Users can refresh transaction data for the selected account
- Refresh button shows loading state while syncing

## Backend Changes

### 1. PlaidItemViewSet - Added Sync Endpoint
**File:** `apps/plaid/views.py`

**New Action:** `sync()`
- **URL:** `/a/{team_slug}/plaid/api/items/{id}/sync/`
- **Method:** POST
- **Purpose:** Triggers a Celery task to sync transactions for a specific Plaid item
- **Returns:** Task ID and status

### 2. PlaidAccountViewSet - Enabled PATCH
**File:** `apps/plaid/views.py`

**Changes:**
- Changed from `ReadOnlyModelViewSet` to `ModelViewSet`
- Restricted HTTP methods to `["get", "patch"]`
- Allows updating the `account` field to map Plaid accounts to ledger accounts

### 3. PlaidAccount Model - Made Account Field Nullable
**File:** `apps/plaid/models.py`

**Changes:**
- Added `null=True, blank=True` to the `account` ForeignKey field
- Allows PlaidAccount records to be created without a ledger account mapping initially
- Added `is_mapped` property to check if account is mapped
- Added `can_sync_transactions()` method to validate readiness for syncing
- Updated `__str__` method to handle unmapped accounts gracefully

### 4. Sync Endpoint - Added Validation
**File:** `apps/plaid/views.py`

**Changes:**
- Added validation to prevent syncing transactions for items with unmapped accounts
- Returns HTTP 400 with error message and list of unmapped accounts if validation fails
- Ensures data integrity by requiring all accounts to be mapped before syncing

### 5. Categorize Endpoint - Added Validation
**File:** `apps/plaid/views.py`

**Changes:**
- Added validation in `create_journal_from_import()` to check if PlaidAccount is mapped
- Raises `ValueError` if attempting to categorize a transaction from an unmapped account
- Error is caught in the categorize endpoint and returned as HTTP 400

## Dependencies Added

### NPM Package
```bash
npm install --save react-plaid-link
```

**Package:** `react-plaid-link`
**Purpose:** Official Plaid React SDK for integrating Plaid Link

## User Flow

### Linking a Bank Account
1. User clicks "Link Bank Account" button
2. Backend creates a `link_token` and returns it to frontend
3. Plaid Link modal opens
4. User authenticates with their bank
5. Plaid returns a `public_token` to the frontend
6. Frontend sends `public_token` to backend
7. Backend exchanges it for an `access_token` and creates PlaidItem and PlaidAccount records
8. Account mapper modal appears
9. User maps each Plaid account to a ledger account
10. Frontend sends PATCH requests to update PlaidAccount records
11. Page reloads to show newly linked accounts

### Refreshing Transaction Data
1. User selects an account with a bank feed
2. User clicks "Refresh" button
3. Frontend fetches the PlaidAccount for the selected ledger account
4. Frontend triggers sync endpoint for the PlaidItem
5. Backend starts a Celery task to sync transactions
6. After 2 seconds, frontend reloads the lines to show new transactions

## API Endpoints Used

### Frontend → Backend
- `POST /a/{team_slug}/plaid/api/link-token/` - Create link token
- `POST /a/{team_slug}/plaid/api/exchange-token/` - Exchange public token
- `GET /a/{team_slug}/plaid/api/accounts/?account={id}` - Get Plaid account by ledger account
- `PATCH /a/{team_slug}/plaid/api/accounts/{id}/` - Update Plaid account mapping
- `POST /a/{team_slug}/plaid/api/items/{id}/sync/` - Trigger transaction sync

## Testing Checklist

- [ ] Link a new bank account via Plaid Link
- [ ] Verify account mapper modal appears with correct account details
- [ ] Map Plaid accounts to ledger accounts
- [ ] Verify PlaidAccount records are updated in the database
- [ ] Verify page reloads and shows newly linked accounts
- [ ] Select an account with a bank feed
- [ ] Click refresh button
- [ ] Verify transactions are synced from Plaid
- [ ] Verify new transactions appear in the lines table
- [ ] Test error handling (network errors, invalid tokens, etc.)
- [ ] Test with multiple accounts
- [ ] Test with different account types (checking, savings, credit card)

## Security Considerations

✅ **Secure Token Handling:**
- `link_token`: Short-lived (4 hours), one-time use, only for UI initialization
- `public_token`: Temporary (30 minutes), single-use, exchanged on backend
- `access_token`: Never exposed to frontend, stored securely in database

✅ **CSRF Protection:**
- All POST/PATCH requests include CSRF token from cookies or DOM

✅ **Team Permissions:**
- All API endpoints use `TeamModelAccessPermissions`
- Users can only access data for their team

## Future Enhancements

- [ ] Add real-time sync status updates using WebSockets
- [ ] Add ability to unlink bank accounts
- [ ] Add ability to re-authenticate expired Plaid items
- [ ] Add transaction categorization suggestions based on Plaid's personal finance categories
- [ ] Add bulk categorization for multiple transactions
- [ ] Add filtering and search for bank feed transactions
