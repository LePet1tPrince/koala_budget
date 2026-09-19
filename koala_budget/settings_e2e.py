from .settings import *  # noqa: F403

BOOTSTRAP_TEAM_ON_CREATE = False

# Skip email verification so tests can log in without verifying email
ACCOUNT_EMAIL_VERIFICATION = "none"

# Speed up password hashing
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Capture emails in memory rather than sending them
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Allow the live server to accept connections from Playwright
ALLOWED_HOSTS = ["*"]

# Disable Stripe live mode and Plaid in tests
STRIPE_LIVE_MODE = False
PLAID_ENV = "sandbox"

# Raise the auth rate-limit cap so E2E tests (all sharing 127.0.0.1) can
# each perform a fresh login without hitting the default 10-req/5-min ceiling.
AUTH_RATE_LIMIT_MAX_REQUESTS = 10000

# Turn off allauth's own rate limiting for the same reason. Every E2E test logs
# in through `authenticated_page`, and the whole suite comes from 127.0.0.1, so
# allauth's default "login": "30/m/ip" counts the suite as one attacker: once a
# run packs more than 30 logins into a rolling minute, the login POST is
# answered with the rate-limit page instead of the redirect, the browser never
# reaches /a/<slug>/, and the fixture's `wait_for_url` fails the test with a
# navigation timeout. Which test that lands on depends on runner speed, so it
# reads as a flake rather than the IP-scoped limit it is. The counters live in
# the process-wide LocMemCache, so they accumulate across the whole session.
#
# The sentinel is `False`, not `{}`: allauth's `RATE_LIMITS` property merges
# whatever dict it is given over its own defaults, so an empty dict turns
# nothing off. Only `False` short-circuits it.
ACCOUNT_RATE_LIMITS = False

# Vite integration for E2E tests.
# - Local dev: keep DJANGO_VITE_DEV_MODE unset (defaults to True) and
#   run `make start-bg` so the Vite dev server is available.
# - CI / after `npm run build`: set DJANGO_VITE_DEV_MODE=False in the
#   environment to serve assets from the build manifest instead.
DJANGO_VITE = {
    "default": {
        "dev_mode": env.bool("DJANGO_VITE_DEV_MODE", default=True),  # noqa: F405
        "dev_server_host": os.environ.get("VITE_DEV_SERVER_HOST", "localhost"),  # noqa: F405
        "dev_server_port": 5173,
        "manifest_path": BASE_DIR / "static" / ".vite" / "manifest.json",  # noqa: F405
    }
}

# Run Celery tasks inline. The YNAB import is a Celery task, and a test (or an E2E
# run) has no worker -- eager mode is what makes the wizard finish rather than sit
# at 0%.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
