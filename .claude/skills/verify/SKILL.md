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

## Windows host via WSL2 (no Docker, no native Django/Node — this dev machine)

This machine has no Docker and no Django/Node installed on Windows itself, but has **WSL2 with an Ubuntu 26.04 distro already set up** (name `Ubuntu`) with PostgreSQL 18, Redis, Node 20, and `uv` already installed via apt/curl, plus `loginctl enable-linger` already enabled for the WSL user so background services survive after a command returns. Postgres already has a `koala_budget` DB and the `postgres` role password is `postgres`.

If your Claude Code session itself is a **Windows session** (not already running inside WSL), you don't have a native `wsl` bash tool — drive it by shelling out from PowerShell/Bash with `wsl -d Ubuntu -- bash -c '...'`. Quoting nested single/double quotes through PowerShell is error-prone; write the script to a temp `.sh` file first (e.g. via the Write tool) and run `wsl -d Ubuntu -- bash "/mnt/c/path/to/script.sh"` instead of inlining it. If your session is already running natively inside WSL (e.g. you started `claude` from an Ubuntu terminal), just use bash directly — skip the `wsl -d Ubuntu --` wrapper entirely.

**Critical: never run `uv sync` or `npm install` against the repo while it lives on `/mnt/c/...`.** Windows' filesystem (`drvfs`) doesn't support the file operations these tools need — `uv sync` fails with `Operation not permitted` trying to hardlink/copy into `.venv`, and `npm install` fails with `EPERM ... chmod` on binary shims. Two different failure modes, same root cause.

Fix: **copy the source tree into WSL's native Linux filesystem** and build/run/test from there, e.g. `~/koala_budget`. A git worktree's `.git` file points to an absolute Windows path (`gitdir: C:\...`), which doesn't resolve inside WSL, so `git clone` of a worktree fails too — instead `rsync -a --delete` the tree over, excluding `.git`, `node_modules`, `.venv`, `__pycache__`, `.ruff_cache`:

```bash
rsync -a --delete --exclude '.git' --exclude 'node_modules' --exclude '.venv' \
  --exclude '__pycache__' --exclude '.ruff_cache' --exclude '*.pyc' \
  "/mnt/c/path/to/your/worktree/" "$HOME/koala_budget/"
```

Re-run that rsync whenever you want the native copy to pick up newer edits from the Windows-side worktree. Then `cd ~/koala_budget` and run `uv sync` / `npm install` / `manage.py migrate` / tests / the dev servers there — all native-filesystem, so no `uv`/`npm` failures. (`uv sync` will place `.venv` inside `~/koala_budget` fine on native fs — no need to relocate it there.)

**Background dev servers can get silently killed** if started with a plain `nohup ... &` from a `wsl -d Ubuntu -- bash script.sh` invocation — once that invocation's session ends, the process can get reaped. Fully detach with `setsid` and redirect stdin from `/dev/null`:

```bash
cd ~/koala_budget
setsid nohup npx vite --port 5173 --host 0.0.0.0 < /dev/null > "$HOME/vite.log" 2>&1 &
disown
export DJANGO_DATABASE_PASSWORD=postgres
setsid nohup uv run python manage.py runserver 0.0.0.0:8000 < /dev/null > "$HOME/django.log" 2>&1 &
disown
```

After starting, always verify the process is still alive a few seconds later (`ps aux | grep vite`) rather than trusting the startup banner — a silently-reaped process leaves no error in its log.

WSL2's `localhost` port forwarding works both directions, so `http://localhost:8000/` and `http://localhost:5173/` are reachable from Windows (e.g. a Windows-side browser pane) once the servers are confirmed running in WSL — no extra port-forwarding setup needed.
