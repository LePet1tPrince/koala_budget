# Codebase Guidelines

## Architecture

- This is a Django project built on Python 3.12.
- User authentication uses `django-allauth`.
- The front end is mostly standard Django views and templates.
- The front end also uses React for dynamic user interfaces and interactions.
- React components are built using TypeScript and communicate with Django via a REST API.
- JavaScript files are kept in the `/assets/` folder and built by vite.
  JavaScript code is typically loaded via the static files framework inside Django templates using `django-vite`.
- Ignore the a standalone React front end in the `/frontend/` folder, which uses its own Vite build.
- APIs use Django Rest Framework, and JavaScript code that interacts with APIs uses an
  auto-generated OpenAPI-schema-baesd client.
- The front end uses Tailwind (Version 4) and DaisyUI. Some components use Material UI. Make sure to confirm which style is being used in a given component.
- The main database is Postgres.
- Celery is used for background jobs and scheduled tasks.
- Redis is used as the default cache, and the message broker for Celery (if enabled).

## Commands you can run

The following commands can be used for various tools and workflows.
A `Makefile` is provided to help centralize commands:

```bash
make  # List available commands
```

### First-time Setup

```bash
make init
```

### Starting the Application

```bash
make start     # Run in foreground with logs
make start-bg  # Run in background
```

Access the app at http://localhost:8000

### Stopping Services

```bash
make stop
```

## Common Commands

### Development

```bash
make ssh              # SSH into web container
make shell            # Open Python / Django shell
make dbshell          # Open PostgreSQL shell
make manage ARGS='command'  # Run any Django management command
```

### Database

```bash
make migrations       # Create new migrations
make migrate          # Apply migrations
```

### Testing

```bash
make test                              # Run all tests
make test ARGS='apps.module.tests.test_file'  # Run specific test
make test ARGS='path.to.test --keepdb'        # Run with options
```

### Python Code Quality

```bash
make ruff-format      # Format code
make ruff-lint        # Lint and auto-fix
make ruff             # Run both format and lint
```
### Python

```bash
make uv add '<package>'         # Add a new package
make requirements               # Rebuild and restart containers after updating packages
make uv run '<command> <args>'  # Run a Python command
```

### Frontend

```bash
make npm-install      # Install npm packages
make npm-install package-name  # Install specific package
make npm-uninstall package-name  # Uninstall package
make npm-dev          # Run the Vite development server
make npm-build        # Build for production
make npm-type-check   # Run TypeScript type checking
```

Note: Vite runs automatically with hot-reload when using `make start`.

### Translations

```bash
make translations     # Update and compile translation files
```

### Standalone Front End

The following commands can be used on the separate standalone frontend (`/frontend/` folder):

```bash
npm run dev       # Run development server
npm run build     # Run type checks and build for production
```

## General Coding Preferences

- Always prefer simple solutions.
- Avoid duplication of code whenever possible, which means checking for other areas of the codebase that might already have similar code and functionality.
- You are careful to only make changes that are requested or you are confident are well understood and related to the change being requested.
- When fixing an issue or bug, do not introduce a new pattern or technology without first exhausting all options for the existing implementation. And if you finally do this, make sure to remove the old implementation afterwards so we don’t have duplicate logic.
- Keep the codebase clean and organized.
- Avoid writing scripts in files if possible, especially if the script is likely only to be run once.
- Try to avoid having files over 200-300 lines of code. Refactor at that point.
- Don't ever add mock data to functions. Only add mocks to tests or utilities that are only used by tests.
- Always think about what other areas of code might be affected by any changes made.
- Never overwrite my .env file without first asking and confirming.

## Python Code Guidelines

### Code Style

- Follow PEP 8 with 120 character line limit.
- Use double quotes for Python strings (ruff enforced).
- Sort imports with isort (via ruff).
- Try to use type hints in new code. However, strict type-checking is not enforced and you can leave them out if it's burdensome.
  There is no need to add type hints to existing code if it does not already use them.

### Preferred Practices

- Use Django signals sparingly and document them well.
- Always use the Django ORM if possible. Use best practices like lazily evaluating querysets
  and selecting or prefetching related objects when necessary.
- Use function-based views by default, unless using a framework that relies on class-based views (e.g. Django Rest Framework).
- Always validate user input server-side.
- Handle errors explicitly, avoid silent failures.
- Use translation markup, usually `gettext_lazy` whenever using user-facing strings.

#### Django models

