# Koala Budget — Style Audit & Layout Redesign Proposal

**Date:** 2026-06-12
**Goal:** Make Koala Budget feel like Wealthsimple — simple, minimalist, calm, and intuitive. Money apps earn trust through restraint: few colors, generous whitespace, one clear number per screen, and zero visual noise.

This document has three parts:

1. **Part 1 — Current styling, documented** (what we have today, with file references)
2. **Part 2 — Wealthsimple-inspired design direction** (the target visual language)
3. **Part 3 — Layout & information-architecture redesign ideas** (making the app intuitive)

---

## Part 1 — Current Styling Inventory

### 1.1 Foundation

| Layer | What we use | Where |
|---|---|---|
| CSS framework | Tailwind CSS 4.1 + DaisyUI 5.5 | `tailwind.config.js`, `assets/styles/site-tailwind.css` |
| Theme | DaisyUI **built-in** `light` / `dark` themes — no custom theme | `koala_budget/settings.py`, `templates/web/base.html:5` |
| Dark mode | Class + `data-theme` attribute, localStorage sync, cookie to avoid flicker | `templates/web/base.html:70-106` |
| Legacy layer | Pegasus `pg-*` component classes wrapping DaisyUI | `assets/styles/pegasus/tailwind.css` (203 lines) |
| App CSS | profile, progress, subscriptions, utilities | `assets/styles/app/` |
| Build | Vite 7 → `/static/css/`, django-vite manifest | `vite.config.ts` |

### 1.2 Typography

- **Django templates (the whole app):** no web font is loaded — falls back to Tailwind's default system stack.
- **Frontend SPA (auth flows only):** declares `Inter, system-ui, Avenir, Helvetica, Arial` in `frontend/src/index.css:17-23`. So login/signup renders in a different font than the app itself.
- Amounts use `font-mono` inconsistently — budget table and net-worth card yes (`templates/budget/components/net_worth_card.html:22`), account list and report cards no.
- Heading scale is ad hoc: `pg-title` (text-3xl bold), `pg-subtitle` (text-xl), raw `text-3xl font-bold` (`templates/budget/budget_home.html:38`), `card-title text-lg` — four competing conventions.

### 1.3 Color usage

Roughly **70% semantic** (DaisyUI tokens), **30% hardcoded** — despite `docs/design-document.md` mandating "DaisyUI semantic tokens only, no raw Tailwind colors."

Violations worth fixing:

| Pattern | Examples |
|---|---|
| Hardcoded grays in templates | `text-gray-600` in `templates/accounts/accounts_home.html:12,24,45,66,87`, `templates/reports/reports_home.html:7,17,33,49,69`; `text-gray-500` empty state in `templates/accounts/account_list.html:56` |
| Hardcoded status-badge palettes in React | `bg-blue-100 text-blue-700`, `bg-purple-100`, `bg-yellow-100`… in `assets/javascript/transactions/TransactionsTable.jsx:22-30` and `bank_feed/react/LineTableMaterial.jsx:294-311` |
| Hardcoded link & button colors in Pegasus layer | `.pg-link` = `text-blue-500 hover:text-blue-800`, `.pg-button-danger` = raw red-500/700, `.pg-breadcrumb-active` = `#7a7a7a` (`assets/styles/pegasus/tailwind.css:12,74,178`) |
| One-off HSL/hex values | `.muted-link` `hsl(0,0%,71%)` (`assets/styles/app/utilities.css:16`), `.edit-guidance` `#888` |

### 1.4 Three design systems at once (the biggest problem)

1. **DaisyUI** — server-rendered templates (budget, accounts, reports, goals).
2. **Pegasus `pg-*` classes** — a second vocabulary for the same things (`pg-button-primary` ≡ `btn btn-primary`, `pg-card` ≡ `card`, `pg-table` ≡ `table`).
3. **Material UI 7 + @material-table/core** — the entire Bank Feed and Transactions experience (`assets/javascript/bank_feed/react/LineTableMaterial.jsx`, `transactions/TransactionsTable.jsx`) renders with MUI's own theme (`createTheme`/`ThemeProvider`), its own buttons, snackbars, toolbars, and icons.

The two screens users live in the most — Bank Feed and Transactions — look like a different product than the rest of the app, and MUI adds significant bundle weight.

**Icons are similarly tripled:** Font Awesome 6 via CDN (`templates/web/base.html:43-44`), inline Heroicons SVGs (`templates/budget/components/net_worth_card.html`), and `@mui/icons-material` in React.

### 1.5 Pegasus boilerplate still shipping

- The logged-in home (`templates/web/app_home.html`) is the stock Pegasus "You're Signed In!" page with a rocket illustration — **there is no dashboard**, yet "Dashboard" is a nav item.
- Top nav shows an "Examples Gallery" link to every authenticated user (`templates/web/components/top_nav.html:31-34`).
- `templates/pegasus/` and `templates/teams_example/` demo templates are still present.
- Breadcrumbs are inconsistent and low-value: lowercase "accounts" (`templates/accounts/accounts_home.html:6`), "accounts Overview" heading (line 11).

