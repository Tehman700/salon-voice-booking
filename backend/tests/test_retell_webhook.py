"""Request signatures, and Retell's call events turning into call-log rows."""

import json
import time
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.retell import signature_is_valid, signature_problem
from tests.booking_helpers import MONDAY, salon
from tests.retell_helpers import API_KEY, CALLER, call_object, sign, signed, tool, webhook

NOW_MS = 1_900_000_000_000  # an arbitrary instant, in unix milliseconds
START_MS = NOW_MS
END_MS = NOW_MS + 95_000


# --- Signatures ---


def test_a_correct_signature_is_accepted() -> None:
    body = b'{"hello": "world"}'
    header = sign(body, at_ms=NOW_MS)
    assert signature_is_valid(body, header, API_KEY, max_age_seconds=300, now=NOW_MS / 1000)


@pytest.mark.parametrize(
    "tamper",
    ["body", "key", "stale", "future", "missing", "garbage", "empty"],
)
def test_bad_signatures_are_refused(tamper: str) -> None:
    body = b'{"hello": "world"}'
    now = NOW_MS / 1000
    header = sign(body, at_ms=NOW_MS)
    if tamper == "body":
        body = b'{"hello": "mallory"}'
    elif tamper == "key":
        header = sign(body, key="another-key", at_ms=NOW_MS)
    elif tamper == "stale":
        header = sign(body, at_ms=NOW_MS - 10 * 60 * 1000)
    elif tamper == "future":
        header = sign(body, at_ms=NOW_MS + 10 * 60 * 1000)
    elif tamper == "missing":
        header = ""
    elif tamper == "garbage":
        header = "v=abc,d=zzz"
    else:
        header = "v=,d="
    assert not signature_is_valid(body, header or None, API_KEY, max_age_seconds=300, now=now)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "no signature header"),
        ("v=1,d=00", "away from now"),
        (sign(b"{}", key="other", at_ms=NOW_MS), "digest does not match"),
        ("nonsense", "unrecognised signature format (8 characters)"),
    ],
)
def test_the_refusal_reason_says_what_is_wrong_without_leaking_secrets(
    header: str | None, expected: str
) -> None:
    reason = signature_problem(b"{}", header, API_KEY, max_age_seconds=300, now=NOW_MS / 1000)
    assert reason is not None and expected in reason
    assert API_KEY not in reason


def test_the_older_unversioned_signature_is_still_understood() -> None:
    import hashlib
    import hmac

    body = b"{}"
    legacy = hmac.new(API_KEY.encode(), body, hashlib.sha256).hexdigest()
    assert signature_is_valid(body, legacy, API_KEY, max_age_seconds=300)
    assert not signature_is_valid(body, legacy[:-1] + "0", API_KEY, max_age_seconds=300)


@pytest.mark.usefixtures("retell_key")
@pytest.mark.parametrize("path", ["/retell/functions/get_salon_info", "/webhooks/retell"])
async def test_unsigned_or_wrongly_signed_requests_are_refused(
    client: AsyncClient, path: str
) -> None:
    await salon(client)
    payload = {"event": "call_started", "name": "get_salon_info", "args": {}, "call": call_object()}
    body = json.dumps(payload).encode()
    for headers in (
        {},
        {"x-retell-signature": "v=1,d=00"},
        {"x-retell-signature": sign(body, key="not-our-key")},
        {"x-retell-signature": sign(body, at_ms=int(time.time() * 1000) - 3_600_000)},
    ):
        response = await client.post(
            path, content=body, headers={"content-type": "application/json", **headers}
        )
        assert response.status_code == 401, headers
        assert response.json()["error"]["code"] == "invalid_signature"
    assert (await client.get("/calls", headers=(await _owner(client)).headers)).json()[
        "items"
    ] == []


async def _owner(client: AsyncClient) -> Any:
    from tests.helpers import login

    return await login(client, "owner@glow.example.com")


