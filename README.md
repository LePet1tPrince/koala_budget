# Koala Budget

Koala Budget is a personal finance application for freelancers that implements double-entry bookkeeping with bank feed integration, monthly budgeting, and savings goals. It is a multi-tenant SaaS app built on the [Pegasus](https://www.saaspegasus.com/) framework.

## Key Features

- **Double-entry bookkeeping** — Full chart of accounts (assets, liabilities, equity, income, expenses) with balanced journal entries
- **Bank feed integration** — Import transactions via [Plaid](https://plaid.com/) (live bank sync) or CSV upload, then categorize them into the ledger
- **Monthly budgeting** — Set per-category spending targets and track actuals against budget in real time
- **Savings goals** — Create goals with target amounts and track progress through monthly allocations
- **AI-assisted categorization** — Chat interface powered by pydantic-ai/LiteLLM (Claude/GPT) to suggest transaction categories
- **Multi-tenancy** — Each user workspace is a Team; all financial data is fully isolated per team
- **Stripe subscriptions** — Team-level billing via dj-stripe

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 6.0+ / Python 3.12, Django REST Framework, Celery + Redis |
| Database | PostgreSQL 17 |
| Frontend | React 19.x + TypeScript, Alpine.js, Tailwind CSS 4.x + DaisyUI 5.x |
| Build | Vite 7.x, auto-generated OpenAPI TypeScript client |
| Auth | django-allauth (social auth + 2FA) |
| Payments | dj-stripe (Stripe) |
| Deployment | Docker Compose (local), Digital Ocean App Platform (production) |

## Documentation

Full documentation lives in the [`docs/`](./docs/README.md) directory:

- [Architecture overview](./docs/architecture.md) — system design, layers, and data flow
- [Entity Relationship Diagram](./docs/erd.md) — database schema
- [Data Model Guide](./docs/data-model.md) — detailed model reference
- [API Guide](./docs/api-guide.md) — REST API reference
- [Frontend Guide](./docs/frontend-guide.md) — React/TypeScript patterns
- [Getting Started](./docs/getting-started.md) — developer onboarding

---

## Quickstart

### Prerequisites

To run the app in the recommended configuration, you will need the following installed:
- [Docker](https://www.docker.com/get-started) and [Docker Compose](https://docs.docker.com/compose/install)

On Windows, you will also need to install `make`, which you can do by
[following these instructions](https://stackoverflow.com/a/57042516/8207).

### Initial setup

Run the following command to initialize your application:

```bash
make init
```

This will:

- Build and run your Postgres database
- Build and run your Redis database
- Build and run Django dev server
- Build and run your Celery worker
- Build and run your front end (JavaScript and CSS) pipeline
- Run your database migrations

Your app should now be running! You can open it at [localhost:8000](http://localhost:8000/).

If you're just getting started, [try these steps next](https://docs.saaspegasus.com/getting-started/#post-installation-steps).

## Using the Makefile

You can run `make` to see other helper functions, and you can view the source
of the file in case you need to run any specific commands.

For example, you can run management commands in containers using the same method
used in the `Makefile`. E.g.

```
docker compose exec web uv run manage.py createsuperuser
```

## Installation - Native

You can also install/run the app directly on your OS using the instructions below.

You can setup a virtual environment and install dependencies in a single command with:

```bash
uv sync
```

This will create your virtual environment in the `.venv` directory of your project root.

## Set up database

*If you are using Docker you can skip these steps.*

Create a database named `koala_budget`.

```
createdb koala_budget
```

Create database migrations:

```
uv run manage.py makemigrations
```

Create database tables:

```
uv run manage.py migrate
```

## Running server

**Docker:**

```bash
make start
```

**Native:**

```bash
uv run manage.py runserver
```

## Building front-end

To build JavaScript and CSS files, first install npm packages:

**Docker:**

```bash
make npm-install
```

**Native:**

```bash
npm install
```

Then build (and watch for changes locally):

**Docker:**

```bash
make npm-watch
```

**Native:**

```bash
npm run dev
```

## Running Celery

Celery can be used to run background tasks.
If you use Docker it will start automatically.

You can run it using:

```bash
celery -A koala_budget worker -l INFO --pool=solo
```

Or with celery beat (for scheduled tasks):

```bash
celery -A koala_budget worker -l INFO -B --pool=solo
```

Note: Using the `solo` pool is recommended for development but not for production.

## Updating translations

**Using make:**

```bash
make translations
```

**Native:**

```bash
uv run manage.py makemessages --all --ignore node_modules --ignore .venv
uv run manage.py makemessages -d djangojs --all --ignore node_modules --ignore .venv
uv run manage.py compilemessages --ignore .venv
```

## Google Authentication Setup

To setup Google Authentication, follow the [instructions here](https://docs.allauth.org/en/latest/socialaccount/providers/google.html).

## Github Authentication Setup

To setup Github Authentication, follow the [instructions here](https://docs.allauth.org/en/latest/socialaccount/providers/github.html).

## Installing Git commit hooks

To install the Git commit hooks run the following:

```shell
uv run pre-commit install --install-hooks
```

Once these are installed they will be run on every commit.

For more information see the [docs](https://docs.saaspegasus.com/code-structure#code-formatting).

## Running Tests

To run tests:

**Using make:**

```bash
make test
```

**Native:**

```bash
uv run manage.py test
```

Or to test a specific app/module:

**Using make:**

```bash
make test ARGS='apps.web.tests.test_basic_views --keepdb'
```

**Native:**

```bash
uv run manage.py test apps.web.tests.test_basic_views --keepdb
```

On Linux-based systems you can watch for changes using the following:

**Docker:**

```bash
find . -name '*.py' | entr docker compose exec web uv run manage.py test apps.web.tests.test_basic_views
```

**Native:**

```bash
find . -name '*.py' | entr uv run manage.py test apps.web.tests.test_basic_views
```
