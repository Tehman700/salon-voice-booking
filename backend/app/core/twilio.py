"""Browser calling through Twilio: access tokens for the dashboard, and checking Twilio's webhooks.

Only two things are trusted to Twilio's side: a short-lived token lets a signed-in dashboard user
place a call from the browser, and Twilio then asks our `/twilio/voice` webhook where to connect
it. That webhook is signed by Twilio and always connects to the one configured salon line, so
nobody can use it to call anywhere else.
"""

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

import jwt
from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError, NotAuthenticatedError

TOKEN_TTL_SECONDS = 3600
SIGNATURE_HEADER = "x-twilio-signature"


class BrowserCallingNotConfiguredError(AppError):
    status_code = 503
    code = "browser_calling_not_configured"
    message = "Browser calling is not configured on this server."


@dataclass(frozen=True)
class TwilioConfig:
    account_sid: str
    api_key_sid: str
    api_key_secret: str
    twiml_app_sid: str
    auth_token: str
    dial_to: str
    caller_id: str


def twilio_config() -> TwilioConfig:
    s = get_settings()
    if not (
        s.twilio_account_sid
        and s.twilio_api_key_sid
        and s.twilio_api_key_secret
        and s.twilio_twiml_app_sid
        and s.twilio_auth_token
        and s.twilio_dial_to
    ):
        raise BrowserCallingNotConfiguredError
    return TwilioConfig(
        account_sid=s.twilio_account_sid,
        api_key_sid=s.twilio_api_key_sid,
        api_key_secret=s.twilio_api_key_secret.get_secret_value(),
        twiml_app_sid=s.twilio_twiml_app_sid,
        auth_token=s.twilio_auth_token.get_secret_value(),
        dial_to=s.twilio_dial_to,
        caller_id=s.twilio_caller_id or s.twilio_dial_to,
    )


def access_token(config: TwilioConfig, identity: str, *, now: float | None = None) -> str:
    """A Twilio Voice access token (a JWT signed with the API key secret), outgoing calls only."""
    issued = int(now if now is not None else time.time())
    payload = {
        "jti": f"{config.api_key_sid}-{issued}",
        "iss": config.api_key_sid,
        "sub": config.account_sid,
        "iat": issued,
        "nbf": issued,
        "exp": issued + TOKEN_TTL_SECONDS,
        "grants": {
            "identity": identity,
            "voice": {"outgoing": {"application_sid": config.twiml_app_sid}},
        },
    }
    return jwt.encode(
        payload, config.api_key_secret, algorithm="HS256", headers={"cty": "twilio-fpa;v=1"}
    )


def expected_signature(auth_token: str, url: str, params: list[tuple[str, str]]) -> str:
    """Twilio's scheme: HMAC-SHA1 of the full URL followed by each POST field (sorted) and value."""
    payload = url + "".join(f"{key}{value}" for key, value in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def public_url(request: Request) -> str:
    """The URL Twilio called, as Twilio saw it (we sit behind a TLS-terminating proxy)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get(
        "host", request.url.netloc
    )
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{proto}://{host}{request.url.path}{query}"


async def verify_twilio_request(request: Request) -> dict[str, str]:
    """FastAPI dependency: the webhook's form fields, once Twilio's signature has checked out."""
    config = twilio_config()
    body = (await request.body()).decode()
    params = parse_qsl(body, keep_blank_values=True)
    signature = request.headers.get(SIGNATURE_HEADER, "")
    expected = expected_signature(config.auth_token, public_url(request), params)
    if not hmac.compare_digest(signature, expected):
        raise NotAuthenticatedError("Invalid signature.", code="invalid_signature")
    return dict(params)
