# Koala Budget — Go-to-Market Plan: 0 → 1,000 Users (Canada)

**Audience:** budget-savvy Canadian individuals and households.
**Competitors to displace:** YNAB, Monarch Money, Google Sheets, and the hole Mint left behind.
**Timeline:** ~8 months, three phases.
**Owner:** founder (this is a founder-led motion — nothing here requires an agency or a marketing hire).

This plan borrows two operating systems:

- **Alex Hormozi** ($100M Offers / $100M Leads): fix the *offer* before touching traffic; work the four lead channels in order of effort-to-payoff (warm outreach → content → cold outreach → paid); "more, better, new."
- **Gary Vaynerchuk**: document don't create, platform-native content at volume, jab-jab-jab-right-hook (~10 give-value posts per 1 ask), hand-reply to every comment while the audience is small enough that you can.

---

## Step 0 — Positioning: pick the fight we can win

We cannot out-feature YNAB or out-fund Monarch. We win by being **specifically for someone**:

> **"The budgeting app for Canadians who actually want their numbers to be right."**

Hero one-liner:

> *Know exactly where every dollar went. Double-entry accuracy, real financial reports, built for Canadian banks — priced in CAD.*

### Defensible differentiators (all real, all shipped)

| # | Differentiator | Why it wins |
|---|---------------|-------------|
| 1 | **Real double-entry accounting** — journal entries, audit trail, voided-entry handling | YNAB/Monarch are "close enough" apps. We're the app for spreadsheet people, engineers, accountants — the budget-savvy segment. |
| 2 | **Transfer duplicate detection + mirror legs** | Every Canadian YNAB user has been burned by a credit-card payment counted twice. We detect, resolve, and keep one journal entry. Marketing weapon, not a feature note. |
| 3 | **Real financial reports** — personal income statement, balance sheet, cash flow, net worth trend, Sankey, budget-vs-actual | Monarch has pretty charts; we have *financial statements for your life*. |
| 4 | **Excel-paste budget grid** | The migration bridge for the huge "I budget in Google Sheets" crowd. Paste a year of budget numbers, Ctrl+V, done. |
| 5 | **Built for Canada** — CSV import works with *any* Canadian bank (Plaid coverage in Canada is famously spotty; we have a fallback), pricing in CAD | YNAB is ~$109 USD (~$150 CAD), Monarch ~$100 USD. Price at **$79–99 CAD/yr** and the comparison table writes itself. |
| 6 | **Households (Teams)** | Budget with a partner as a first-class concept — also the referral loop. |

---

## Step 1 — The Grand Slam Offer (Weeks 1–2)

Hormozi's value equation: **(Dream outcome × Perceived likelihood) ÷ (Time delay × Effort)**. Attack every term:

