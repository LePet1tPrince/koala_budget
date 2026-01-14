# Income Statement Drill-Down Report Implementation Prompt

## Context
You are working inside a Django personal finance application that uses **double-entry accounting**.

Core models:
- `JournalEntry` (date, payee, memo, status, etc.)
- `JournalLine` (account, dr_amount, cr_amount)
- `Account` → `AccountGroup` → `account_type`
  (`INCOME`, `EXPENSE`, `ASSET`, `LIABILITY`, `EQUITY`)

All reporting data must be derived from **JournalLine**.

A `ReportService` already exists and produces:
- Income Statement
- Balance Sheet
- Net Worth Trend

An income statement view, template, and date filter form already exist.

---

## Objective
Implement an **Income Statement with drill-down**, where:

1. The Income Statement displays:
   - Summarized Income accounts
   - Summarized Expense accounts
   - Totals and net profit

2. Clicking any income or expense line item drills down into:
   - Individual transactions for that account
   - Using the **same date range**
   - Within a URL that is an **extension of the income statement URL**

---

## URL Design (IMPORTANT)

The drill-down view **must be nested under the income statement URL**:

```
/reports/income-statement/
/reports/income-statement/account/<account_id>/
```

Date filters must be preserved using the query string.

This enforces a clear conceptual hierarchy:
- Income Statement → Account Detail

---

## Architectural Rules
- **Do NOT create new tables**
- **Do NOT denormalize data**
- All report data must come from `JournalLine`
- Keep aggregation logic inside `ReportService`
- Views should be thin
- Sign logic must be consistent between summary and detail views
- Templates must not contain business logic

---

## Required Changes

### 1. Extend `ReportService`
Add a reusable method:

```
get_account_activity(account, start_date, end_date)
```

This method must:
- Filter `JournalLine` by team and account
- Filter by date range (if provided)
- `select_related` required `JournalEntry` fields
- Annotate a signed `amount`:
  - Income: `cr_amount - dr_amount`
  - Expense: `dr_amount - cr_amount`
- Order by entry date ascending

Do **not** modify existing summary methods.

---

### 2. Create a Drill-Down View
Add a Django view that:
- Lives under the income statement route
- Accepts `account_id`
- Uses the same date filter form
- Calls `get_account_activity`
- Computes a total for the account
- Renders a dedicated detail template

---

### 3. URL Configuration
Update routing so the drill-down URL is an extension of the income statement:

```
income-statement/
income-statement/account/<int:account_id>/
```

The drill-down view must not be accessible outside this hierarchy.

---

### 4. Update Income Statement Template
Modify the income statement template so that:
- Each income and expense account name is clickable
- Links point to:
  ```
  income-statement/account/<account_id>/?<existing query params>
  ```
- Date filters are preserved automatically

---

### 5. Account Activity Template
Create a detail template that displays:
- Entry date
- Payee
- Memo / description
- Signed amount
- Footer total

This view represents a **ledger-style breakdown** for the selected account.

---

## Quality Expectations
- Clean separation of concerns
- Reusable service methods
- Predictable URL structure
- Code should feel production-ready
- Architecture should support future expansion:
  - Ledger views
  - Monthly subtotals
  - Charts
  - API endpoints

---

## Deliverables
- Updated `ReportService`
- New drill-down view under income statement
- Updated URL configuration
- Updated income statement template
- New account activity template

---

## Non-Goals
- No frontend JS or React
- No API endpoints
- No pagination
- No audit logging

---

If implemented correctly, the result should feel like a **professional accounting report system**, similar to QuickBooks or Wave, with intuitive drill-down behavior.
