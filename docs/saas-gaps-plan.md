# SaaS Gaps Plan — Koala Budget

> Comprehensive plan to bring Koala Budget from MVP to production-ready SaaS.

---

## Current State (What We Have)

- **Core product**: Double-entry bookkeeping, bank feed (Plaid + CSV), budgeting, goals, reports (income statement, balance sheet, net worth, sankey)
- **Multi-tenancy**: Team-scoped data via `BaseTeamModel`
- **Auth**: django-allauth (email/password, Google, GitHub), 2FA
- **Subscriptions**: Stripe checkout + customer portal + webhooks + feature gating via dj-stripe
- **API**: DRF with OpenAPI schema + generated TypeScript client
- **CI/CD**: GitHub Actions (tests, frontend build, Claude PR bot)
- **Deployment**: DigitalOcean App Platform (web, celery worker, celery beat, PostgreSQL, Valkey)
- **Error tracking**: Sentry (optional via env var)
- **Health checks**: django-health-check (DB, Celery, Redis)
- **Background tasks**: Celery + Beat
- **AI/Chat**: pydantic-ai with LiteLLM for smart categorization
- **UI**: Tailwind CSS + DaisyUI, dark mode, i18n
- **Admin tools**: Impersonation (hijack), feature flags (Waffle)

---

## Phase 1 — Launch Blockers

These must be completed before charging customers.

### 1.1 Rate Limiting / API Throttling ✅
**Status**: Complete

**What was done**:
- DRF throttle classes configured in `settings.py` (100/hr anon, 1000/hr authenticated, 5/min auth endpoints)
- Custom `AuthRateLimitMiddleware` for Django view-based auth endpoints (login, signup, password reset) — 10 POST requests per 5 min per IP
- Renders `429.html` error page with `Retry-After` header
- Fixed `DummyCache` → `LocMemCache` so rate limiting works in development
- Tests in `apps/api/tests/test_rate_limiting.py`

**Files created/modified**:
- `apps/api/middleware.py` — Auth rate limit middleware
- `apps/api/throttling.py` — Custom DRF throttle class
- `apps/api/tests/test_rate_limiting.py` — 10 tests
- `koala_budget/settings.py` — Middleware, throttle config, cache fix

---

### 1.2 Data Export ✅
**Status**: Complete

**What was done**:
- CSV export endpoints for income statement, balance sheet, account activity, and all transactions
- Export buttons on report pages that inherit date range filters via query string passthrough
- Export button on account activity detail page

**Files created/modified**:
- `apps/reports/exports.py` — CSV generation functions
- `apps/reports/views.py` — Export view functions with `@login_and_team_required`
- `apps/reports/urls.py` — 4 export URL patterns
- `templates/reports/income_statement.html` — Export CSV button
- `templates/reports/balance_sheet.html` — Export CSV button
- `templates/reports/reports_home.html` — Data Exports section
- `templates/reports/account_activity.html` — Export CSV button

---

### 1.3 Terms of Service / Privacy Policy ✅
**Status**: Complete

**What was done**:
- Full 12-section Terms of Service with i18n support
- Full 12-section Privacy Policy with i18n support
- Both linked from site footer
- Signup consent checkbox updated: "I agree to the Terms of Service and Privacy Policy" with links to both

**Files created/modified**:
- `templates/web/terms.html` — Updated from placeholder to full content
- `templates/web/privacy.html` — Created
- `apps/web/urls.py` — Added `/privacy/` route
- `templates/web/components/footer.html` — Added ToS and Privacy links
- `apps/teams/forms.py` — Updated signup consent label with both links

---

### 1.4 Account Deletion / Data Portability (GDPR) ✅
**Status**: Complete

**What was done**:
- "Download My Data" — ZIP archive with CSV files for all user/team data (profile, accounts, journal entries, budgets, goals, Plaid items)
- "Delete Account" — Confirmation page requires typing email address; deletes PROTECT-referenced models in dependency order, then team, then user
- Data Management section on profile page with download and delete buttons

**Files created/modified**:
- `apps/users/services.py` — `export_user_data()` and `delete_user_account()`
- `apps/users/views.py` — `download_data` and `delete_account` views
- `apps/users/urls.py` — `/download-data/` and `/delete-account/` routes
- `templates/account/components/data_management.html` — Profile component
- `templates/account/delete_account.html` — Confirmation page
- `templates/account/profile.html` — Includes data management component

---

### 1.5 Transactional Email Notifications
**Why**: Users get zero emails beyond signup admin alert. Need lifecycle and financial alert emails.

**Implementation**:
- Welcome email on signup
- Budget overspend alerts (when actual > budgeted)
- Plaid connection error alerts
- Subscription expiry/renewal warnings
- Weekly/monthly financial summary (opt-in, via Celery Beat)
- Email preference settings page

