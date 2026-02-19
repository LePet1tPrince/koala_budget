# Implementation Plan: Budget Actual Column Tooltip with Recategorize

## Overview

Add interactive functionality to the "Actual" column in the budget table. When users click on an actual amount (e.g., $200.02), a tooltip/popover appears showing a table of transactions that sum to that amount. Each transaction row includes a "Recategorize" dropdown to move the transaction to a different category.

## Why React Instead of Pure Django Templates

Given the requirements:
- **Click-triggered tooltip** with a table inside
- **Interactive dropdown** for recategorizing on each row
- **API calls** to fetch transaction details and update categories
- **State management** for the dropdown and loading states

Pure Django templates with Alpine.js could handle simple tooltips, but the recategorize dropdown + API integration makes React the better choice. This follows the existing pattern used in `bank_feed/bank_feed_home.html`.

---

## Implementation Steps

### Phase 1: Backend - Extend Existing Journal API

**Approach:** Extend the existing `SimpleLineViewSet` in the journal app rather than creating new endpoints in budget. This keeps JournalLine operations centralized.

#### 1.1 Add Query Param Filtering to SimpleLineViewSet

**File:** `apps/journal/views.py`

Add filtering by `account` and `month` query parameters:

```python
def get_queryset(self):
    qs = JournalLine.for_team.select_related(...)

    # Filter by account (category) if provided
    account_id = self.request.query_params.get('account')
    if account_id:
        qs = qs.filter(account_id=account_id)

    # Filter by month if provided (YYYY-MM-DD format)
    month = self.request.query_params.get('month')
    if month:
        start, end = month_bounds(parse_date(month))
        qs = qs.filter(journal_entry__entry_date__gte=start, journal_entry__entry_date__lt=end)

    return qs
```

#### 1.2 Add Recategorize Action to SimpleLineViewSet

**File:** `apps/journal/views.py`

```python
@action(detail=True, methods=["post"])
def recategorize(self, request, pk=None, team_slug=None):
    """
    Recategorize a journal line to a different account/category.
    POST body: { "new_category_id": 456 }
    """
    line = self.get_object()
    new_category_id = request.data.get('new_category_id')

    new_category = get_object_or_404(Account.for_team, id=new_category_id)
    line.account = new_category
    line.save()

    return Response({'status': 'success', 'line_id': line.id})
```

#### 1.3 URL Structure (Already Configured)

The existing router in `apps/journal/urls.py` already provides:
- `GET /journal/api/lines/?account={id}&month={YYYY-MM-DD}` - List with filters
- `POST /journal/api/lines/{id}/recategorize/` - New action

---

### Phase 2: Frontend - React Component

#### 2.1 Create React Entry Point

**File:** `assets/javascript/budget/budget-actual-app.jsx`

```jsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import ActualTooltip from './react/ActualTooltip';

// Initialize all actual tooltips on the page
document.querySelectorAll('[data-actual-tooltip]').forEach((element) => {
    const root = createRoot(element);
    const categoryId = element.dataset.categoryId;
    const amount = element.dataset.amount;
    const month = element.dataset.month;

    root.render(
        <ActualTooltip
            categoryId={categoryId}
            amount={amount}
            month={month}
        />
    );
});
```

#### 2.2 Create ActualTooltip Component

**File:** `assets/javascript/budget/react/ActualTooltip.jsx`

