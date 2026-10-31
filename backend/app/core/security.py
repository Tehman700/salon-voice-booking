"""Password hashing, access tokens (JWT) and opaque token helpers."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass


# --- Passwords (Argon2id) ---


@lru_cache
def _password_hasher() -> PasswordHash:
    if get_settings().environment == "test":
        # Cheapest legal parameters: keeps the suite fast. Hashes record their own parameters,
        # so they are still verified correctly (and upgraded) if parameters change later.
        return PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))
    return PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher().hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (is_valid, replacement_hash). A replacement means the stored hash is outdated."""
    return _password_hasher().verify_and_update(password, password_hash)


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def verify_dummy_password(password: str) -> None:
    """Spend the same time as a real check, so unknown emails can't be told apart by latency."""
    _password_hasher().verify(password, _dummy_hash())


# --- Access tokens ---


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    business_id: uuid.UUID | None
    role: str


def create_access_token(user_id: uuid.UUID, business_id: uuid.UUID | None, role: str) -> str:
    settings = get_settings()
    assert settings.jwt_secret is not None
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "bid": str(business_id) if business_id else None,
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access_token(token: str) -> AccessTokenClaims:
    settings = get_settings()
    assert settings.jwt_secret is not None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
        bid = payload.get("bid")
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            business_id=uuid.UUID(bid) if bid else None,
            role=str(payload["role"]),
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError from exc
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise TokenInvalidError from exc


# --- Opaque tokens (refresh tokens, invites) ---


def generate_opaque_token() -> str:
    """256 bits of randomness, URL-safe. Only its hash is ever stored."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