### 1.6 Layout patterns today

- **Shell:** top navbar (`navbar shadow-md`) + 256px left sidebar (hidden below `lg`, replaced by a hamburger dropdown that mixes site links with app links) + content. `templates/web/app/app_base.html`.
- **Nav order** (`templates/web/components/app_nav_menu_items.html`): *Set Up → Bank Feed → Transactions → Budget → Reports → Dashboard → team links → AI Chat → My Account → Admin*. "Set Up" is actually the chart of accounts; "Dashboard" is the boilerplate page; the home icon appears twice (Set Up + Dashboard) and `fa-book` twice (Bank Feed + Budget).
- **Cards-in-cards:** pages wrap an `app-card` (white card with shadow) around more `card bg-base-200 shadow-md` cards around `stat` blocks — three levels of boxes with three shadow weights (`templates/accounts/accounts_home.html`).
- **Hub-page pattern:** Accounts home and Reports home are grids of cards where every card has *two* buttons ("View All" + "New X") — six to eight competing CTAs per screen.
- **Good recent work to build on:** the net-worth card (`templates/budget/components/net_worth_card.html`) is the closest thing to the target aesthetic — one big number, muted labels, semantic colors. Loading skeletons on React mounts are also already in place.

---

## Part 2 — Design Direction: "Calm Money"

Wealthsimple's visual language, translated to our stack:

### 2.1 Principles

1. **One number per screen.** Every page leads with the single figure the user came for (net worth, left to spend, uncategorized count). Everything else is secondary.
2. **Color means something.** Near-monochrome UI; green/red appear *only* on amounts and statuses. If everything is colorful, nothing is.
3. **Whitespace instead of boxes.** Separate content with spacing and hairline dividers, not nested shadowed cards.
4. **Plain words.** "Set Up" → "Accounts". "Journal Entry" → "Transaction". No accounting jargon in the UI (keep it in the data model).
5. **Progressive disclosure.** Show the simple path; tuck power features (account groups, institutions, debug views) behind a settings area.

### 2.2 Proposed theme tokens (custom DaisyUI theme)

Define a custom theme in `assets/styles/site-tailwind.css` (DaisyUI 5 supports CSS-based themes) instead of stock `light`/`dark`:

```css
@plugin "daisyui" {
  themes: koala --default, koala-dark --prefersdark;
}

@plugin "daisyui/theme" {
  name: "koala";
  color-scheme: light;
  --color-base-100: oklch(99% 0.004 95);   /* warm off-white, not pure white */
  --color-base-200: oklch(96.5% 0.006 95); /* cream — page background */
  --color-base-300: oklch(92% 0.008 95);   /* hairline borders */
  --color-base-content: oklch(24% 0.01 95);/* warm near-black */
  --color-primary: oklch(30% 0.02 95);     /* ink — primary buttons are dark, not blue */
  --color-primary-content: oklch(98% 0.004 95);
  --color-accent: oklch(72% 0.11 80);      /* muted gold — used sparingly */
  --color-success: oklch(52% 0.13 155);    /* deep green for positive amounts */
  --color-error: oklch(55% 0.18 25);       /* restrained red */
  --radius-box: 1rem;                      /* soft rounded cards */
  --radius-field: 0.75rem;
  --radius-selector: 9999px;               /* pill buttons/badges */
  --border: 1px;
}
```

(Exact values to be tuned in review; intent: cream background, ink-colored primary buttons, gold accent, pill controls.)

### 2.3 Typography

- Load **Inter** (self-hosted, variable) in `templates/web/base.html` so the app and SPA match; set `font-feature-settings: "tnum"` (tabular numerals) on amount elements instead of `font-mono` — aligned digits without the typewriter look.
- Fixed scale, three levels only:
  - **Display number:** `text-4xl font-semibold tracking-tight` — the hero figure
  - **Page title:** `text-2xl font-semibold`
  - **Label/meta:** `text-sm text-base-content/60`
- Delete `pg-title`/`pg-subtitle` in favor of these.

### 2.4 Component rules

| Component | Rule |
|---|---|
| Cards | One level deep, `bg-base-100 rounded-2xl border border-base-300` — **no shadows** except overlays (modals, dropdowns) |
| Buttons | One primary (ink) button per view; everything else `btn-ghost` or a text link; pill shape |
| Tables | Remove `table-zebra`; hairline row dividers, generous row padding, right-aligned tabular-num amounts |
| Badges | DaisyUI `badge-soft badge-{success,warning,error,neutral}` — replaces the hardcoded `bg-*-100 text-*-700` pairs in React |
| Icons | Single set (Heroicons outline, inline or via a tiny include) — drop Font Awesome CDN and `@mui/icons-material` |
| Empty states | Illustration-free: short sentence + one primary action |
| Forms | DaisyUI fields, labels above, single column, max-w-md |

### 2.5 Consolidation plan (ordered, incremental)