```jsx
import React, { useState, useRef, useEffect } from 'react';
import { Popover, Table, TableBody, TableCell, TableHead, TableRow,
         Select, MenuItem, CircularProgress, Alert, Snackbar } from '@mui/material';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import { formatCurrency } from '../../utilities/currency';

/* globals gettext, SERVER_URL_BASE */

const ActualTooltip = ({ categoryId, amount, month }) => {
    const [anchorEl, setAnchorEl] = useState(null);
    const [transactions, setTransactions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [categories, setCategories] = useState([]);
    const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });

    const apiUrls = JSON.parse(document.getElementById('api-urls').textContent);
    const allAccounts = JSON.parse(document.getElementById('all-accounts').textContent);

    const handleClick = async (event) => {
        setAnchorEl(event.currentTarget);
        await fetchTransactions();
    };

    const handleClose = () => {
        setAnchorEl(null);
    };

    const fetchTransactions = async () => {
        setLoading(true);
        try {
            const response = await fetch(
                `${apiUrls.categoryTransactions}?category_id=${categoryId}&month=${month}`
            );
            const data = await response.json();
            setTransactions(data.results || data);
        } catch (error) {
            console.error('Failed to fetch transactions:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleRecategorize = async (lineId, newCategoryId) => {
        try {
            const response = await fetch(apiUrls.recategorize, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({ line_id: lineId, new_category_id: newCategoryId }),
            });

            if (response.ok) {
                // Remove the recategorized transaction from local state
                setTransactions(transactions.filter(t => t.id !== lineId));
                setSnackbar({ open: true, message: gettext('Transaction recategorized'), severity: 'success' });
            }
        } catch (error) {
            setSnackbar({ open: true, message: gettext('Failed to recategorize'), severity: 'error' });
        }
    };

    const open = Boolean(anchorEl);

    return (
        <>
            <span
                className="font-mono cursor-pointer hover:underline text-primary"
                onClick={handleClick}
            >
                {formatCurrency(amount)}
            </span>

            <Popover
                open={open}
                anchorEl={anchorEl}
                onClose={handleClose}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
                transformOrigin={{ vertical: 'top', horizontal: 'center' }}
            >
                <div className="p-4 min-w-[400px] max-w-[600px] max-h-[400px] overflow-auto">
                    <h3 className="font-bold mb-2">{gettext('Transaction Details')}</h3>

                    {loading ? (
                        <CircularProgress size={24} />
                    ) : (
                        <Table size="small">
                            <TableHead>
                                <TableRow>
                                    <TableCell>{gettext('Date')}</TableCell>
                                    <TableCell>{gettext('Payee')}</TableCell>
                                    <TableCell>{gettext('Memo')}</TableCell>
                                    <TableCell align="right">{gettext('Amount')}</TableCell>
                                    <TableCell>{gettext('Recategorize')}</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {transactions.map((tx) => (
                                    <TableRow key={tx.id}>
                                        <TableCell>{tx.date}</TableCell>
                                        <TableCell>{tx.payee || '-'}</TableCell>
                                        <TableCell className="max-w-[150px] truncate">{tx.memo}</TableCell>
                                        <TableCell align="right">{formatCurrency(tx.amount)}</TableCell>
                                        <TableCell>
                                            <Select
                                                size="small"
                                                value=""
                                                displayEmpty
                                                onChange={(e) => handleRecategorize(tx.id, e.target.value)}
                                            >
                                                <MenuItem value="" disabled>
                                                    {gettext('Move to...')}
                                                </MenuItem>
                                                {allAccounts
                                                    .filter(a => a.id !== categoryId)
                                                    .map(account => (
                                                        <MenuItem key={account.id} value={account.id}>
                                                            {account.name}
                                                        </MenuItem>
                                                    ))
                                                }
                                            </Select>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}

                    {!loading && transactions.length === 0 && (
                        <p className="text-gray-500">{gettext('No transactions found')}</p>
                    )}
                </div>
            </Popover>

            <Snackbar
                open={snackbar.open}
                autoHideDuration={3000}
                onClose={() => setSnackbar({...snackbar, open: false})}
            >
                <Alert severity={snackbar.severity}>{snackbar.message}</Alert>
            </Snackbar>
        </>
    );
};

export default ActualTooltip;
```

---

### Phase 3: Template Integration

#### 3.1 Update Budget Table Template

**File:** `templates/budget/components/budget_table.html`

Replace the static actual amount display with a React mount point:

