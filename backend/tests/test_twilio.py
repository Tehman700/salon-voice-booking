"""Calling the receptionist from the browser through Twilio."""

from urllib.parse import urlencode

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.twilio import expected_signature
from tests.booking_helpers import MONDAY, salon
from tests.helpers import build_world
from tests.retell_helpers import call_object, tool

PUBLIC_VOICE_URL = "https://43-205-17-140.sslip.io/twilio/voice"
AUTH_TOKEN = "test-auth-token"  # the twilio_settings fixture value
PROXY_HEADERS = {"x-forwarded-proto": "https", "host": "43-205-17-140.sslip.io"}


async def twilio_posts(client: AsyncClient, params: dict[str, str]) -> tuple[int, str]:
    """POST to the voice webhook the way Twilio does, through the TLS proxy."""
    body = urlencode(params)
    signature = expected_signature(AUTH_TOKEN, PUBLIC_VOICE_URL, list(params.items()))
    response = await client.post(
        "/twilio/voice",
        content=body,
        headers={
            **PROXY_HEADERS,
            "content-type": "application/x-www-form-urlencoded",
            "x-twilio-signature": signature,
        },
    )
    return response.status_code, response.text


CALL = {"CallSid": "CA123", "From": "client:dashboard-1", "To": "", "AccountSid": "AC0"}


# --- Tokens ---


@pytest.mark.usefixtures("twilio_settings")
async def test_a_signed_in_user_gets_an_outgoing_only_voice_token(client: AsyncClient) -> None:
    w = await build_world(client)
    for who in (w.owner_a, w.manager_a, w.staff_a):
        response = await client.post("/twilio/token", headers=who.headers)
        assert response.status_code == 200
        body = response.json()
        assert body["identity"] == f"dashboard-{who.user['id']}" and body["expires_in"] == 3600

        header = jwt.get_unverified_header(body["token"])
        assert header["cty"] == "twilio-fpa;v=1" and header["alg"] == "HS256"
        secret = "test-api-key-secret-32-characters"
        claims = jwt.decode(body["token"], secret, algorithms=["HS256"])
        assert claims["iss"] == "SK00000000000000000000000000000000"
        assert claims["sub"] == "AC00000000000000000000000000000000"
        assert claims["exp"] - claims["nbf"] == 3600
        assert claims["grants"] == {
            "identity": body["identity"],
            "voice": {"outgoing": {"application_sid": "AP00000000000000000000000000000000"}},
        }


async def test_tokens_need_a_signed_in_user_and_a_configured_server(client: AsyncClient) -> None:
    assert (await client.post("/twilio/token")).status_code == 401
    s = await salon(client)
    off = await client.post("/twilio/token", headers=s.owner.headers)
    assert (
        off.status_code == 503 and off.json()["error"]["code"] == "browser_calling_not_configured"
    )


# --- Where Twilio connects the call ---


@pytest.mark.usefixtures("twilio_settings")
async def test_the_call_goes_to_the_salon_line(client: AsyncClient) -> None:
    status, twiml = await twilio_posts(client, CALL)
    assert status == 200
    assert twiml == (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response><Dial answerOnBridge="true" callerId="+19787343798" timeLimit="900">'
        "<Number>+19787343798</Number></Dial></Response>"
    )


@pytest.mark.usefixtures("twilio_settings")
async def test_a_browser_cannot_choose_who_gets_called(client: AsyncClient) -> None:
    """Toll-fraud guard: anything the request asks for is ignored."""
    _, twiml = await twilio_posts(client, {**CALL, "To": "+923001234567", "Dial": "+447700900123"})
    assert "+923001234567" not in twiml and "+447700900123" not in twiml
    assert "<Number>+19787343798</Number>" in twiml


@pytest.mark.usefixtures("twilio_settings")
async def test_the_line_can_be_a_sip_address(client: AsyncClient) -> None:
    settings = get_settings()
    settings.twilio_dial_to = "sip:+19787343798@sip.retellai.com"
    settings.twilio_caller_id = "+19787343798"
    _, twiml = await twilio_posts(client, CALL)
    assert "<Sip>sip:+19787343798@sip.retellai.com</Sip>" in twiml
    assert 'callerId="+19787343798"' in twiml


@pytest.mark.usefixtures("twilio_settings")
@pytest.mark.parametrize("problem", ["missing", "wrong token", "tampered", "wrong url"])
async def test_only_twilio_can_ask(client: AsyncClient, problem: str) -> None:
    params = dict(CALL)
    body = urlencode(params)
    headers = {**PROXY_HEADERS, "content-type": "application/x-www-form-urlencoded"}
    if problem == "wrong token":
        headers["x-twilio-signature"] = expected_signature(
            "not-the-token", PUBLIC_VOICE_URL, list(params.items())
        )
    elif problem == "tampered":
        headers["x-twilio-signature"] = expected_signature(
            "test-auth-token", PUBLIC_VOICE_URL, list(params.items())
        )
        body = urlencode({**params, "From": "client:someone-else"})
    elif problem == "wrong url":
        headers["x-twilio-signature"] = expected_signature(
            "test-auth-token", "https://evil.example.com/twilio/voice", list(params.items())
        )
    response = await client.post("/twilio/voice", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"


async def test_the_webhook_is_off_until_configured(client: AsyncClient) -> None:
    status, _ = await twilio_posts(client, CALL)
    assert status == 503


def test_the_signature_matches_twilios_published_example() -> None:
    """The worked example from Twilio's webhook-security documentation."""
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    signature = expected_signature(
        "12345", "https://mycompany.com/myapp.php?foo=1&bar=2", list(params.items())
    )
    assert signature == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


# --- What the agent hears about the caller ---


@pytest.mark.usefixtures("retell_key")
async def test_a_call_presented_as_the_salon_line_has_no_customer_number(
    client: AsyncClient,
) -> None:
    """Browser calls reach Retell with the salon's own number as caller ID."""
    s = await salon(client)
    await client.patch(
        f"/locations/{s.location_id}", json={"phone": "+19787343798"}, headers=s.owner.headers
    )
    from_salon = call_object(to="+19787343798", from_="+19787343798")
    args = {
        "service_id": s.service["id"],
        "staff_id": s.staff["id"],
        "date": MONDAY,
        "time": "10:00",
        "customer_name": "Ayesha Khan",
    }
    result = await tool(client, "create_booking", args, call=from_salon)
    assert result["success"] is False and result["error"] == "need_phone"
    found = await tool(client, "find_my_bookings", call=from_salon)
    assert found["bookings"] == []
    booked = await tool(
        client, "create_booking", {**args, "phone": "0300 1234567"}, call=from_salon
    )
    assert booked["success"] is True