- All Django models should extend `apps.utils.models.BaseModel` (which adds `created_at` and `updated_at` fields) or `apps.teams.models.BaseTeamModel` (which also adds a `team`) if owned by a team.
- Models that extend `BaseTeamModel` should use the `for_team` model manager for queries that require team filtering. This will apply the team filter automatically based on the global team context. See `apps.teams.context.get_current_team`.
- The project's user model is `apps.users.models.CustomUser` and should be imported directly.
- The `Team` model is like a virtual tenant and most data access / functionality happens within
  the context of a `Team`.

##### Key Application Models and Views

**apps.accounts** - Manages the chart of accounts and transactional counterparties.

Models:
- `Account` - Represents a financial account (asset, liability, income, expense, or equity) with account type determined by its associated AccountGroup. Includes `account_number` (1000s for assets, 2000s for liabilities, etc.) and an optional `has_feed` flag for bank integrations. Has a property `account_balance` that calculates balance from journal lines.
- `AccountGroup` - Organizes accounts by type (asset, liability, income, expense, equity) and includes a description. Enforces unique names per team.
- `Payee` - Tracks who transactions are with. Simple model with name and unique constraint per team.

Views:
- `AccountsHomeView` - Home page displaying quick stats (account groups count, accounts count, payees count).
- Account/AccountGroup/Payee CRUD views - Standard Django class-based views (CreateView, UpdateView, DeleteView, DetailView, ListView) with `LoginAndTeamRequiredMixin` and team context.

**apps.journal** - Implements double-entry bookkeeping with journal entries and lines.

Models:
- `JournalEntry` - Represents a balanced double-entry transaction with entry_date, optional payee, description, source (manual, import, bank_match, recurring), and status (draft, posted, void). Extends `BaseTeamModel`. Has validation ensuring total debits equal total credits. Includes properties `total_debits`, `total_credits`, and `is_balanced`.
- `JournalLine` - Individual debit/credit line in a journal entry. Each line has either a `dr_amount` or `cr_amount` (not both). Includes `is_cleared` and `is_reconciled` flags. Stores optional FK to Budget for auto-linking based on account and entry date. Validates that only one of debit or credit is used.

Views:
- `JournalEntryViewSet` - REST API viewset providing CRUD for journal entries with custom actions `post_entry` (draft→posted) and `void_entry` (posted→void). Only balanced entries can be posted.
- `SimpleLineViewSet` - REST API viewset for simplified line interface presenting transactions from a single account perspective (like a bank register). Creates/updates journal entries with exactly 2 lines (main line with specified account, sibling line with category account using opposite amounts). Destroying a line deletes the entire journal entry.
- `journal_home` - Template view for main journal page displaying accounts and transactions.

**apps.budget** - Monthly budget planning and tracking.

Models:
- `Budget` - Represents a monthly budget for an income/expense category (Account). Has `month` (first day of month), `category` FK to Account, and `budget_amount`. Unique constraint on team/month/category combination. Ordered by month (descending) then account number.

Views:
- `budget_month_view` - Template view displaying a budget month with categories grouped by account group. Shows budgeted, actual, and available amounts with subtotals per group and grand totals. Allows form submission to update budget amounts for each category.

Services:
- `BudgetService` - Service class providing methods: `budgeted(category, month)`, `actual(category, month)`, and `available(category, month)` for calculations used in views and elsewhere.

**apps.goals** - Financial goal tracking and savings planning.

Models:
- `Goal` - Represents a financial goal with `name`, `description`, `goal_amount`, optional `target_date`, and `saved_amount`. Extends `BaseTeamModel`. Has property to calculate remaining amount.

Views:
- `GoalsHomeView` - Home/list page for goals. Calculates net worth from journal lines (sum of asset/liability debits - credits), grand total available from budget service, sum of saved amounts across all goals, and left to allocate (net_worth - available - saved). Lists all goals with context including counts and financial calculations.
- Goal CRUD views - Standard class-based views (CreateView, UpdateView, DeleteView, DetailView) with `LoginAndTeamRequiredMixin` and team context.

**apps.plaid** - Plaid bank feed integration for importing and categorizing bank transactions.

Architecture Philosophy:
- **The bank feed is a task list, not the ledger.** Plaid transactions are stored as staging objects (`ImportedTransaction`) and only converted to ledger entries (`JournalEntry`) when the user categorizes them.
- **Unified Bank Feed API** - Single endpoint combines both ledger transactions (`JournalLine`) and uncategorized Plaid imports into one feed for display.
- **Lazy Categorization** - Journal entries are created only when user explicitly categorizes a transaction, preserving double-entry bookkeeping integrity.

