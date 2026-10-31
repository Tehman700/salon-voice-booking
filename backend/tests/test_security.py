import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.security import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.core.slug import randomized_slug, slugify, unique_slug

# --- Passwords ---


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("a-long-enough-password")
    assert hashed.startswith("$argon2id$")
    assert verify_password("a-long-enough-password", hashed)[0] is True
    assert verify_password("another-password-1", hashed)[0] is False


def test_password_hashes_are_salted() -> None:
    assert hash_password("same-password-123") != hash_password("same-password-123")


def test_dummy_verification_never_raises() -> None:
    verify_dummy_password("whatever-the-attacker-sent")


# --- Access tokens ---


def test_access_token_roundtrip() -> None:
    user_id, business_id = uuid.uuid4(), uuid.uuid4()
    claims = decode_access_token(create_access_token(user_id, business_id, "owner"))
    assert (claims.user_id, claims.business_id, claims.role) == (user_id, business_id, "owner")


def test_access_token_without_business() -> None:
    user_id = uuid.uuid4()
    claims = decode_access_token(create_access_token(user_id, None, "platform_admin"))
    assert claims.business_id is None


def test_access_tokens_are_unique() -> None:
    user_id = uuid.uuid4()
    assert create_access_token(user_id, None, "owner") != create_access_token(
        user_id, None, "owner"
    )


def test_access_token_expires_after_the_configured_ttl() -> None:
    token = create_access_token(uuid.uuid4(), None, "owner")
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["exp"] - payload["iat"] == get_settings().access_token_ttl_seconds


def _signed(**claims: object) -> str:
    settings = get_settings()
    assert settings.jwt_secret is not None
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=1),
    }
    base.update(claims)
    return jwt.encode(base, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def test_expired_token() -> None:
    with pytest.raises(TokenExpiredError):
        decode_access_token(_signed(exp=datetime.now(UTC) - timedelta(seconds=1), role="owner"))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "abc",
        "a.b.c",
        pytest.param(lambda: _signed(role="owner", sub="not-a-uuid"), id="bad-subject"),
        pytest.param(lambda: _signed(role="owner", sub=None), id="no-subject"),
        pytest.param(lambda: _signed(role="owner", bid="not-a-uuid"), id="bad-business"),
        pytest.param(lambda: _signed(sub=str(uuid.uuid4())), id="no-role"),
    ],
)
def test_malformed_tokens_are_invalid(token: object) -> None:
    value = token() if callable(token) else token
    assert isinstance(value, str)
    with pytest.raises(TokenInvalidError):
        decode_access_token(value)


def test_token_signed_with_another_secret_is_invalid() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "owner",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
        },
        "z" * 40,
        algorithm="HS256",
    )
    with pytest.raises(TokenInvalidError):
        decode_access_token(forged)


def test_algorithm_none_is_not_accepted() -> None:
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "owner",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
        },
        "",
        algorithm="none",
    )
    with pytest.raises(TokenInvalidError):
        decode_access_token(unsigned)


# --- Opaque tokens ---


def test_opaque_tokens_are_long_unique_and_hash_deterministically() -> None:
    first, second = generate_opaque_token(), generate_opaque_token()
    assert first != second
    assert len(first) >= 40
    assert hash_opaque_token(first) == hash_opaque_token(first)
    assert hash_opaque_token(first) != hash_opaque_token(second)
    assert first not in hash_opaque_token(first)


# --- Slugs ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Glow Salon", "glow-salon"),
        ("  Glow & Co.  Salon!! ", "glow-co-salon"),
        ("Café Étoile", "cafe-etoile"),
        ("日本語", "salon"),  # nothing ASCII left -> fallback
        ("---", "salon"),
        ("A" * 200, "a" * 60),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_unique_slug() -> None:
    assert unique_slug("main", set()) == "main"
    assert unique_slug("main", {"main"}) == "main-2"
    assert unique_slug("main", {"main", "main-2", "main-3"}) == "main-4"
    long_base = "x" * 80
    assert len(unique_slug(long_base, {long_base})) <= 80


def test_randomized_slug_keeps_the_base_and_varies() -> None:
    results = {randomized_slug("main") for _ in range(20)}
    assert len(results) > 1
    assert all(r.startswith("main-") and len(r) == len("main-") + 4 for r in results)
    assert len(randomized_slug("x" * 80)) <= 80


# --- Cursors ---


def test_cursor_roundtrip() -> None:
    created, row_id = datetime(2026, 10, 31, 12, 30, 45, 123456, tzinfo=UTC), uuid.uuid4()
    assert decode_cursor(encode_cursor(created, row_id)) == (created, row_id)


@pytest.mark.parametrize("cursor", ["", "garbage", "bm90LWEtY3Vyc29y", "%%%"])
def test_invalid_cursor(cursor: str) -> None:
    with pytest.raises(ValidationFailedError):
        decode_cursor(cursor)
