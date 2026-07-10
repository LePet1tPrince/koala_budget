---
name: verify
description: Build, run, and drive Koala Budget locally (no Docker) to verify changes end-to-end in a real browser.
---

# Verifying Koala Budget changes without Docker

The Makefile assumes Docker Compose; in environments without a Docker daemon, run everything directly:

```bash
sudo service postgresql start && sudo service redis-server start
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
sudo -u postgres createdb koala_budget
uv sync
DJANGO_DATABASE_PASSWORD=postgres uv run python manage.py migrate
npm install
npx vite --port 5173 &                                          # dev assets (DEBUG=True uses vite dev mode)
DJANGO_DATABASE_PASSWORD=postgres uv run python manage.py runserver 0.0.0.0:8000 &
```

Tests: `DJANGO_DATABASE_PASSWORD=postgres DJANGO_SETTINGS_MODULE=koala_budget.settings_test uv run python manage.py test apps.<app> --parallel 1`

## Seeding a user + team

Create a `CustomUser`, add to a `Team` with `through_defaults={"role": ROLE_ADMIN}`, and create income/expense `AccountGroup`s + `Account`s via `manage.py shell`. `BOOTSTRAP_TEAM_ON_CREATE` also seeds a default chart of accounts.

## Driving the browser

Playwright with the pre-installed Chromium (`executablePath: '/opt/pw-browsers/chromium'`). Install `playwright-core` in a scratch dir, not the repo.

Gotchas:

- **Proxy**: launch with `proxy: { server: process.env.HTTPS_PROXY, bypass: 'localhost,127.0.0.1' }` or localhost requests die with `ERR_TUNNEL_CONNECTION_FAILED`.
- **Login form**: the first `button[type=submit]` on the login page is "Sign in with Google" — submit by pressing Enter in the password field instead.
- **Email verification**: allauth redirects to confirm-email; mark the address verified via `allauth.account.models.EmailAddress` (`verified=True, primary=True`).
- **Login 500**: the `user_logged_in` audit signal crashes on non-team URLs (`AuditEvent.team` gets a lazy `None`). Work around by creating a session in `manage.py shell` (`SessionStore`, set `_auth_user_id`/`_auth_user_backend`/`_auth_user_hash`, `.create()`) and injecting the `sessionid` cookie.
- **`networkidle` never fires** (django-browser-reload polling); wait for selectors instead.