@pytest.mark.parametrize("path", ["/retell/functions/get_salon_info", "/webhooks/retell"])
async def test_without_a_configured_key_voice_endpoints_are_off(
    client: AsyncClient, path: str
) -> None:
    assert get_settings().retell_api_key is None
    body, headers = signed({"call": call_object(), "event": "call_started"})
    response = await client.post(path, content=body, headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "voice_not_configured"


@pytest.mark.usefixtures("retell_key")
async def test_a_signed_but_malformed_body_is_a_validation_error(client: AsyncClient) -> None:
    body, headers = signed({"name": "get_salon_info", "args": {}})  # no "call"
    response = await client.post("/retell/functions/get_salon_info", content=body, headers=headers)
    assert response.status_code == 422
    response = await client.post(
        "/webhooks/retell", content=b"not json", headers={"x-retell-signature": sign(b"not json")}
    )
    assert response.status_code == 422


# --- Events ---


@pytest.mark.usefixtures("retell_key")
class TestEvents:
    async def calls(self, client: AsyncClient) -> list[dict[str, Any]]:
        owner = await _owner(client)
        return list((await client.get("/calls", headers=owner.headers)).json()["items"])

    async def test_a_call_is_logged_from_start_to_finish(self, client: AsyncClient) -> None:
        await salon(client)
        call = call_object("call_abc", start_timestamp=START_MS)
        started = await webhook(client, "call_started", call)
        assert started.status_code == 200 and started.json() == {"status": "recorded"}
        [log] = await self.calls(client)
        assert log["retell_call_id"] == "call_abc" and log["from_number"] == CALLER
        assert log["ended_at"] is None and log["outcome"] == "info_only"

        ended = {
            **call,
            "end_timestamp": END_MS,
            "disconnection_reason": "user_hangup",
            "transcript_object": [
                {"role": "agent", "content": "Hello, Glow Salon."},
                {"role": "user", "content": "What time do you open?"},
                {"role": "agent", "content": "  "},  # blank turns are dropped
            ],
        }
        await webhook(client, "call_ended", ended)
        analysed = {**ended, "call_analysis": {"call_summary": "Asked about opening hours."}}
        await webhook(client, "call_analyzed", analysed)

        [log] = await self.calls(client)
        assert log["duration_seconds"] == 95 and log["ended_at"] is not None
        assert log["summary"] == "Asked about opening hours."
        assert log["transcript"] == [
            {"role": "agent", "text": "Hello, Glow Salon."},
            {"role": "user", "text": "What time do you open?"},
        ]
        assert log["outcome"] == "info_only"  # they talked, nothing was booked

    async def test_repeated_and_out_of_order_events_leave_one_row(
        self, client: AsyncClient
    ) -> None:
        await salon(client)
        call = call_object("call_dup", start_timestamp=START_MS, end_timestamp=END_MS)
        for event in ("call_ended", "call_started", "call_ended", "call_analyzed", "call_started"):
            assert (await webhook(client, event, call)).status_code == 200
        assert len(await self.calls(client)) == 1

    async def test_booking_during_a_call_is_linked_and_survives_the_end_event(
        self, client: AsyncClient
    ) -> None:
        s = await salon(client)
        call = call_object("call_book", start_timestamp=START_MS)
        await webhook(client, "call_started", call)
        made = await tool(
            client,
            "create_booking",
            {
                "service_id": s.service["id"],
                "staff_id": s.staff["id"],
                "date": MONDAY,
                "time": "10:00",
                "customer_name": "Ayesha Khan",
            },
            call=call,
        )
        assert made["success"] is True
        await webhook(client, "call_ended", {**call, "end_timestamp": END_MS})
        [log] = await self.calls(client)
        assert log["outcome"] == "booked" and log["booking_id"] is not None
        assert len(await self.calls(client)) == 1  # the tool and the webhook share one row

    async def test_a_call_where_nobody_spoke_is_abandoned(self, client: AsyncClient) -> None:
        await salon(client)
        call = call_object(
            "call_silent",
            start_timestamp=START_MS,
            end_timestamp=END_MS,
            transcript_object=[{"role": "agent", "content": "Hello?"}],
        )
        await webhook(client, "call_ended", call)
        assert (await self.calls(client))[0]["outcome"] == "abandoned"

    async def test_a_location_in_the_webhook_url_routes_the_call(self, client: AsyncClient) -> None:
        s = await salon(client)
        call = call_object("call_pinned", to=None, start_timestamp=START_MS)
        assert (await webhook(client, "call_started", call)).json() == {"status": "unrouted"}
        pinned = await webhook(client, "call_started", call, location_id=s.location_id)
        assert pinned.json() == {"status": "recorded"}
        assert [c["retell_call_id"] for c in await self.calls(client)] == ["call_pinned"]

    async def test_a_technical_failure_is_marked_failed(self, client: AsyncClient) -> None:
        await salon(client)
        call = call_object(
            "call_broken",
            start_timestamp=START_MS,
            end_timestamp=END_MS,
            disconnection_reason="error_llm_websocket_open",
        )
        await webhook(client, "call_ended", call)
        assert (await self.calls(client))[0]["outcome"] == "failed"

    async def test_events_we_do_not_use_and_calls_we_cannot_route_are_acknowledged(
        self, client: AsyncClient
    ) -> None:
        await salon(client)
        other = await webhook(client, "transcript_updated", call_object("call_x"))
        assert other.status_code == 200 and other.json() == {"status": "ignored"}
        lost = await webhook(client, "call_started", call_object("call_y", to="+14155550123"))
        assert lost.status_code == 200 and lost.json() == {"status": "unrouted"}
        assert await self.calls(client) == []
