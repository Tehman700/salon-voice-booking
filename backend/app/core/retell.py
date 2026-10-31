"""Checking that a request really came from Retell.

Retell signs every function call and webhook with the account's API key in the
`X-Retell-Signature` header, as `v=<unix ms>,d=<hex hmac-sha256 of body + timestamp>`. Requests
with a bad or stale signature are refused before any data is touched. An older plain
`hex hmac-sha256(body)` form is accepted too, since replays are harmless: every action the voice
agent can take is idempotent.
"""

import hashlib
import hmac
import logging
import re
import time

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError, NotAuthenticatedError

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "x-retell-signature"
_VERSIONED = re.compile(r"^v=(\d+),d=([0-9a-fA-F]+)$")


class VoiceNotConfiguredError(AppError):
    status_code = 503
    code = "voice_not_configured"
    message = "The voice integration is not configured on this server."


def _digest(key: str, payload: str) -> str:
    return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def signature_problem(
    body: bytes, signature: str | None, key: str, *, max_age_seconds: int, now: float | None = None
) -> str | None:
    """Why a signature is not acceptable, or None if it is. The reason holds no secrets."""
    if not signature:
        return "no signature header"
    text = body.decode("utf-8", errors="replace")
    versioned = _VERSIONED.match(signature)
    if versioned:
        timestamp, digest = versioned.groups()
        age = abs((now if now is not None else time.time()) - int(timestamp) / 1000)
        if age > max_age_seconds:
            return f"timestamp is {int(age)}s away from now (limit {max_age_seconds}s)"
        if hmac.compare_digest(_digest(key, text + timestamp), digest.lower()):
            return None
        # TEMPORARY diagnostic: does a different formula match? (Removed once Retell is verified.)
        variants = {
            "body only": _digest(key, text),
            "timestamp+body": _digest(key, timestamp + text),
            "body.timestamp": _digest(key, text + "." + timestamp),
            "timestamp.body": _digest(key, timestamp + "." + text),
        }
        hits = [
            name for name, value in variants.items() if hmac.compare_digest(value, digest.lower())
        ]
        if hits:
            return f"digest does not match, but formula {hits} would (algorithm differs)"
        return (
            "digest does not match (wrong API key, or the body changed); "
            f"digest has {len(digest)} characters"
        )
    if hmac.compare_digest(_digest(key, text), signature.lower()):
        return None
    return f"unrecognised signature format ({len(signature)} characters)"


def signature_is_valid(
    body: bytes, signature: str | None, key: str, *, max_age_seconds: int, now: float | None = None
) -> bool:
    return signature_problem(body, signature, key, max_age_seconds=max_age_seconds, now=now) is None


async def verify_retell_request(request: Request) -> bytes:
    """FastAPI dependency: returns the raw body once its signature has checked out."""
    settings = get_settings()
    if settings.retell_api_key is None:
        raise VoiceNotConfiguredError
    body = await request.body()
    problem = signature_problem(
        body,
        request.headers.get(SIGNATURE_HEADER),
        settings.retell_api_key.get_secret_value(),
        max_age_seconds=settings.retell_signature_max_age_seconds,
    )
    if problem is not None:
        logger.warning("Refused %s: %s (body %d bytes)", request.url.path, problem, len(body))
        raise NotAuthenticatedError("Invalid signature.", code="invalid_signature")
    return body