```html
<!-- Before -->
<td class="text-right">
    <span class="font-mono">{{ row.actual|floatformat:2 }}</span>
</td>

<!-- After -->
<td class="text-right">
    <div data-actual-tooltip
         data-category-id="{{ row.category.id }}"
         data-amount="{{ row.actual }}"
         data-month="{{ month|date:'Y-m-d' }}">
        <span class="font-mono">{{ row.actual|floatformat:2 }}</span>
    </div>
</td>
```

#### 3.2 Update Budget Home Template

**File:** `templates/budget/budget_home.html`

Add React integration scripts and data:

```html
{% load django_vite %}

{% block extra_head %}
{# Pass data to React #}
{{ all_accounts|json_script:'all-accounts' }}
{{ api_urls|json_script:'api-urls' }}
{% endblock %}

{% block page_js %}
<script>
    const SERVER_URL_BASE = "{{ request.scheme }}://{{ request.get_host }}";
</script>
{% vite_react_refresh %}
{% vite_asset 'assets/javascript/budget/budget-actual-app.jsx' %}
{% endblock %}
```

#### 3.3 Update Budget View

**File:** `apps/budget/views.py`

Pass additional data needed by React:

```python
def budget_month_view(request, team_slug):
    # ... existing code ...

    # Get all accounts for recategorize dropdown
    all_accounts = Account.for_team.filter(
        account_group__account_type__in=("expense", "income"),
    ).values('id', 'name', 'account_number')

    # API URLs for React
    api_urls = {
        'categoryTransactions': f'/a/{team_slug}/budget/api/category-transactions/',
        'recategorize': f'/a/{team_slug}/budget/api/recategorize/',
    }

    return render(request, "budget/budget_home.html", {
        # ... existing context ...
        'all_accounts': list(all_accounts),
        'api_urls': api_urls,
    })
```

---

## File Summary

### New Files to Create:
1. `apps/budget/serializers.py` - CategoryTransactionSerializer
2. `assets/javascript/budget/budget-actual-app.jsx` - React entry point
3. `assets/javascript/budget/react/ActualTooltip.jsx` - Main tooltip component

### Files to Modify:
1. `apps/budget/views.py` - Add API viewset and recategorize endpoint
2. `apps/budget/urls.py` - Add API routes
3. `templates/budget/components/budget_table.html` - Add data attributes for React
4. `templates/budget/budget_home.html` - Add React scripts and data

---

## Data Flow

```
User clicks on Actual amount ($200.02)
    ↓
ActualTooltip opens Popover
    ↓
Fetches transactions from /api/category-transactions/?category_id=X&month=Y
    ↓
Displays table with Date, Payee, Memo, Amount, Recategorize dropdown
    ↓
User selects new category from dropdown
    ↓
POST to /api/recategorize/ with line_id and new_category_id
    ↓
Transaction removed from tooltip (moves to new category)
    ↓
Snackbar shows success message
```

---

## Styling Notes

- Uses MUI components (Popover, Table, Select) for consistency with LineTableMaterial.jsx
- Tailwind/DaisyUI classes for basic styling (font-mono, text-primary, etc.)
- ThemeProvider with dark mode detection (following existing pattern)
- Responsive max-width and max-height for the popover content

---

## Testing Considerations

1. **API Tests:**
   - Test category-transactions endpoint with valid/invalid params
   - Test recategorize endpoint permissions and validation

2. **Component Tests:**
   - Test tooltip opens on click
   - Test transactions load and display correctly
   - Test recategorize updates state

3. **Integration Tests:**
   - Test full flow from click to recategorize
   - Test error handling for failed API calls

---

## Alternative Approaches Considered

1. **Pure Alpine.js + DaisyUI Tooltip**: Simpler but limited interactivity for the recategorize dropdown and API calls.

2. **HTMX**: Could handle the fetch but recategorize dropdown state management would be awkward.

3. **Full React Budget Table**: More comprehensive but higher effort; the current approach surgically adds React only where needed.

The chosen approach (React tooltips injected into Django template) balances complexity with functionality, following the existing pattern in the codebase.
