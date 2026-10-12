# Double-entry budgeting: concept

## Context
Today, budget state lives outside the ledger: `Budget` rows, `GoalAllocation` rows, and a computed `compute_unassigned()`. The proposal is to make budgeting real journal entries, so that Unassigned, envelopes and goals become account balances instead of formulas.

## Core idea
Net worth = equity. We split equity into named buckets that say what each dollar is for. Budgeting then just moves equity between buckets, and net worth never changes when it does. The precedent is government fund accounting (appropriations / budgetary fund balance).

## New account types (all equity-side)
| Type | One per | Normal balance | Meaning |
|---|---|---|---|
| **Unassigned** | book (system) | credit | Money with no job |
| **Envelope** | expense category | credit | Money set aside for that category |
| **Goal** | goal (exists today) | credit | Money saved for the goal |
| **Expected income** | income category | debit | Income budgeted but not yet received (only when "budget future income" is on) |

The existing Reconciliation Adjustments equity (opening balances, adjustments) merges into **Unassigned**.

## Example chart of accounts
Pairing rule: each bucket is paired with its Income or Expense account by matching the last digits (3110 ↔ 5110). "Available" is the bucket's balance minus its paired account's activity.

```
1000 ASSETS
  1010 Chequing                     6,000
  1020 Savings                     10,000
2000 LIABILITIES
  2010 Visa                        (1,000)
                        Net worth  15,000

3000 BUDGET EQUITY                         available
  3010 Unassigned (system)                     1,500
  3100 Envelopes
    3110 Groceries   ↔ 5110                      400
    3120 Rent        ↔ 5120                    2,000
    3130 Dining out  ↔ 5130                      100
  3500 Goals
    3510 Emergency fund                       10,000
    3520 New car                               3,000
  3900 Expected income (debit)
    3910 Salary due  ↔ 4010                   (2,000)

4000 INCOME
  4010 Salary
5000 EXPENSES
  5110 Groceries
  5120 Rent
  5130 Dining out
```

Check: net worth 15,000 + salary still due 2,000 = 17,000 = Unassigned 1,500 + envelopes 2,500 + goals 13,000.

## The six events
| Event | Entry |
|---|---|
| Opening balance | Dr Bank / Cr Unassigned |
| Plan income | Dr Expected income / Cr Unassigned |
| Receive income | Dr Bank / Cr Income. Income clears against Expected income, or against Unassigned if future income is off |
| Assign / move / cover | Dr Unassigned (or Envelope A) / Cr Envelope or Goal |
| Spend | Dr Expense / Cr Bank. Expense draws down its paired Envelope |
| Spend from a goal | Dr Goal / Cr Bank (same as today) |

Resulting invariant, which the trial balance enforces for free:
`Assets − Liabilities + Expected income = Unassigned + Envelopes + Goals`

## Key decisions
1. **How income and expense reach their buckets.** Recommended: no physical closing entries. Each Income/Expense account is *paired* with its Expected-income/Envelope account, and a bucket's available balance = bucket balance ± its paired account's activity. This keeps the income statement intact.
2. **Overspending.** In pure double-entry, an overspent envelope just goes negative and Unassigned doesn't move. The current v3 rule takes overspending out of Unassigned immediately. That would become a presentation rule: displayed Unassigned = Unassigned − Σ negative envelopes. The alternative is an automatic month-end cover entry.
3. **Entry granularity.** One budget entry per month with one line per category, edited in place. This mirrors today's `Budget` rows, so there is no per-keystroke history noise; the audit log already covers edits.
4. **Reporting.** Budget entries are equity-to-equity, so they never touch the income statement. The balance sheet's equity section *becomes* the Dollar Map.

## Requirements (agreed)
1. **Auto-paired buckets.** Creating an Expense account creates its Envelope, and creating an Income account creates its Expected-income account. Rename, archive, restore and delete follow the pair. A bucket has no form of its own.
2. **Never shown as a category.** Unassigned, Envelope and Expected-income accounts are left out of every categorization picker:
   - Bank Feed, categorize mode, CSV map, split legs and the Transactions edit modal.
   - Filtered in both shared helpers: `picker_accounts_data()` (`apps/budget/services.py`) on the server and `pickableAccounts` (`common/accountKind.js`) on the client.
3. **Ledger guard: budget-only accounts stay in budget entries.**
   - New `JournalEntry.SOURCE_BUDGET`.
   - Unassigned, Envelope and Expected income may appear only in `SOURCE_BUDGET` entries, and those entries may hold only budget accounts plus Goals.
   - Goals are the one dual account: `Dr Goal / Cr Bank` is real goal spending, `Dr Unassigned / Cr Goal` is a budget move.
   - Enforced in two layers:
     - the model, in `JournalLine.save()` / entry validation, so every path (API, import, admin) is covered;
     - `apps/accounts/guards.py::assert_category_allowed`, so the user sees a readable refusal.
   - This blocks `Dr Bank / Cr Envelope` by construction.

## What gets simpler / harder
- **Simpler:** Unassigned, rollover and goal "left" become balances, not formulas. Splits, transfers and reconciliation need no budget logic. Export and import carry it automatically.
- **Harder:** every "doesn't count" filter (`counted_entries`) must also exclude budget entries wherever real cash flow is meant (reports, Transactions page, bank feed). The "account type" checks in pickers and reports must learn the new types.

## Migration (mechanical)
- `Budget` rows → monthly budget entries.
- `GoalAllocation` rows → Unassigned→Goal entries.
- Opening-balance equity → Unassigned.
- Verify with the existing `compute_unassigned()`: it must equal the new Unassigned balance (after the overspend rule) for every month, then retire it.

## Verification (when built)
- Per book, per month: old `compute_unassigned()` == new balance-derived Unassigned.
- Trial balance holds.
- The `apps/budget/test_unassigned.py` matrix passes unchanged.
