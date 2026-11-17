"""
Security utilities for password hashing, PIN verification, JWT tokens, and RBAC.
Uses hashlib.scrypt with cryptographically random salts and constant-time comparisons.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt

MIN_SECRET_LENGTH = 43
INSECURE_SECRET_VALUES = frozenset(
    {
        "change-me",
        "change-me-in-production",
        "your-secret-key",
        "replace-with-at-least-43-character-value-from-32-random-bytes",
        "udaya-library-secret-key-change-in-production-2026",
    }
)


def _required_secret_key() -> str:
    secret_key = os.getenv("JWT_SECRET_KEY", "").strip()
    if not secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set before starting Udaya Library. "
            "Generate at least 32 random bytes and provide their encoded value."
        )
    normalized_secret = secret_key.lower()
    if (
        len(secret_key) < MIN_SECRET_LENGTH
        or normalized_secret in INSECURE_SECRET_VALUES
        or normalized_secret.startswith(("replace-with-", "change-me", "your-"))
    ):
        raise RuntimeError(
            "JWT_SECRET_KEY is insecure. Use an unpredictable value generated from "
            "at least 32 random bytes."
        )
    return secret_key


SECRET_KEY = _required_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


def hash_password(password: str) -> tuple[str, str]:
    """
    Hash a password using scrypt with a random 16-byte salt.
    Returns (hex_hash, hex_salt).
    """
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384,
        r=8,
        p=1,
        maxmem=64 * 1024 * 1024,
    )
    return key.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """
    Verify password against stored scrypt hash and salt in constant time.
    """
    try:
        expected = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=16384,
            r=8,
            p=1,
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(expected.hex(), password_hash)
    except Exception:
        return False


def hash_pin(pin: str, salt: str) -> str:
    """
    Hash a trusted-device PIN using PBKDF2-HMAC-SHA256.
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    ).hex()


def verify_pin(pin: str, pin_hash: str, salt: str) -> bool:
    """
    Verify trusted-device PIN in constant time.
    """
    computed = hash_pin(pin, salt)
    return hmac.compare_digest(computed, pin_hash)


def create_access_token(
    user_id: int,
    email: str,
    role: str,
    name: str,
    device_id: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token containing user identity and role.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "name": name,
        "device_id": device_id,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """
    Decode and validate a signed JWT token.
    Returns payload dictionary or None if invalid/expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None
