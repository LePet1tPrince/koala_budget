# Koala Budget — Design Document

This document is the living record of all UI/UX decisions made in the project. Agents must read this before making any UI or design decision, and append new decisions here after each feature.

---

## Color System

Koala Budget uses **DaisyUI 5** semantic color tokens on top of Tailwind CSS 4. Do not use raw Tailwind color utilities (e.g. `bg-blue-500`) in UI components — always use DaisyUI semantic tokens so theming works correctly.

| Token | Usage |
|-------|-------|
| `primary` | Main CTAs, active nav items, key interactive elements |
| `secondary` | Supporting actions, secondary buttons |
| `accent` | Highlights, badges, progress indicators |
| `neutral` | Cards, panels, secondary backgrounds |
| `base-100/200/300` | Page background layers |
| `success` | Positive amounts, completed goals, passing states |
| `warning` | Budget at-risk, approaching limits |
| `error` | Negative balances, failed states, destructive actions |
| `info` | Tooltips, informational banners |

**Financial amounts:**
- Positive balance / income: `text-success`
- Negative balance / expense: `text-error`
- Zero / neutral: `text-base-content`

---

## Typography

- Font stack: system UI fonts (Tailwind default)
- Headings: DaisyUI `.text-xl` / `.text-2xl` with `font-semibold`
- Body: `text-base` (16px)
- Small labels: `text-sm text-base-content/70`
- Monospace (amounts, account numbers): `font-mono`

---

## Component Patterns

### Tables
- Use Material-Table (Material UI) for data-heavy views (accounts, transactions, journal entries)
- Always include: sort, filter, and a row-level action menu
- Empty state: centered text with a CTA button to create the first item

### Forms
- Use DaisyUI `form-control`, `label`, `input`, `select`, `textarea` classes
- Inline validation with `text-error` below the field
- Submit buttons: `btn btn-primary`
- Cancel/back: `btn btn-ghost`

### Modals
- DaisyUI `modal` component
- Always trap focus and close on backdrop click
- Destructive confirmations use `btn btn-error` confirm button

### Cards
- DaisyUI `card card-bordered` for data panels
- `card-title` with optional icon prefix
- Actions in `card-actions justify-end`

### Navigation
- Top nav for global actions (team switcher, user menu)
- Left sidebar for section navigation (accounts, budget, reports, etc.)
- Active nav item: `menu-active` DaisyUI class

### Badges / Status Indicators
- Goal progress: DaisyUI `progress` bar with `accent` color
- Transaction status: `badge badge-success` / `badge badge-warning` / `badge badge-error`

---

## Layout and Spacing

- Page content max-width: `max-w-7xl mx-auto`
- Standard section padding: `p-6` (desktop) / `p-4` (mobile)
- Card gap in grids: `gap-4` (compact) / `gap-6` (spacious)
- Form field spacing: `space-y-4`
- Table row height: default Material-Table (dense mode for transaction lists)
- Responsive breakpoints: Tailwind defaults (sm: 640px, md: 768px, lg: 1024px, xl: 1280px)

---

## User Flows

### Transaction Categorization
1. Uncategorized transactions appear in the Bank Feed inbox
2. User selects account + payee → creates JournalEntry
3. Categorized transaction disappears from inbox
4. AI auto-suggest is available; user confirms or overrides

### Budget Entry
1. User navigates to Budget for current month
2. Each expense account row shows allocated vs. spent
3. Click cell to enter budget amount inline
4. Over-budget rows highlighted with `warning` color

### Goal Savings
1. User creates a Goal with target amount and target date
2. System auto-creates an equity account in 3000s range
3. Monthly allocations tracked via GoalAllocation
4. Progress bar shown on goal card

### Plaid Connection
1. User clicks "Connect Bank" → Plaid Link modal
2. On success, PlaidItem + PlaidAccounts created
3. Initial sync runs; transactions appear in inbox
4. Incremental sync runs on subsequent visits

---

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| Project start | DaisyUI semantic tokens only — no raw Tailwind colors | Enables theming, consistent palette |
| Project start | Material-Table for data grids | Built-in sort/filter/pagination, mature library |
| Project start | Positive amounts = outflow (Plaid convention) | Matches Plaid API; consistent throughout |
| Project start | Team-level multi-tenancy with role-based access | SaaS model; supports shared household budgets |
| Project start | Double-entry bookkeeping | Financial integrity; enables full reporting |
| 2026-06-04 | Accounts filter state passed as `return_type` query param on outbound links; no client-side storage | Stateless, bookmarkable, no JS dependency |
| 2026-06-04 | Hidden `<input type="hidden" name="return_type">` in account edit form to survive POST redirect | Preserves filter through form submission without URL manipulation in the view |
| 2026-06-04 | Invalid/unrecognized `return_type` values are passed through; the account list view silently ignores them | Avoids 400 errors on stale/external links; degrades gracefully to unfiltered list |
