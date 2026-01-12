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
