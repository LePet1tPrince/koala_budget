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

# Use the Vite dev server for E2E tests.
# When running tests, ensure the 'vite' Docker service is also running
# (e.g. via `make start-bg` before `make test-e2e`).
# Alternatively run `make npm-build` once to produce static assets,
# then set DJANGO_VITE_DEV_MODE=False here to use the build output.
DJANGO_VITE = {
    "default": {
        "dev_mode": True,
        "dev_server_port": 5173,
        "manifest_path": BASE_DIR / "static" / ".vite" / "manifest.json",  # noqa: F405
    }
}
