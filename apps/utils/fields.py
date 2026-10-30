"""
Model fields shared across apps.

`EncryptedTextField` keeps a secret encrypted at rest -- in the database, its
backups and any dump of them -- using Fernet (AES-128-CBC + HMAC-SHA256) with
the key(s) in `FIELD_ENCRYPTION_KEY`. It is for values only ever read back
whole, like an API token: the ciphertext is randomised, so the field cannot be
filtered, ordered or made unique on.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

#: Marks a stored value as ciphertext, so a plaintext value written before the
#: field was encrypted is still read correctly (and re-encrypted on next save).
PREFIX = "fernet:"


@lru_cache(maxsize=4)
def _fernet(keys: str) -> MultiFernet:
    parts = [key.strip() for key in keys.split(",") if key.strip()]
    if not parts:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is empty.")
    return MultiFernet([Fernet(key.encode()) for key in parts])


def fernet() -> MultiFernet:
    """The configured keys: the first encrypts, any decrypts (so keys can rotate)."""
    return _fernet(settings.FIELD_ENCRYPTION_KEY)


def encrypt(value: str) -> str:
    return PREFIX + fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value.startswith(PREFIX):
        return value
    try:
        return fernet().decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        # Never fall back to the ciphertext: code would send it to an API as if
        # it were the secret. A wrong or missing key must fail loudly.
        raise ImproperlyConfigured("Could not decrypt a field: FIELD_ENCRYPTION_KEY does not match.") from exc


class EncryptedTextField(models.TextField):
    """A TextField stored encrypted (see the module docstring)."""

    def from_db_value(self, value, expression, connection):
        return value if value is None else decrypt(value)

    def to_python(self, value):
        return value if not isinstance(value, str) else decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "" or value.startswith(PREFIX):
            return value
        return encrypt(value)
