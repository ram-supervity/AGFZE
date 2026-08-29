"""Print one VAPID key pair, ready to paste into an environment file.

Run once per environment and keep what it prints. Regenerating the pair invalidates every push
subscription every browser has ever taken against this deployment, and each of those users has to
grant permission again - so this is not a thing to re-run casually.

    make vapid-keys

The keys are emitted in the raw, unpadded URL-safe base64 form the Web Push standard uses: the
public key as the uncompressed P-256 point a browser passes to `pushManager.subscribe`, and the
private key as the 32-byte scalar `pywebpush` signs with. `py_vapid`'s own `save_key` writes PEM
files instead, which is the wrong shape for an environment variable and for the browser both.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid01

PRIVATE_KEY_BYTES = 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate() -> tuple[str, str]:
    vapid = Vapid01()
    vapid.generate_keys()
    public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    private = vapid.private_key.private_numbers().private_value.to_bytes(PRIVATE_KEY_BYTES, "big")
    return _b64(public), _b64(private)


def main() -> None:
    public, private = generate()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")


if __name__ == "__main__":
    main()
