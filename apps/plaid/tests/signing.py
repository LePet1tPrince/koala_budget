"""Sign test webhooks the way Plaid does (ES256 JWT over the body's SHA-256)."""

import hashlib
import json
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

KEY_ID = "test-key-1"
_PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC_JWK = {
    **json.loads(jwt.algorithms.ECAlgorithm.to_jwk(_PRIVATE.public_key())),
    "alg": "ES256",
    "kid": KEY_ID,
    "use": "sig",
    "created_at": 1,
    "expired_at": None,
}


def sign(body: bytes, *, iat=None, key=_PRIVATE, kid=KEY_ID, body_hash=None):
    claims = {"iat": int(time.time()) if iat is None else iat}
    claims["request_body_sha256"] = body_hash or hashlib.sha256(body).hexdigest()
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})
