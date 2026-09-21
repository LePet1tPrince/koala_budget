from .settings import *  # noqa: F403

BOOTSTRAP_TEAM_ON_CREATE = False

DEBUG = False


PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Run Celery tasks inline. The YNAB import is a Celery task, and a test (or an E2E
# run) has no worker -- eager mode is what makes the wizard finish rather than sit
# at 0%.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
