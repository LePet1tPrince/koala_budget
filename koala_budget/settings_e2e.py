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