**Files to create/modify**:
- `apps/users/emails.py` — Email builder functions
- `apps/users/tasks.py` — Celery tasks for async email
- `apps/budget/signals.py` — Budget overspend detection
- `templates/emails/` — Email templates (HTML + text)
- `apps/users/models.py` — Email preference fields
- Configure production email backend (Mailgun/SES via django-anymail)

---

### 1.6 Onboarding / Setup Wizard
**Why**: New users land in an empty app with no guidance. Activation rates will suffer.

**Implementation**:
- Post-signup redirect to onboarding flow
- Step 1: Welcome + explain the app
- Step 2: Create chart of accounts (offer templates: freelancer, small business, personal)
- Step 3: Connect bank (Plaid) or import CSV, or skip
- Step 4: Set up first budget categories
- Track onboarding completion on Team model
- Show "getting started" checklist on dashboard until dismissed

**Files to create/modify**:
- `apps/web/views.py` — Onboarding views
- `apps/web/services.py` — Chart of accounts templates
- `templates/web/onboarding/` — Step templates
- `apps/teams/models.py` — Add `onboarding_completed` field
- Redirect logic in middleware or login signal

---

### 1.7 End-to-End Testing with Playwright
**Why**: No e2e tests exist. Need confidence that critical user flows work before launch.

**Implementation**:
- Install Playwright and configure for Django
- Write e2e tests for critical paths:
  - Signup → onboarding → dashboard
  - Login → view bank feed → categorize transaction
  - Create budget → view budget → check actuals
  - Run reports (income statement, balance sheet)
  - Subscription checkout flow
  - Account deletion flow
- Add to CI/CD pipeline
- Docker service for running e2e tests

**Files to create/modify**:
- `playwright.config.ts` — Playwright configuration
- `e2e/` — Test directory
- `e2e/fixtures/` — Test data setup
- `e2e/tests/` — Test files
- `.github/workflows/e2e.yml` — CI workflow
- `package.json` — Add Playwright dependency
- `Makefile` — Add `make e2e` target

---

## Phase 2 — Retention Essentials

Post-launch features that drive daily usage and user trust.

### 2.1 Dashboard / Home Page
Summary view after login: account balances, recent transactions, budget status, goal progress, uncategorized transaction count.

### 2.2 Recurring Transactions
`SOURCE_RECURRING` exists on JournalEntry but isn't implemented. Add recurring transaction rules with Celery Beat scheduling.

### 2.3 Transaction Search & Filtering
Full-text search across journal entries and bank transactions. Filter by date, account, payee, amount range.

### 2.4 Auto-Categorization Rules
Rule-based system: "transactions matching X always categorize as Y." Supplements the AI chat approach.

### 2.5 Plaid Error Handling / Reconnection
UI for connection health, reconnection flow when tokens expire, alerts on sync failures.

### 2.6 Audit Trail / Activity Log
Change history on critical models (JournalEntry, Account, Budget). Use django-auditlog or similar.

---

## Phase 3 — Growth Features

Differentiation and churn reduction.

### 3.1 In-App Notification Center
Surface alerts inside the app (budget exceeded, goal reached, uncategorized pile-up).

### 3.2 User Preferences / Settings Page
Currency, date format, notification opt-in/out, default accounts, language, timezone.

### 3.3 Attachments / Receipt Upload
Attach receipts/invoices to journal entries for tax purposes.

### 3.4 Multi-Currency Support
Currency handling beyond single-currency. Exchange rates, multi-currency reports.

### 3.5 Landing / Marketing Pages
Public-facing marketing site, pricing page, feature comparison.

### 3.6 Help Center / In-App Documentation
User-facing FAQs, tooltips, accounting concept explanations.

### 3.7 Mobile Responsiveness / PWA
Ensure mobile-first experience, consider PWA support.

### 3.8 Scheduled/Automated Reports
Weekly email summaries, scheduled PDF report generation.

---

## Implementation Order (Phase 1)

Recommended order based on dependencies and impact:

| Order | Task | Rationale |
|-------|------|-----------|
| 1 | Rate Limiting | Quick win, security foundation |
| 2 | Data Export | Needed by GDPR task, builds export infrastructure |
| 3 | Terms of Service / Privacy Policy | Quick win, legal foundation |
| 4 | Account Deletion / GDPR | Depends on data export |
| 5 | Transactional Emails | Depends on email backend being configured |
| 6 | Onboarding Wizard | Largest task, benefits from all above being in place |
| 7 | Playwright E2E Tests | Tests all the above flows |

---

## Success Criteria

Phase 1 is complete when:
- [x] All API endpoints have rate limits
- [x] Users can export their transactions as CSV
- [ ] Users can export reports as PDF
- [x] Terms of Service and Privacy Policy pages exist and are linked from signup
- [x] Users can delete their account and download all their data
- [ ] Users receive welcome email, budget alerts, and can manage email preferences
- [ ] New users go through a guided onboarding flow
- [ ] Critical user flows are covered by Playwright e2e tests
- [ ] All e2e tests pass in CI
