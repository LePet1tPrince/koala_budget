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
| **Goal bucket** | goal | credit | Money saved for the goal |
| **Expected income** | income category | debit | Income budgeted but not yet received (only when "budget future income" is on) |

All four are one stored account type, `budget`, with a `paired_account` link to the category they budget for (an expense, an income account, or a goal's own account); Unassigned is the one paired with nothing. The role is derived from the pair.

**Goals work like expenses.** A goal's own account ("Goal: Car") stays the category that spending from the goal is categorized to; its paired goal bucket holds what was saved. Left in the goal = bucket − spending, exactly like an envelope's available.

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
| Assign / move / cover | Dr Unassigned (or Envelope A) / Cr Envelope or Goal bucket |
| Spend | Dr Expense / Cr Bank. Expense draws down its paired Envelope |
| Spend from a goal | Dr Goal: Car / Cr Bank (same as today). The goal account draws down its paired Goal bucket |

Resulting invariant, which the trial balance enforces for free:
`Assets − Liabilities + Expected income = Unassigned + Envelopes + Goals`

## Key decisions
1. **How income and expense reach their buckets.** Recommended: no physical closing entries. Each Income/Expense account is *paired* with its Expected-income/Envelope account, and a bucket's available balance = bucket balance ± its paired account's activity. This keeps the income statement intact.
2. **Overspending.** In pure double-entry, an overspent envelope just goes negative and Unassigned doesn't move. The current v3 rule takes overspending out of Unassigned immediately. That would become a presentation rule: displayed Unassigned = Unassigned − Σ negative envelopes. The alternative is an automatic month-end cover entry.
3. **Entry granularity.** One budget entry per month with one line per category, edited in place. This mirrors today's `Budget` rows, so there is no per-keystroke history noise; the audit log already covers edits.
4. **Reporting.** Budget entries are equity-to-equity, so they never touch the income statement. The balance sheet's equity section *becomes* the Dollar Map.

## Requirements (agreed)
1. **Auto-paired buckets.** Creating an Expense account creates its Envelope, creating an Income account creates its Expected-income account, and creating a goal creates its Goal bucket. Rename, archive, restore and delete follow the pair. A bucket has no form of its own.
2. **Never shown as a category.** Every budget bucket is left out of every categorization picker:
   - Bank Feed, categorize mode, CSV map, split legs and the Transactions edit modal.
   - Filtered in both shared helpers: `picker_accounts_data()` (`apps/budget/services.py`) on the server and `pickableAccounts` (`common/accountKind.js`) on the client.
3. **Ledger guard: budget-only accounts stay in budget entries.**
   - New `JournalEntry.SOURCE_BUDGET`.
   - Budget buckets may appear only in `SOURCE_BUDGET` entries, and those entries may hold only budget buckets.
   - No exception for goals: their buckets are budget-only and their accounts are ordinary categories (`Dr Goal: Car / Cr Bank` is real goal spending, `Dr Unassigned / Cr Goal bucket` is a budget move).
   - Enforced in two layers:
     - the model, in `JournalLine.save()` / entry validation, so every path (API, import, admin) is covered;
     - `apps/accounts/guards.py::assert_category_allowed`, so the user sees a readable refusal.
   - This blocks `Dr Bank / Cr Envelope` by construction.

## What gets simpler / harder
- **Simpler:** Unassigned, rollover and goal "left" become balances, not formulas. Splits, transfers and reconciliation need no budget logic. Export and import carry it automatically.
- **Harder:** every "doesn't count" filter (`counted_entries`) must also exclude budget entries wherever real cash flow is meant (reports, Transactions page, bank feed). The "account type" checks in pickers and reports must learn the new types.

## Migration (mechanical)
- `Budget` rows → monthly budget entries.
- `GoalAllocation` rows → Unassigned→Goal bucket entries.
- Opening-balance equity → Unassigned.
- Verify with the existing `compute_unassigned()`: it must equal the new Unassigned balance (after the overspend rule) for every month, then retire it.

## Verification (when built)
- Per book, per month: old `compute_unassigned()` == new balance-derived Unassigned.
- Trial balance holds.
- The `apps/budget/test_unassigned.py` matrix passes unchanged.

## Phases
Each phase is its own branch off the `budget-ledger` integration branch (itself cut from `develop`, which stays untouched as the fallback).

1. **Budget accounts + ledger guard** (`budget-ledger-phase-1-accounts`): the `budget` type, `Account.paired_account`, Unassigned and a bucket per income/expense/goal account (`apps/budget/buckets.py`, backfilled by `budget.0009`), buckets hidden from every picker and page, and `assert_budget_entry_rules` on every line write. No budget numbers change.
2. **Budget entries** (`budget-ledger-phase-2-entries`): `apps/budget/ledger.py` mirrors each month's `Budget` and `GoalAllocation` rows into one `SOURCE_BUDGET` entry (dated the 1st; one line per bucket plus a balancing Unassigned line; unique per book and month). The rows stay the source of truth; the entry is rebuilt from them on every write (signals for single saves, explicit `sync_month`/`sync_book` for bulk paths and deletes, backfilled by `budget.0010`). `ledger_unassigned` reads Unassigned off the bucket balances, and `check_book` / `manage.py budget_ledger_check` prove it equals `compute_unassigned` for every month — including the real YNAB sample book. Budget entries are kept out of everything that means "transactions" via `transaction_entries()`.
3. **Switch over:** budget page, goals, Dollar Map and balance sheet read balances; old tables and `compute_unassigned()` retired; Reconciliation Adjustments merged into Unassigned.
4. **Portability:** buckets and budget entries in the export format, older archives still import.
