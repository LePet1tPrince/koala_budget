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
