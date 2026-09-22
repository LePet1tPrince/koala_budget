# Koala Budget — Feature Priority Report

**Author:** Product Owner
**Date:** 2026-09-21
**Branch surveyed:** `claude/koala-feature-priority-report-f79194` (at `cfbb6c6`, 205 merged PRs)

---

## How to read this

Every item below was verified against the code, not against a plan document. Where a
plan claims something is missing that has since shipped, I say so; where a plan claims
something shipped that is a stub, I say that too. File references are the evidence —
check them before disagreeing with a priority.

**Effort** is dev-days for one senior full-stack engineer already fluent in this
codebase, including tests and a docs/CLAUDE.md update, because that is what every
shipped feature here has cost. It is calibrated against real work in this repo:

| Reference feature | Actual scope | Calibration |
|---|---|---|
| Transfer-leg link (#203) | one button, no API change | ~1–2 days = **S** |
| Settings consolidation (#202) | one shell, 6 pages re-parented | ~2–3 days = **S/M** |
| Transactions column filters (#191→) | new filter module + tree UI | ~5–7 days = **M** |
| Monthly review | new app, 2,955 py lines + React | ~12–15 days = **L** |
| Onboarding walkthrough | new app, 8 steps, E2E suite | ~15–20 days = **L/XL** |
| YNAB import | new app, 6 screens, reconciler | ~15–20 days = **XL** |

**Complexity** is risk, not size: how likely the estimate is wrong, and how much
damage a bug does. A Low-complexity 8-day item is safer than a High-complexity 4-day
one.

---

## 1. Who we are building for

From `docs/marketing-plan.md`, corroborated by what the product actually optimises for:

> **"The budgeting app for Canadians who actually want their numbers to be right."**

The ICP is **budget-savvy Canadian individuals and households** — specifically the
spreadsheet-and-footnotes segment: engineers, accountants, finance-adjacent people, and
the "I budget in Google Sheets and I've outgrown it" crowd. They are:

- **Migrating, not starting.** They come from YNAB (price increases, Canadian bank
  support), Mint (dead), Monarch, or Sheets. They arrive with history and expect it to
  survive the move.
- **Numerate and suspicious.** They will notice a double-counted credit-card payment.
  The whole positioning is that we notice it first.
- **Canadian.** CAD pricing, Canadian banks, spotty Plaid coverage, RRSP/TFSA/USD
  accounts, a February–April tax-season attention spike.
- **Household-shaped.** Budgeting with a partner is the norm, which is why Teams is
  a first-class concept and also the referral loop.

Two consequences for prioritisation that I will keep returning to:

1. **The migration path is the acquisition path.** YNAB refugee-hunting is the primary
   channel for users 1–100. Anything that breaks a migrant in week one is not a
   nice-to-have; it is a leak in the top channel.
2. **"Right" is the promise.** We sell a reconciliation guarantee. Anything that lets
   the numbers go quietly stale or wrong costs more than a missing feature would.

---

## 2. Where the product actually stands

Stronger than the plan docs suggest. `docs/saas-gaps-plan.md` is materially out of date —
several of its open items have shipped since it was written.

**Shipped and genuinely good** (this is the moat; do not re-litigate it):

- Double-entry ledger with void handling, audit trail (row-level diffs + operation
  events), and correct exclusion of voided entries from every balance and report.
- Transfer duplicate detection *and* mirror legs — the marquee differentiator, fully
  transversable, with a reconciled-leg guard. Now links leg-to-leg across feeds (#203).
- Bank feed with categorize mode: history-based category suggestions across three
  match tiers, keyboard-drivable search, inline account creation, batch-categorize of
  lookalikes, and in-place payee/description editing (#201).
- Six reports plus a **guided monthly review** (`apps/monthly_review/`, 2,955 py lines —
  shipped, not a proposal, contrary to the plan doc's "no code written yet" header).
- Budget: single-month table with in-place autosave, multi-month Excel-paste grid,
  rollover-correct `available`.
- Goals with allocations, withdrawals, and progress reporting.
- **Onboarding walkthrough** — questionnaire → generated chart of accounts → review →
  guided task rail → opening balances → finish card, with funnel instrumentation and a
  17-test E2E suite.
- **YNAB import** — two CSVs in, whole budget out, with a reconciler that verifies
  2,394 category-months and 36 account balances before writing anything.
- Design system consolidated: custom daisyUI theme, one icon set, **zero MUI**, zero
  Pegasus CSS. Bank-feed bundle down 91%.
- Rate limiting, CSV exports, ToS/Privacy, GDPR download + account deletion, settings
  hub (#202).
- 1,051 backend tests across 72 test modules; 10 E2E suites.

**Stale entries in `CLAUDE.md` Known Issues** — worth correcting so they stop
consuming attention: `STRICT_TEAM_CONTEXT` is now `True` (`settings.py:681`), and
`ONBOARDING_ENABLED` is on (`settings.py:675`).

**The real gaps** are clustered in three places, and they are not where the plan docs
look. In order of how much they cost us:

1. **Everything after the ledger is trusted.** No email, no notifications, no alerts.
   The app cannot tell a user anything unless they log in and look.
2. **Manual control of the ledger.** You can import a split transaction; you cannot
   create or edit one. You cannot record a cash purchase at all. The Transactions page
   is read-only.
3. **The trust prerequisites for taking bank credentials.** Plaid tokens are plaintext,
   webhooks are unverified, and an expired connection fails silently.

---

## 3. Priority rubric

| Tier | Meaning | Window |
|---|---|---|
| **P0** | Blocks charging money, blocks trust with bank data, or the app contradicts its own marketing | Before the founding-member push |
| **P1** | The core loop holds but users hit a wall or churn quietly | Before scaling past ~100 users |
| **P2** | Differentiation, retention depth, growth loops | Months 4–8 |
| **P3** | Deferred — real value, wrong time, or needs a decision first | Watch list |

---

## 4. P0 — Before you take money or bank credentials

Seven items, **~22–33 dev-days**. Nothing here is a feature a user would praise; all of
it is the cost of being allowed to charge.

### P0.1 — Encrypt `PlaidItem.access_token`
**Effort: S · 1–2 days · Complexity: Low**

Plaintext today, with the fix already written and commented out:

```python
# apps/plaid/models.py:19-20
access_token = models.CharField(max_length=512, help_text="Access token for Plaid API")
# access_token = EncryptedCharField(max_length=512, help_text="Access token for Plaid API")
```

A long-lived credential to a stranger's bank, sitting in a column any DB backup copies.
The only real work is key management (env var, rotation story) and a data migration for
existing rows.

**Why P0:** the marketing plan names this as a trust prerequisite, and budget-savvy
Canadians *will* ask. It is also the cheapest item in this report.

---

### P0.2 — Verify Plaid webhook signatures
**Effort: S · 1–2 days · Complexity: Low**

The view documents its own gap (`apps/plaid/views.py:263-274`): unauthenticated, any
caller can trigger a sync for any known `item_id`. Blast radius today is genuinely small
(an extra sync), which is why it is not P0.1 — but it is an unauthenticated write path
into Celery, and JWT verification is a documented, bounded Plaid procedure.

**Dependency:** none. Ship alongside P0.1 as one "Plaid hardening" PR.

---

### P0.3 — Plaid connection health and reconnection
**Effort: M · 4–6 days · Complexity: Medium**

Nothing in the codebase handles `ITEM_LOGIN_REQUIRED` or any other item error — grep
finds zero matches across `apps/plaid/`. When a bank connection expires (routinely, every
few months, and *especially* at Canadian institutions), sync stops, no one is told, and
the feed silently goes stale.

Needs: item-error state on `PlaidItem`, Plaid Link *update mode* to re-authenticate,
a health indicator on the account cards, and an alert (see P0.4).

**Why P0:** this is the single worst failure mode for a product selling a reconciliation
guarantee. A user whose numbers quietly stopped updating has been told our promise is
false, and told it by our own product.

**Also fix here (S, ~1 day):** "Link Bank Account" is currently buried in a dropdown
inside `LineTable.jsx:496`, which only renders *after* an account is selected — and the
prominent version in `LineApp.jsx:587` renders only when the team has **zero** feed
accounts. Since both onboarding and YNAB import create accounts, a real new user never
sees it. Connecting a second bank is effectively undiscoverable.

---

### P0.4 — Transactional email and alerts
**Effort: M/L · 6–9 days · Complexity: Medium**

There is no email layer at all. No `templates/emails/`, no `apps/users/emails.py`, no
Celery email tasks. `EMAIL_BACKEND` defaults to a dev console backend
(`settings.py:408`), Anymail is configured but not activated (`settings.py:413`), and
`DEFAULT_FROM_EMAIL` is a personal Gmail address (`settings.py:404`).

Minimum viable set:
- Welcome email on signup
- Plaid connection failure (pairs with P0.3 — this is the mechanism that makes it honest)
- Budget overspend alert
- Trial-ending and subscription renewal/failure warnings
- Email preference page and unsubscribe handling

**Why P0:** we are about to run a 60-day trial. Without email, a trial user who drifts
away in week two is never contacted again, and a failed payment is invisible. It is also
the precondition for every retention mechanic in P1 and P2.

**Complexity note:** the send infrastructure is routine; the *preference model and
unsubscribe* are where this overruns. Do those properly now — retrofitting consent onto
an existing send layer is worse.

---

### P0.5 — Wire the offer into Stripe
**Effort: S/M · 3–4 days · Complexity: Medium**

`docs/marketing-plan.md` promises a $59 CAD/yr founding-member price locked for life,
500 spots with a live counter, and a 60-day trial. The code has **no trial configuration
whatsoever** — grep for `TRIAL` in `settings.py` returns nothing — and no founding-member
price or counter.

Needs: Stripe price + product metadata, trial-days on checkout, a spots-remaining count
the landing page can read, and the "locked for life" grandfathering rule written down
somewhere enforceable.

**Why P0:** the landing page already makes these promises. Shipping copy we cannot honour
is the one marketing mistake that costs the founding cohort's goodwill permanently.

**Complexity note:** dj-stripe is in place and the subscription app is mature (1,650
lines), so this is configuration and one counter endpoint — but "locked for life"
needs a real decision about what happens at renewal, and that is a product call, not an
engineering one.

---

### P0.6 — Conversion pages: pricing, comparison, security
**Effort: M · 4–6 days · Complexity: Low**

`apps/web/urls.py` has exactly `home`, `terms`, `privacy`, `robots.txt` and error pages.
There is **no `/pricing` page**, and none of the three SEO comparison pages the marketing
plan calls for (`/vs/ynab`, `/vs/monarch`, `/mint-alternative-canada`). The landing page's
comparison table is an in-page anchor only.

Also here: replace the undraw placeholder illustrations
(`landing_section1.html:81`, `landing_section2.html:8`) with **real product screenshots** —
the Sankey diagram and the net-worth chart are the best visual assets we have and they are
currently hidden behind generic clip art.

**Why P0:** the KPI is ≥3% landing→signup. We are asking for that conversion with no
pricing page, no competitor comparison, and stock illustrations. The comparison pages are
also the only P0 item that compounds — written once, they recruit indefinitely.

**Complexity: Low** but calendar-heavy — most of the cost is copy and screenshots, which
is founder time, not engineering time. Sequence it in parallel with engineering work.

---

### P0.7 — Retire the Pegasus demo surface
**Effort: S/M · 2–4 days · Complexity: Medium**

Publicly mounted in `koala_budget/urls.py`: `/pegasus/` (examples), `/pegasus/employees/`,
and `example/` inside the team URLs. Worse, the **AI Chat link is prominent in the sidebar**
(`app_nav.html:36`, styled with a border to draw the eye) and the agents behind it are
`WEATHER`, `ADMIN` and `EMPLOYEES` — Pegasus demo tools (`apps/ai/agents.py:40-43`).
There is no finance agent. A user who clicks the highlighted "AI Chat" in a budgeting app
gets a weather bot.

The admin agent *is* correctly gated to superusers (`apps/chat/views.py:57`,
`apps/ai/permissions.py`) — credit where due — but it wires an LLM to an MCP Postgres
server, and that should not be reachable from a production deployment at all.

Recommended split: **gate or unmount the demo routes now (S)**, and **remove the AI Chat
nav link until P2.9 gives it something to do (XS)**. Full removal of the demo apps needs
untangling `apps/ai/tools/employees.py` and a Celery beat entry, plus a migration — that
is the 2–4 day version and can wait.

**Why P0:** it is a credibility problem on a product whose entire pitch is rigour, and a
production attack surface we get nothing for.

---

## 5. P1 — Before scaling past ~100 users

Seven items, **~35–50 dev-days**. The core loop works; these are the walls users hit.

### P1.1 — Split transactions in the UI ⭐ *highest-value single item in this report*
**Effort: M/L · 6–9 days · Complexity: Medium/High**

The API already supports multi-line entries with balance validation
(`apps/journal/serializers.py:105-120`). The **UI does not.** `EditTransactionModal.jsx`
has no split concept at all — grep for "split" returns nothing in all 372 lines. Neither
does categorize mode.

So: **the YNAB importer creates splits (83 groups on the sample export) that the user can
then never edit, and can never create again.** A Costco receipt across groceries and
household, a paycheck across gross/tax/net, a lump Amazon order — all impossible.

**Why this is the top P1:** it is the intersection of our primary acquisition channel
(YNAB migration) and our core daily loop (categorization). A migrant hits it in week one,
and the failure mode is "this app is less capable than the one I left" — the single most
expensive impression we can make. It is also the only item in this report where we *ship
data we cannot ourselves author*, which is an internal inconsistency a numerate user will
find and post about.

**Complexity note:** the accounting is already sound (n-line balanced entries); the risk
is all in the interaction design and in the ~6 places that assume two lines — the feed row
projection, transfer mirroring, `_get_sibling_line` (`serializers.py:249-253`, which
explicitly returns None for >2 lines), budget actuals, and the transactions table's
debit/credit subqueries. Audit that list before estimating firmly.

---

### P1.2 — Manual transaction entry, edit and delete
**Effort: M · 5–7 days · Complexity: Medium**

`apps/journal/urls.py` exposes one page view — `transactions_home` — and
`TransactionsTable.jsx` has no row actions whatsoever (no edit, no delete, no add).
The Transactions page is a **read-only** ledger with excellent filters.

Consequence: **cash spending cannot be recorded.** Neither can a correction to a
historical entry, a manual journal adjustment, or anything at an account without a bank
feed. The only way any transaction enters the ledger is a bank feed, a CSV, or the YNAB
importer.

**Why P1:** for a double-entry product aimed at accountants and spreadsheet people, "you
may not write to the ledger" is an odd limitation. Cash is a small share of spend for
this ICP, but "I can't fix a mistake" is a daily irritation and a support-ticket
generator.

**Dependency:** design this *with* P1.1 — one entry/edit surface that handles 2 lines and
n lines is far less work than two surfaces, and avoids shipping a splits UI that the
Transactions page cannot open.

---

### P1.3 — Statement reconciliation flow
**Effort: M/L · 6–9 days · Complexity: Medium**

`JournalLine.is_reconciled` exists and the bank feed can batch reconcile/unreconcile with
a reconciled balance shown in the header. What does **not** exist is a reconciliation
*session*: no model anywhere for a statement, closing balance, or statement date (checked
`apps/journal/models.py` and `apps/bank_feed/models.py` — `JournalEntry`, `JournalLine`,
`BankTransaction`, `TransferMatchDismissal`, and nothing else).

So the user can tick lines as reconciled, but the app never asks "your statement says
$4,182.19 as of Aug 31 — mine says $4,182.19, you're clear" or, better, "mine says
$4,169.44, here is the $12.75 difference."

**Why P1:** we sell a **reconciliation guarantee** — "if your accounts don't reconcile to
the penny in 30 days, full refund." Right now the product cannot tell the user whether
they reconcile. The guarantee is unfalsifiable in both directions, which is worse than
useless: it is a refund liability with no instrument to discharge it.

**Complexity note:** Medium, not High, because every ingredient exists —
`with_reconciled_balance()` in `apps/accounts/querysets.py`, the per-line flag, the batch
operations. This is mostly a model for the statement, a difference calculation, and a
focused screen.

---

### P1.4 — Auto-categorization rules
**Effort: M · 5–8 days · Complexity: Medium**

No rule model exists (grep: no `CategorizationRule`, no `class *Rule`). What exists is
much better than nothing — `apps/bank_feed/services/similar_transactions.py` is a genuinely
good three-tier matcher (payee / description / token-set Jaccard) feeding suggestions in
categorize mode — but a suggestion is a prompt, not a rule. The user still confirms every
transaction, forever.

Needs: a persistent rule (`match on payee/description/amount` → `set category, payee`),
applied on import, with a "created by rule" marker so it is auditable and reversible, and
a management screen. The matcher already solved the hard part (normalisation, noise
tokens); rules are the persistence layer over it.

**Why P1:** this is the difference between a 30-second monthly review and a 20-minute one.
Retention in budgeting apps is almost entirely a function of how cheap the recurring
chore is. YNAB and Monarch both have this; its absence is felt every single week.

---

### P1.5 — In-app notification centre
**Effort: M · 5–7 days · Complexity: Low/Medium**

No `Notification` model anywhere. Budget overspend, goal reached, uncategorized pile-up,
sync failure, transfer duplicate detected — all of these are computed *somewhere* in the
product already and none of them is ever surfaced unless you happen to open the right page.

**Why P1:** it is the in-app half of P0.4, shares the same event taxonomy, and costs
little once that exists. The `inbox_count` context processor and `AuditEvent` already
establish the patterns.

**Dependency:** P0.4 (share one event definition; do not build two).

---

### P1.6 — User preferences
**Effort: S/M · 3–5 days · Complexity: Low**

The settings shell shipped (#202) with Profile, Password, Team, Subscription, YNAB import
and Audit log — but there is **no preferences section**. No date format, no timezone
behaviour for financial dates, no notification opt-ins, no first-month-of-fiscal-year, no
default account.

`apps/web/settings_sections.py` is a single well-documented list, so adding the section is
genuinely an edit in one place. The work is the preference model and honouring the values
at render time.

**Why P1:** it is the natural home for P0.4's email opt-ins (which we need for CASL
compliance in Canada, not just politeness), and the settings hub currently looks
conspicuously empty of actual *settings*.

---

### P1.7 — Mobile experience pass
**Effort: M · 5–8 days · Complexity: Medium**

A mobile dock exists (`app_base.html`) and the restyle work was responsive-aware, but the
heavy surfaces are desktop-first by construction: the bank feed table (`table-fixed` with
fixed column widths), the multi-month budget grid, the frozen-pane income statement, and
the transactions table with its tree filter menus.

**Why P1 and not P0:** the ICP does its budgeting sitting down, and the monthly review is
a desk activity. But *checking* a balance, and *categorizing* a handful of transactions,
are phone activities — and categorize mode is the one surface genuinely suited to a thumb.

**Recommendation:** scope this as "audit and fix the three journeys that matter on a phone"
(dashboard glance, categorize mode, goal check), not "make everything responsive." The
budget grid should stay explicitly desktop-only with an honest message.

---

## 6. P2 — Differentiation and growth (months 4–8)

Ten items, **~55–80 dev-days**. Pick by channel, not by order.

| # | Feature | Effort | Days | Complexity | Why it earns its place |
|---|---|---|---|---|---|
| P2.1 | **Recurring / scheduled transactions** | M/L | 7–10 | Medium | `SOURCE_RECURRING` is an enum value and nothing else (`apps/journal/models.py:32`). Rent, salary, subscriptions — the predictable spine of a budget, currently retyped or waited for. Precondition for P2.2. |
| P2.2 | **Cash-flow forecast / runway** | M | 6–8 | Medium | "Will I make it to payday" is the question budget apps are actually opened for. We have the cash-flow *report* (backward) and none of the forecast (forward). **Depends on P2.1.** |
| P2.3 | **Investment / tracking accounts with market value** | L | 8–12 | High | No units, no market value, no currency — `Account` is name + group + institution (`apps/accounts/models.py:56-75`). For Canadians with RRSP/TFSA/brokerage, net worth is *the* headline number and ours is structurally incomplete. High complexity: valuation history, price updates, and unrealised-gain accounting that must not corrupt the income statement. |
| P2.4 | **Debt payoff planner** (avalanche/snowball) | M | 6–8 | Medium | Liabilities are fully modelled and utterly unplanned. Strong Canadian hook (HELOC, credit-card debt, student loans) and excellent content fuel — every payoff calculator post ranks forever. |
| P2.5 | **Finance-aware AI assistant** | M/L | 8–12 | Medium/High | Replaces the demo agents removed in P0.7 with real tools over the ledger: "why was August $680 over," "categorize these 40," "what changed in groceries." We already have pydantic-ai + LiteLLM plumbing and deterministic insight rules in `apps/monthly_review/services/insights.py` to ground it. Complexity is in scoping tools to one team and never letting the model write unaudited. |
| P2.6 | **Bank-specific CSV presets** (RBC/TD/Scotiabank/BMO/CIBC/Tangerine/EQ) | S/M | 3–5 | Low | The SEO plan is one post per bank; a preset is what makes each post convert instead of merely rank. The column-mapping wizard already does the hard work — this is stored mappings plus auto-detection. **Best effort-to-channel ratio in P2.** |
| P2.7 | **Receipt / attachment upload** | M | 5–7 | Medium | Nothing outside user avatars uses `FileField`. Tax-time need for the self-employed slice of the ICP. Complexity is storage config, validation, and the privacy/retention story on someone's receipts. |
| P2.8 | **PDF report export** | S/M | 3–5 | Low | Listed unchecked in `saas-gaps-plan.md`'s own success criteria. CSV exists for four reports; PDF is what people send to an accountant or a mortgage broker. |
| P2.9 | **Scheduled email reports / weekly summary** | S/M | 3–5 | Low | Cheap retention once P0.4 exists. Pairs naturally with the monthly review: email the summary, link to the walkthrough. **Depends on P0.4.** |
| P2.10 | **Referral loop** (give a month, get a month) | M | 5–7 | Medium | Marketing plan 5b attributes ~100 of the first 1,000 users to this. Budget apps spread inside households and Teams already models that. |
| P2.11 | **Help centre / accounting explainers** | M | 5–8 | Low | Double-entry is simultaneously our differentiator and our learning curve. "Why is my credit-card purchase positive" needs an answer that is not a support email. |

---

## 7. P3 — Deferred watch list

| # | Item | Effort | Why not now |
|---|---|---|---|
| P3.1 | **Multi-currency** | XL · 15–25 days · Very High | No currency field exists anywhere; `currency_tags.py` hardcodes `$`. Genuinely wanted by Canadians with USD accounts, and genuinely an architectural change touching every amount, every report, every aggregate, plus FX rate history and revaluation accounting. Do not start this until P0 and P1 are done — it can eat a quarter. Consider a scoped version: **display-only USD accounts excluded from CAD totals**, which is days not weeks, and buys most of the goodwill. |
| P3.2 | **Goals: choose one of three styles** | S · 1 day · Low | `goals_summit` / `goals_koala` / `goals_arcade` all ship today as a deliberate review mechanism. Someone needs to *decide*, then delete two templates and their JS branches. Pure debt with a product decision attached — it is cheap, it is just not urgent. |
| P3.3 | **PWA / offline** | M · 5–8 days · Medium | No manifest, no service worker. Revisit after P1.7 tells us whether phone usage is real. |
| P3.4 | **Granular household permissions** (read-only partner) | M · 5–7 days · Medium | Teams has admin/member. No one has asked for finer grain yet. |
| P3.5 | **Tax-time exports** (capital gains, T-slip summaries) | L · 8–12 days · High | Seasonally powerful (Feb–Apr is a Canadian traffic spike) but depends on P2.3 investments to be worth anything. Plan it for the *second* tax season. |
| P3.6 | **Public API productization** | S/M · 3–5 days · Low | `UserAPIKey` and a generated TS client already exist. A differentiator for exactly our nerdiest users — but a handful of them, and not until the core is settled. |
| P3.7 | **Raise coverage threshold above 50%** | M · ongoing · Low | `pyproject.toml:45`. 1,051 tests is respectable, but the threshold is not enforcing much. Raise it as a ratchet alongside feature work rather than as a project. |

---

## 8. Summary table

| Tier | # | Feature | Effort | Days | Complexity |
|---|---|---|---|---|---|
| **P0** | 1 | Encrypt Plaid access token | S | 1–2 | Low |
| **P0** | 2 | Verify Plaid webhook signatures | S | 1–2 | Low |
| **P0** | 3 | Plaid connection health + reconnect (+ expose Link) | M | 4–6 | Medium |
| **P0** | 4 | Transactional email and alerts | M/L | 6–9 | Medium |
| **P0** | 5 | Wire the offer into Stripe (founding price, trial, counter) | S/M | 3–4 | Medium |
| **P0** | 6 | Pricing + comparison + security pages, real screenshots | M | 4–6 | Low |
| **P0** | 7 | Retire the Pegasus demo surface | S/M | 2–4 | Medium |
| | | **P0 subtotal** | | **22–33** | |
| **P1** | 1 | ⭐ Split transactions in the UI | M/L | 6–9 | Medium/High |
| **P1** | 2 | Manual transaction entry / edit / delete | M | 5–7 | Medium |
| **P1** | 3 | Statement reconciliation flow | M/L | 6–9 | Medium |
| **P1** | 4 | Auto-categorization rules | M | 5–8 | Medium |
| **P1** | 5 | In-app notification centre | M | 5–7 | Low/Medium |
| **P1** | 6 | User preferences | S/M | 3–5 | Low |
| **P1** | 7 | Mobile experience pass | M | 5–8 | Medium |
| | | **P1 subtotal** | | **35–53** | |
| **P2** | 1–11 | Growth and differentiation (table §6) | — | **55–80** | mixed |
| **P3** | 1–7 | Watch list (table §7) | — | **38–60** | mixed |

**P0 + P1 = ~57–86 dev-days**, or roughly **3–4.5 months** for one engineer at a
realistic 70% feature-time. Two engineers, or an aggressive P0-only push, gets the
founding-member launch open in about six weeks.

---

## 9. Recommended sequencing

**Sprint 1–2 (weeks 1–4) — "allowed to charge"**
P0.1 + P0.2 as one Plaid-hardening PR · P0.4 email layer · P0.7 demo removal (gate the
routes, drop the AI Chat nav link). Founder works P0.6 copy and screenshots in parallel.

**Sprint 3 (weeks 5–6) — "allowed to promise"**
P0.3 Plaid health and reconnect · P0.5 Stripe offer wiring · P0.6 pages ship.
**→ Founding-member push opens here.**

**Sprint 4–6 (weeks 7–12) — "the ledger is yours"**
P1.1 splits and P1.2 manual entry **designed and built together as one entry surface** ·
P1.6 preferences (cheap, unblocks email opt-ins properly).

**Sprint 7–8 (weeks 13–16) — "the chore is cheap and the promise is testable"**
P1.4 auto-categorization rules · P1.3 statement reconciliation · P1.5 notifications.

**Sprint 9+ (months 5–8) — channel-driven**
Choose P2 items by which channel is working, per the marketing plan's *more, better, new*
rule. If SEO is carrying: **P2.6 bank CSV presets** and **P2.4 debt planner** (content
fuel). If retention is the problem: **P2.1 recurring** → **P2.2 forecast**. If the ICP
keeps asking about net worth: **P2.3 investments**.

---

## 10. Risks and judgement calls I want on the record

1. **Splits are the one item I would fight for.** If only a single P1 ships, make it
   P1.1. We currently import financial structures we cannot author or edit, in the exact
   migration path that is our primary acquisition channel. Everything else on the P1 list
   is a wall users hit; this one is a wall we built and then sold tickets to.

2. **The reconciliation guarantee is currently unfalsifiable.** P1.3 is the instrument
   that makes the marketing claim honest in both directions. Until it ships, we have a
   refund promise with no way to demonstrate compliance — and the guarantee is load-bearing
   in the positioning.

3. **Multi-currency will be demanded earlier than P3 suggests.** Canadians with USD
   accounts are a large slice of our exact ICP and they will ask in month one. I am
   deferring it because it is a genuine architectural change, not because it is unimportant
   — and I am explicitly recommending the scoped "display-only USD accounts" escape hatch
   (P3.1) so we have an answer that is not "next year."

4. **`docs/saas-gaps-plan.md` should be retired or rewritten.** It lists onboarding, E2E
   testing and dashboard as open when all three shipped, and it does not know about the
   monthly review, YNAB import, transfer detection or the restyle. It is now actively
   misleading about where we stand. `docs/monthly-review-plan.md` still carries a
   "Status: proposal. No code written yet." header over a shipped 2,955-line app.

5. **My effort estimates assume the current engineer.** They are calibrated on this
   repo's own delivery record, which reflects deep familiarity with a genuinely unusual
   codebase (double-entry projections, transfer mirroring, team-scoped managers). Add
   50–100% for a new hire's first quarter, and expect P1.1 specifically to be the item
   where an unfamiliar engineer discovers the two-line assumptions the hard way.

6. **We have no analytics.** The marketing plan flags this as a Step-2 todo and it is
   still open. Every priority above is my judgement against the code and the ICP, not
   against behaviour — because there is no behaviour to read. I would spend half a day on
   Plausible plus the existing `AuditEvent` funnel before sprint 4, so that the P1 ordering
   can be argued with data instead of with me.
