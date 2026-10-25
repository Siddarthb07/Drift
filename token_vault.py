"""Optional Fernet encryption for OAuth watch tokens at rest."""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

_PREFIX = "enc:v1:"


def _fernet():
    key = os.getenv("DRIFT_TOKEN_KEY") or os.getenv("SECRET_KEY") or ""
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    digest = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(plaintext: str) -> str:
    f = _fernet()
    if not f:
        return plaintext
    return _PREFIX + f.encrypt(plaintext.encode()).decode()


def open_token(blob: Optional[str]) -> Optional[str]:
    if not blob:
        return blob
    if not blob.startswith(_PREFIX):
        return blob
    f = _fernet()
    if not f:
        raise RuntimeError("Encrypted token present but cryptography/SECRET_KEY unavailable")
    return f.decrypt(blob[len(_PREFIX):].encode()).decode()