Models:
- `PlaidItem` - Represents a Plaid connection to a financial institution. Stores `plaid_item_id` (Plaid's unique ID), `access_token` (for Plaid API calls - TODO: encrypt in production), `institution_name`, `cursor` (for incremental transaction sync), and `is_active` flag. Extends `BaseTeamModel`.
- `PlaidAccount` - Links a Plaid account to a ledger Account. Stores `plaid_account_id`, FK to `PlaidItem`, optional FK to `Account` (ledger account - set by user), `name`, `mask` (last 4 digits), `type` (depository/credit), and `subtype` (checking/savings). Extends `BaseTeamModel`.
- `ImportedTransaction` - Staging area for Plaid transactions before categorization. Stores transaction details (`plaid_transaction_id`, `amount`, `date`, `authorized_date`, `name`, `merchant_name`), categorization hints (`personal_finance_category`, `category_confidence`, `payment_channel`), optional FK to `JournalEntry` (set when categorized), and full `raw` JSON from Plaid. Extends `BaseTeamModel`. Amount convention: positive = outflow, negative = inflow (Plaid's convention).

Views & API Endpoints:
- `BankFeedViewSet` - Unified bank feed API at `/a/{team}/plaid/api/bank-feed/`
  - `GET /` - Returns combined feed of ledger transactions and uncategorized Plaid imports for a given account. Query param: `account` (account ID). Returns `BankFeedRowSerializer` data with unified format.
  - `POST /categorize/` - Batch categorize transactions. Body: `rows` (list of row IDs), `category` (account ID). Creates journal entries for Plaid transactions or updates category for ledger transactions.
- `create_link_token_view` - `POST /a/{team}/plaid/api/link-token/` - Creates Plaid Link token for frontend initialization. Returns `{"link_token": "..."}`.
- `exchange_public_token_view` - `POST /a/{team}/plaid/api/exchange-token/` - Exchanges public token from Plaid Link for access token. Body: `public_token`, `institution_id`, `accounts`. Creates `PlaidItem` and `PlaidAccount` records. Returns created item and accounts.
- `PlaidItemViewSet` - CRUD for Plaid items at `/a/{team}/plaid/api/items/`
- `PlaidAccountViewSet` - CRUD for Plaid accounts at `/a/{team}/plaid/api/accounts/`
- `ImportedTransactionViewSet` - Read-only view of imported transactions at `/a/{team}/plaid/api/transactions/`

Serializers:
- `BankFeedRowSerializer` - Unified format for both ledger and Plaid transactions. Fields: `id`, `source` (ledger/plaid), `date`, `description`, `account`, `category`, `inflow`, `outflow`, `is_pending`, `is_cleared`, `payment_channel`, `confidence`, `journal_line_id`, `imported_transaction_id`, `is_editable`.
- `journal_line_to_feed_row(line)` - Adapter function converting `JournalLine` to bank feed row format. Extracts data from line, parent journal entry, and sibling line.
- `imported_tx_to_feed_row(tx)` - Adapter function converting `ImportedTransaction` to bank feed row format. Converts Plaid amount convention to inflow/outflow.
- Standard model serializers: `PlaidItemSerializer`, `PlaidAccountSerializer`, `ImportedTransactionSerializer`

Services (`services.py`):
- `get_plaid_client()` - Returns configured Plaid API client using settings `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`.
- `create_link_token(user_id, client_name)` - Creates Plaid Link token for initializing Plaid Link in frontend.
- `exchange_public_token(public_token)` - Exchanges public token for access token and item ID.
- `get_accounts(access_token)` - Fetches account details from Plaid.
- `get_institution(institution_id)` - Fetches institution details from Plaid.
- `sync_transactions(access_token, cursor)` - Syncs transactions using Plaid's `/transactions/sync` endpoint with cursor-based pagination. Returns added, modified, removed transactions and next cursor.

Background Tasks (`tasks.py`):
- `sync_plaid_transactions(plaid_item_id)` - Celery task to sync transactions for a specific Plaid item. Uses cursor-based pagination to fetch all new/modified/removed transactions. Calls processor functions for each transaction type.
- `sync_all_plaid_items()` - Celery task to sync all active Plaid items. Can be scheduled with Celery Beat for periodic syncing.
- `process_added_transaction(plaid_item, tx_data)` - Creates `ImportedTransaction` from Plaid transaction data. Skips if already exists.
- `process_modified_transaction(plaid_item, tx_data)` - Updates existing `ImportedTransaction` if not yet categorized (journal_entry is null). Otherwise treats as new.
- `process_removed_transaction(plaid_item, tx_data)` - Deletes `ImportedTransaction` if not yet categorized (journal_entry is null).

Helper Functions (`views.py`):
- `create_journal_from_import(imported_tx_id, category_account, team)` - Creates a balanced `JournalEntry` with 2 lines from an `ImportedTransaction`. Links the import to the journal entry. Converts Plaid amount convention to proper debits/credits. Sets source to `SOURCE_IMPORT`.
- `update_simple_line_category(journal_line_id, category_account, team)` - Updates the category (sibling line's account) for an existing simple journal entry. Only works for 2-line entries.

Configuration:
- Settings: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (sandbox/development/production URL)
- Dependencies: `plaid-python==38.0.0`, `django-encrypted-model-fields==0.6.5` (for future encryption)
- URLs: Registered at `/a/{team}/plaid/` in main URL config

Admin:
- Full Django admin interface for `PlaidItem`, `PlaidAccount`, and `ImportedTransaction` with search, filtering, and autocomplete.

Integration Notes:
- All models extend `BaseTeamModel` for multi-tenancy support
- Uses `for_team` manager for team-scoped queries
- Preserves double-entry bookkeeping when creating journal entries from imports
- Transaction amounts follow Plaid convention in `ImportedTransaction` (positive=outflow) but are converted to proper debit/credit in journal entries
- Categorized transactions are linked to journal entries via FK, preventing duplicate categorization
- Modified/removed Plaid transactions only affect uncategorized imports; categorized transactions are preserved in the ledger

#### Django URLs, Views and Teams

- Many apps have a `urls.py` with a `urlpatterns` and a `team_urlpatterns` value.
  The `urlpatterns` are for views that happen outside the context of a `Team` model.
  `team_urlpatterns` are for views that happen within the context of a `Team`.
- Anything in `team_urlpatterns` will have URLs of the format `/a/<team_slug>/<app_path>/<pattern>/`.
- Any view referenced by `team_urlpatterns` must contain `team_slug` as the first argument.
- For team-based views, the `@login_and_team_required` and `@team_admin_required` decorators
  can be used to ensure the user is logged in and can access the associated team.
- If not specified, assume that a given url/view belongs within the context of a team
  (and follows the above guidance)

## Django Template Coding Guidelines for HTML files

- Indent templates with two spaces.
- Use standard Django template syntax.
- Use translation markup, usually `translate` or `blocktranslate trimmed` with user-facing text.
  Don't forget to `{% load i18n %}` if needed.
- JavaScript and CSS files built with vite should be included with the `{% vite_asset %}` template tag provided by `django-vite` (must have `{% load django_vite %}` at the top of the template)
- Any react components also need `{% vite_react_refresh %}` for Vite + React's HMR functionality, from the same `django_vite` template library)
- Use the Django `{% static %}` tag for loading images and external JavaScript / CSS files not managed by vite.
- Prefer using alpine.js for page-level JavaScript, and avoid inline `<script>` tags where possible.
- Break re-usable template components into separate templates with `{% include %}` statements.
  These normally go into a `components` folder.
- Use DaisyUI styling markup for available components. When not available, fall back to standard TailwindCSS classes.
- Stick with the DaisyUI color palette whenever possible.

## JavaScript Code Guidelines

### Code Style

- Use ES6+ syntax for JavaScript code.
- Use 2 spaces for indentation in JavaScript, JSX, and HTML files.
- Use single quotes for JavaScript strings.
- End statements with semicolons.
- Use camelCase for variable and function names.
- Use PascalCase for component names (React).
- For React components, use functional components with hooks rather than class components.
- Use explicit type annotations in TypeScript files.
- Use ES6 import/export syntax for module management.

### Preferred Practices
- React components should be kept small and focused on a single responsibility.
- Store state at an appropriate level; avoid prop drilling by using context when necessary.
- Where possible, use TypeScript for React components to leverage type safety.
- Use Alpine.js for client-side interactivity that doesn't require server interaction.
- Avoid inline `<script>` tags wherever posisble.
- Use the generated OpenAPI client for API calls instead of raw fetch or axios calls.
- Validate user input on both client and server side.
- Handle errors explicitly in promise chains and async functions.

### Build System

- Code is bundled using vite and served with `django-vite`.
