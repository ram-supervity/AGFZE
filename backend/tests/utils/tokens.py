"""RS256 tokens signed by a keypair generated for this test session.

The public half is published as a JWKS document that stands in for Keycloak's, so the tests drive
app.core.security through a real signature verification instead of stubbing the decoder out. Only
the network fetch of the key set is replaced; every claim check runs for real.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.core.config import settings

KID = "agfze-test-signing-key"
ALGORITHM = "RS256"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_numbers = _private_key.public_key().public_numbers()

PRIVATE_PEM: str = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()

PUBLIC_PEM: str = (
    _private_key.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


def _b64u_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


JWKS: dict[str, list[dict[str, str]]] = {
    "keys": [
        {
            "kty": "RSA",
            "kid": KID,
            "use": "sig",
            "alg": ALGORITHM,
            "n": _b64u_uint(_public_numbers.n),
            "e": _b64u_uint(_public_numbers.e),
        }
    ]
}


def build_token(**overrides: Any) -> str:
    """Sign an access token shaped like the one Keycloak issues for the AGFZE realm."""
    issued_at = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "iss": settings.KEYCLOAK_ISSUER,
        "aud": settings.KEYCLOAK_AUDIENCE,
        "azp": settings.KEYCLOAK_AUDIENCE,
        "typ": "Bearer",
        "sub": "3f1c2a8e-0000-4000-8000-0000000000aa",
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(minutes=15)).timestamp()),
        "email": "purchase.user@agfze.ae",
        "preferred_username": "purchase.user",
        "name": "Marco Bellini",
        "realm_access": {"roles": ["purchase_user"]},
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_PEM, algorithm=ALGORITHM, headers={"kid": KID})


def expired_token(**overrides: Any) -> str:
    """A correctly signed token whose exp is far enough back to clear JWT_LEEWAY_SECONDS."""
    expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
    claims: dict[str, Any] = {
        "iat": int((expired_at - timedelta(minutes=15)).timestamp()),
        "nbf": int((expired_at - timedelta(minutes=15)).timestamp()),
        "exp": int(expired_at.timestamp()),
    }
    claims.update(overrides)
    return build_token(**claims)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
