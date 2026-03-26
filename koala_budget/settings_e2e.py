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

# Vite integration for E2E tests.
# - Local dev: keep DJANGO_VITE_DEV_MODE unset (defaults to True) and
#   run `make start-bg` so the Vite dev server is available.
# - CI / after `npm run build`: set DJANGO_VITE_DEV_MODE=False in the
#   environment to serve assets from the build manifest instead.
DJANGO_VITE = {
    "default": {
        "dev_mode": env.bool("DJANGO_VITE_DEV_MODE", default=True),  # noqa: F405
        "dev_server_port": 5173,
        "manifest_path": BASE_DIR / "static" / ".vite" / "manifest.json",  # noqa: F405
    }
}
