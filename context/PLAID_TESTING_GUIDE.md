# Plaid Frontend Integration - Testing Guide

## Prerequisites

1. **Plaid Account Setup**
   - Ensure you have Plaid API credentials in your `.env` file:
     ```
     PLAID_CLIENT_ID=your_client_id
     PLAID_SECRET=your_secret
     PLAID_ENV=sandbox  # or development/production
     ```

2. **Dependencies Installed**
   - Run: `make npm-install react-plaid-link` (already done)

3. **Services Running**
   - Django server: `make start` or `make start-bg`
   - Celery worker (for transaction sync): Check your docker-compose setup

## Testing Steps

### 1. Build Frontend Assets
```bash
make npm-build
# or for development with hot reload:
make npm-dev
```

### 2. Access the Journal Lines Page
1. Log in to your application
2. Navigate to: `/a/{your-team-slug}/journal/lines/`
3. You should see the "Link Bank Account" button in the top right

### 3. Test Linking a Bank Account

#### Using Plaid Sandbox
1. Click "Link Bank Account"
2. Plaid Link modal should open
3. Select any institution (e.g., "First Platypus Bank")
4. Use Plaid sandbox credentials:
   - Username: `user_good`
   - Password: `pass_good`
5. Select accounts to link
6. Click "Continue"

#### Expected Behavior
- Plaid Link closes
- Account mapper modal appears
- Shows all linked accounts with details
- Each account has a dropdown to select a ledger account

### 4. Test Account Mapping
1. For each Plaid account, select a corresponding ledger account from the dropdown
2. Click "Save Mappings"
3. Page should reload
4. Newly linked accounts should appear in the account selection grid

### 5. Test Transaction Refresh
1. Select an account that has a bank feed (one you just linked)
2. Click the "Refresh" button in the lines table section
3. Button should show "Refreshing..." with a spinner
4. After ~2 seconds, transactions should appear in the table

### 6. Verify Data in Database

#### Check PlaidItem
```bash
make dbshell
```
```sql
SELECT id, institution_name, is_active, cursor FROM plaid_plaiditem;
```

#### Check PlaidAccount
```sql
SELECT id, name, mask, type, subtype, account_id FROM plaid_plaidaccount;
```

#### Check ImportedTransaction
```sql
SELECT id, name, amount, date, pending FROM plaid_importedtransaction LIMIT 10;
```

## Plaid Sandbox Test Credentials

### Institutions
- **First Platypus Bank** - Full featured test bank
- **Tartan Bank** - Another test bank
- **Houndstooth Bank** - Test bank with specific scenarios

### Credentials
- **Success:** `user_good` / `pass_good`
- **MFA:** `user_good` / `pass_good` (will prompt for MFA)
- **Invalid Credentials:** `user_bad` / `pass_bad`

### Test Account Numbers
Plaid sandbox will create test accounts automatically when you link.

## Common Issues and Solutions

### Issue: "Failed to initialize Plaid Link"
**Solution:** Check that your Plaid credentials are correct in `.env`

### Issue: "Failed to exchange token"
**Solution:** 
- Check backend logs for errors
- Verify the exchange-token endpoint is working
- Ensure CSRF token is being sent correctly

### Issue: Account mapper doesn't show
**Solution:**
- Check browser console for JavaScript errors
- Verify PlaidAccountMapper component is imported correctly
- Check that accounts were created in the database

### Issue: Refresh button doesn't work
**Solution:**
- Verify Celery worker is running
- Check that the PlaidAccount has an `item` foreign key set
- Check backend logs for sync errors

### Issue: No transactions appear after refresh
**Solution:**
- Plaid sandbox accounts may not have transactions by default
- Check the ImportedTransaction table to see if transactions were created
- Verify the account mapping is correct

## Browser Console Debugging

Open browser DevTools (F12) and check:

1. **Network Tab:**
   - Look for requests to `/plaid/api/link-token/`
   - Look for requests to `/plaid/api/exchange-token/`
   - Look for requests to `/plaid/api/accounts/`
   - Look for requests to `/plaid/api/items/{id}/sync/`

2. **Console Tab:**
   - Look for any JavaScript errors
   - Check for Plaid Link events being logged

## Backend Logs

Check Django logs for:
```bash
make ssh
# Inside container:
tail -f /var/log/django.log  # or wherever your logs are
```

Look for:
- Link token creation
- Token exchange
- Account creation
- Transaction sync task execution

## Celery Task Monitoring

If you have Flower or another Celery monitoring tool:
1. Check that `sync_plaid_transactions` task is being triggered
2. Verify task completes successfully
3. Check task result for number of transactions added/modified/removed

## Next Steps After Testing

Once basic functionality is verified:

1. **Test Error Scenarios:**
   - Invalid credentials
   - Network errors
   - Expired tokens
   - Unmapped accounts

2. **Test Edge Cases:**
   - Multiple accounts from same institution
   - Different account types (checking, savings, credit)
   - Pending vs. posted transactions

3. **Performance Testing:**
   - Link multiple institutions
   - Sync large number of transactions
   - Test with slow network

4. **UI/UX Testing:**
   - Mobile responsiveness
   - Loading states
   - Error messages
   - Success feedback

## Support Resources

- **Plaid Documentation:** https://plaid.com/docs/
- **Plaid Sandbox Guide:** https://plaid.com/docs/sandbox/
- **React Plaid Link:** https://github.com/plaid/react-plaid-link

