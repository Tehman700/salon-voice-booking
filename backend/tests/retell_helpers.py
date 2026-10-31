"""Helpers for the voice-agent tests: signed requests, in Retell's format."""

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from httpx import AsyncClient, Response

API_KEY = "test-retell-api-key"  # same value as the retell_key fixture in conftest.py
SALON_NUMBER = "+923001234567"  # the number every test salon is created with
CALLER = "+923335550101"


def sign(body: bytes, *, key: str = API_KEY, at_ms: int | None = None) -> str:
    stamp = str(at_ms if at_ms is not None else int(time.time() * 1000))
    digest = hmac.new(key.encode(), body + stamp.encode(), hashlib.sha256).hexdigest()
    return f"v={stamp},d={digest}"


def signed(payload: dict[str, Any], **kw: Any) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    return body, {"content-type": "application/json", "x-retell-signature": sign(body, **kw)}


def call_object(
    call_id: str | None = None,
    *,
    to: str | None = SALON_NUMBER,
    from_: str | None = CALLER,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "call_id": call_id or f"call_{uuid.uuid4().hex[:16]}",
        "from_number": from_,
        "to_number": to,
        **extra,
    }


async def tool(
    client: AsyncClient,
    name: str,
    args: dict[str, Any] | None = None,
    *,
    call: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a tool the way Retell does and return the JSON the agent would hear."""
    body, headers = signed({"name": name, "args": args or {}, "call": call or call_object()})
    response = await client.post(f"/retell/functions/{name}", content=body, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def webhook(client: AsyncClient, event: str, call: dict[str, Any]) -> Response:
    body, headers = signed({"event": event, "call": call})
    return await client.post("/webhooks/retell", content=body, headers=headers)
