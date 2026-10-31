"""Browser calling: a token for the dashboard, and the webhook Twilio asks where to connect."""

from typing import Annotated
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.api.deps import AnyPrincipal
from app.core.errors import error_responses
from app.core.twilio import TOKEN_TTL_SECONDS, access_token, twilio_config, verify_twilio_request

# Long enough for any booking conversation, short enough to cap the cost of a forgotten call.
CALL_TIME_LIMIT_SECONDS = 15 * 60

router = APIRouter(prefix="/twilio", tags=["voice"])


class CallToken(BaseModel):
    token: str
    identity: str
    expires_in: int


@router.post(
    "/token",
    summary="A short-lived token for calling the receptionist from the browser",
    responses=error_responses(401) | {503: {"description": "Browser calling not configured"}},
)
async def call_token(principal: AnyPrincipal) -> CallToken:
    identity = f"dashboard-{principal.user_id}"
    return CallToken(
        token=access_token(twilio_config(), identity),
        identity=identity,
        expires_in=TOKEN_TTL_SECONDS,
    )


@router.post(
    "/voice",
    summary="Twilio asks where to connect a browser call (signed by Twilio)",
    response_class=Response,
    responses=error_responses(401),
)
async def connect_call(_: Annotated[dict[str, str], Depends(verify_twilio_request)]) -> Response:
    """Always the configured salon line. Whatever the request asks for is ignored on purpose."""
    config = twilio_config()
    target = (
        f"<Sip>{escape(config.dial_to)}</Sip>"
        if config.dial_to.startswith("sip:")
        else f"<Number>{escape(config.dial_to)}</Number>"
    )
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Dial answerOnBridge="true" callerId={quoteattr(config.caller_id)} '
        f'timeLimit="{CALL_TIME_LIMIT_SECONDS}">{target}</Dial></Response>'
    )
    return Response(content=twiml, media_type="application/xml")