1. **Custom theme + Inter** — pure CSS, instantly reskins every DaisyUI surface. Lowest effort, highest visible impact.
2. **Purge Pegasus:** delete "Examples Gallery" nav link, `templates/pegasus/`, `teams_example/`; migrate `pg-*` usages to DaisyUI equivalents and delete `assets/styles/pegasus/tailwind.css`.
3. **Fix design-doc violations:** replace all `text-gray-*` with `text-base-content/{60,70}`; replace hardcoded badge palettes with semantic badges.
4. **Migrate Bank Feed + Transactions off MUI** to a Tailwind/DaisyUI table (TanStack Table is headless and pairs well, or plain markup — we already paginate server-side). Removes `@mui/material`, `@mui/icons-material`, `@material-table/core` from the bundle and unifies the look. This is the largest item; do it last, screen by screen.
5. **One icon set**, removing the Font Awesome CDN dependency (also a performance/privacy win).

---

## Part 3 — Layout & IA Redesign Ideas

### 3.1 A real Home page (replaces the rocket)

`web:home` → team dashboard answering "how am I doing, and what needs me?" in five seconds:

```
┌──────────────────────────────────────────────────┐
│  Net worth                                       │
│  $128,431.22            ▁▂▂▃▃▄▅▅ (12-mo spark)   │
│  +$2,140 this month                              │
├──────────────────────────────────────────────────┤
│  ⚠ 14 transactions to review        [Review →]   │  ← only when nonzero
├────────────────────────┬─────────────────────────┤
│  June budget           │  Goals                  │
│  $1,240 left to spend  │  Vacation  ▓▓▓▓░░ 64%   │
│  ▓▓▓▓▓▓▓░░░            │  Emergency ▓▓▓▓▓░ 88%   │
├────────────────────────┴─────────────────────────┤
│  Recent activity (5 rows)         [See all →]    │
└──────────────────────────────────────────────────┘
```

Everything already exists: net worth + available from the budget context, uncategorized count from bank feed, goal progress from `GoalQuerySet.with_progress()`. This is composition, not new features. New users instead see an **onboarding checklist** here (Connect a bank → Review transactions → Set a budget).

### 3.2 Navigation restructure

Current: `Set Up · Bank Feed · Transactions · Budget · Reports · Dashboard · Team · AI Chat · My Account`

Proposed:

| Item | Notes |
|---|---|
| **Home** | The new dashboard, first item |
| **Inbox** `(14)` | Renamed Bank Feed, with a live count badge of uncategorized transactions — the daily-driver task gets inbox-zero mechanics |
| **Transactions** | The clean, categorized history |
| **Budget** | Keep |
| **Goals** | Promote from a tab inside Budget to a top-level item — emotionally, goals are why people budget |
| **Reports** | Keep |
| **Settings** | Collapses: Accounts/Groups/Payees/Institutions (today's "Set Up"), team management, profile, password, subscription |

Rules: unique icon per item, one icon set, `AI Chat` becomes a floating affordance or stays last — it shouldn't sit between account settings and sign-out. "My Account" links move under Settings; sign-out goes in a top-right avatar menu.

### 3.3 Page-level layout fixes

- **Standard page header everywhere:** title left, single primary action right, no breadcrumbs (the app is one level deep — breadcrumbs that read "accounts" add noise, not orientation). Delete `pg-breadcrumbs`.
- **Hub pages → lists:** Accounts home's 4-card grid (8 buttons) becomes a single grouped list — accounts grouped by type with balances, one "New account" button, whole rows clickable. Payees/Institutions/Groups become tabs or settings sub-pages.
- **Reports home:** three near-identical cards each shouting `btn-primary` → a simple list of report links with one-line descriptions; the CSV export is a quiet secondary row.
- **Budget page:** keep the table+sidebar split, but flatten card nesting and let the net-worth "Available" figure become the page hero. Over-budget rows: a thin warning underline on the amount, not a colored row.
- **Bank Feed:** lead with "N to review"; account cards collapse into a slim filter row; bulk-categorize stays sticky at the bottom.

### 3.4 Mobile

The sidebar disappears below `lg` into a hamburger that mixes marketing-site links with app links (`top_nav_app.html` extends the site nav). Replace with a **bottom tab bar** (DaisyUI `dock`): Home · Inbox · Budget · More. Inbox-style categorization is a phone task; today it's the weakest screen on mobile because of the MUI table.

### 3.5 Suggested sequencing

| Phase | Scope | Effort |
|---|---|---|
| 1 | Custom theme, Inter, kill Examples Gallery + breadcrumbs, fix gray/hardcoded colors | Small |
| 2 | Real Home dashboard + nav restructure (rename, reorder, Settings group, Inbox badge) | Medium |
| 3 | Hub pages → lists; standard page headers; Goals promoted | Medium |
| 4 | Bank Feed/Transactions off MUI; mobile dock | Large |

Each phase ships independently and is testable with the existing Playwright POM suite (nav and page-header changes will require page-object updates in `e2e/pages/`).
