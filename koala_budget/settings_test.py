from .settings import *  # noqa: F403

BOOTSTRAP_TEAM_ON_CREATE = False

DEBUG = False


PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
