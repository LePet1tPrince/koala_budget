"""
Verifying that a webhook really came from Plaid.

Plaid signs every webhook: the `Plaid-Verification` header is a JWT (ES256)
whose payload carries the SHA-256 of the request body and when it was issued.
Following https://plaid.com/docs/api/webhooks/webhook-verification/:

1. read the JWT header without verifying it; refuse anything but ES256;
2. fetch the public key for its `kid` from /webhook_verification_key/get
   (cached; an expired key is refused);
3. verify the signature with that key, and refuse a token issued more than
   five minutes ago (a replay);
4. compare the body's SHA-256 to the token's `request_body_sha256` in
   constant time.

Unverified, the webhook endpoint would let anyone who can guess an item id
mark a connection broken or revoked (the ITEM webhooks change what the Inbox
asks of the user) and trigger syncs at will.
"""

import hashlib
import hmac
import logging
import time

import jwt
from django.core.cache import cache

from . import services

logger = logging.getLogger(__name__)

#: Plaid's own replay window.
MAX_AGE_SECONDS = 5 * 60

KEY_CACHE_SECONDS = 24 * 60 * 60


class WebhookVerificationError(Exception):
    """The webhook is not provably from Plaid."""


def _key(key_id) -> dict:
    cache_key = f"plaid:webhook-key:{key_id}"
    key = cache.get(cache_key)
    if key is None:
        key = services.get_webhook_verification_key(key_id)
        cache.set(cache_key, key, KEY_CACHE_SECONDS)
    expired_at = key.get("expired_at")
    if expired_at and expired_at <= time.time():
        cache.delete(cache_key)
        raise WebhookVerificationError("The signing key has expired.")
    return key


def verify(body: bytes, token: str | None):
    """Raise WebhookVerificationError unless `token` is Plaid's signature over `body`."""
    if not token:
        raise WebhookVerificationError("No Plaid-Verification header.")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise WebhookVerificationError("Malformed verification token.") from exc
    if header.get("alg") != "ES256" or not header.get("kid"):
        raise WebhookVerificationError("Unexpected verification token algorithm.")

    try:
        jwk = _key(header["kid"])
    except WebhookVerificationError:
        raise
    except Exception as exc:
        raise WebhookVerificationError("Could not fetch Plaid's signing key.") from exc

    public = {name: jwk[name] for name in ("kty", "crv", "x", "y") if name in jwk}
    try:
        claims = jwt.decode(
            token,
            key=jwt.PyJWK({**public, "alg": "ES256"}).key,
            algorithms=["ES256"],
            options={"require": ["iat"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise WebhookVerificationError("Invalid signature.") from exc

    if time.time() - claims["iat"] > MAX_AGE_SECONDS:
        raise WebhookVerificationError("Verification token is too old.")

    expected = claims.get("request_body_sha256") or ""
    if not hmac.compare_digest(hashlib.sha256(body).hexdigest(), expected):
        raise WebhookVerificationError("Body does not match its signature.")