1. **Founding Member deal (first 500 users):** $59 CAD/year **locked for life**, founding badge, direct line to the founder for feature requests. Real scarcity — publish the live counter ("437/500 spots left") and let it be the recurring "right hook."
2. **Kill the effort term:** "Switch from YNAB / Mint / Sheets in 15 minutes." The CSV importer with category mapping and account suggestions already exists — productize it as **migration concierge**: for the first 100 users, personally migrate their data on a screen-share. Unscalable on purpose.
3. **The reconciliation guarantee:** *"If your accounts don't reconcile to the penny in 30 days, full refund — and I'll help you export everything."* On-brand for a double-entry app; no competitor can copy it.
4. **60-day free trial** — two full statement cycles, "because that's how long it takes to trust your numbers." (YNAB's is 34 days; ours is meaningfully longer *and* has a reason.)

---

## Step 2 — Fix the funnel before touching traffic (Weeks 1–2)

- [x] Rewrite the landing page (stock Pegasus template as of July 2026): real hero copy, product-truth features, **Koala vs YNAB vs Monarch comparison table** with a CAD-pricing row and a "works with Canadian banks" row, founding-member offer, reconciliation guarantee. *(Done — see `templates/web/components/`.)*
- [ ] Replace illustration placeholders with **real product screenshots** — the Sankey diagram and net-worth chart are visual candy; use them in the hero and section images.
- [ ] Three SEO comparison pages: `/vs/ynab`, `/vs/monarch`, `/mint-alternative-canada`. "YNAB alternative Canada" and "Mint replacement Canada" have steady search volume and weak competition. Written once, they recruit forever.
- [ ] Analytics (Plausible or similar) so signup conversion is measurable from day one.
- [ ] **Trust prerequisites before taking strangers' bank data:** encrypt `PlaidItem.access_token` (currently plaintext — see Known Issues in CLAUDE.md), verify Plaid webhook signatures, publish a short security page. Budget-savvy Canadians *will* ask.
- [ ] Wire the founding-member price into Stripe (dj-stripe) and put the live spots-remaining counter on the landing page.

---

## Step 3 — Users 1–100: do things that don't scale (Weeks 2–6)

No ads. Channel order at zero: **warm outreach → refugee-hunting → communities**.

### 3a. Warm outreach — target 20–30 users
List every person you know who budgets. Personal message, not a blast: *"I built this — can I set up your budget with you for 20 minutes?"* Onboard each one personally. You're buying two things: users, and a live view of exactly where the funnel confuses people.

### 3b. The Mint/YNAB refugee hunt — target 30–50 users
Daily search on Reddit, X, and Threads for people *actively complaining*: "YNAB price increase," "YNAB Canadian bank," "Mint alternative Canada," "Monarch Canada." Reply helpfully and specifically — e.g. *"If your issue is duplicate transfers from credit-card payments, I built a thing that detects those. Happy to migrate your data personally."* 10–15 genuine replies/day. It's cold outreach that doesn't feel cold because they raised their hand first.

### 3c. Communities — carefully
- **r/PersonalFinanceCanada (1.5M+ members) bans self-promotion.** Do NOT drop links. Become a genuinely useful commenter for 3–4 weeks, then ask the mods about policy for member-built tools (intro post / AMA). Play the long game here; getting banned from PFC is unrecoverable.
- Builder-friendly venues meanwhile: **r/ynab** (alternatives are openly discussed), **r/Frugal_Canada**, **RedFlagDeals personal-finance forum** (very Canadian, deal-driven — CAD pricing lands hard here), **Blossom** (Canadian PF/investing community app), **r/SideProject**, and **Hacker News "Show HN"** (the double-entry angle is HN catnip).

### 3d. Learn from every user
Ask each of the first 100: *"What almost stopped you from signing up?"* and *"Where were you budgeting before?"* Their words become the ad copy, landing-page objections section, and comparison-page content later.

---

## Step 4 — Users 100–500: the content engine (Months 2–4)

Gary Vee layer: **document, don't create**; native to each platform; volume over polish.

### Pillar content — 1×/week (long-form video or written)
- **Build in public with real numbers** — the product is *about* numbers, so the content is the product: "My actual net-worth Sankey for June." "What double-entry caught that my spreadsheet missed."
- **Canadian money content:** "The real cost of YNAB in CAD," "Why your credit-card payment double-counts in every budget app (and the accounting fix)," "TFSA vs RRSP as a cash-flow report."

### Chopped content — every pillar becomes 5–10 pieces
- **TikTok / Reels / Shorts:** 30-second screen captures — the Sankey rendering, transfer-dedup catching a duplicate, pasting a spreadsheet into the budget grid. Product-as-content. Canadian PF TikTok is big and under-served on the nerdy end.
- **X / Threads:** build-in-public thread + takes on budgeting-app pricing in CAD.

### SEO — 1 post/week, long-tail Canadian
"How to import **[RBC / TD / Scotiabank / BMO / CIBC / Tangerine / EQ Bank]** transactions into a budget app" — one post per major bank. CSV import supports all of them; these convert forever.

### Lead magnet (give away what they'd pay for)
A genuinely excellent **free Canadian budget spreadsheet template** (Google Sheets) with the pitch: *"When you outgrow this, paste it straight into Koala Budget — literally, Ctrl+V."* Distributable everywhere links are allowed, and it filters for exactly our ICP: spreadsheet-comfortable, budget-savvy Canadians.

### Cadence rule
Jab, jab, jab, right hook: ~10 value posts per 1 ask. The founding-member counter is the standing right hook.

---

## Step 5 — Users 500–1,000: borrowed audiences + loops (Months 4–8)

### 5a. Canadian PF creators (mid-size beats mega)
Targets in the 10–50k range: Jessica Moorhouse, Barry Choi, Money After Graduation, Steph & Den, Brandon Beavis, plus a dozen similar YouTube/podcast accounts. Offer: **free year + recurring affiliate (e.g. 30%, easy via Stripe)** and a real story angle — *"the app that replaced Mint for Canadians."* One good "I tried every Mint alternative in Canada" video can be worth 200 signups and keeps ranking for years.

### 5b. Referral loop
Double-sided: **give a month, get a month.** Budget apps spread inside households — the Teams model makes "invite your partner" a natural in-product prompt that also boosts retention.

### 5c. Seasonality — plan the calendar around it
**January** (new-year budgets) and **February–April** (RRSP deadline + tax season) are Canada's PF traffic spikes. Ship the best content, the Product Hunt launch, and press pitches into those windows. Pitch Canadian money press (MoneySense, Globe & Mail personal finance, CBC money desk) with the *story*, not the app: *"Mint died and left a million Canadians without a budget app that speaks CAD."*

### 5d. Paid ads — only now, only small
$500–1,000 CAD/month on Google Search against proven terms ("ynab alternative canada", "mint replacement canada"). Paid pours gas on a funnel already shown to convert; before that it burns money.

---

## The math

Rough attribution to 1,000 (no channel needs to be a home run):

| Channel | Users |
|---|---|
| Warm outreach + refugee-hunting | ~100 |
| Communities (Reddit, RFD, Blossom, HN) | ~150 |
| SEO / comparison pages | ~250 |
| Short-form content | ~150 |
| Creators / affiliates | ~250 |
| Referral loop | ~100 |

## Weekly operating cadence

- **Daily (45 min):** 10 helpful replies where the ICP complains; respond to every comment on our own content.
- **Weekly:** 1 pillar piece → 5+ chopped clips; 1 SEO post; 5 creator/partnership emails; talk to 3 users.
- **Monthly:** review signups by channel; double down on the top channel, cut the bottom one (**more, better, new** — in that order).

## KPIs

| Metric | Target |
|---|---|
| Landing page → signup conversion | ≥ 3% |
| Trial → active (categorized 50+ transactions) | ≥ 40% |
| Founding-member conversions | 500 by month 6 |
| Weekly content output | 1 pillar + 5 chopped + 1 SEO post |
| Time to 1,000 users | ≤ 8 months |

## Positioning cheat-sheet (for all copy)

- **Never say:** "budgeting made easy," "take control of your finances" (everyone says this).
- **Always say:** numbers that reconcile · real financial statements · built for Canadian banks · priced in CAD · no double-counted transfers.
- **Tone:** confident, numerate, a little nerdy. Our user reads the footnotes.
