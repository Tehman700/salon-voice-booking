"""Retell's call events (started, ended, analysed) become rows in the call log.

Events can arrive late, twice, or out of order, so every one is applied as an idempotent update
of the same row. Anything that cannot be routed to a location is acknowledged and dropped:
answering with an error would only make Retell retry it forever.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import CallOutcome
from app.services.voice import RetellCall, get_or_create_call, resolve_place

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_TURNS = 2000
HANDLED_EVENTS = {"call_started", "call_ended", "call_analyzed"}


class WebhookCall(RetellCall):
    transcript_object: list[dict[str, Any]] | None = None
    disconnection_reason: str | None = None
    call_analysis: dict[str, Any] | None = None


class WebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: str
    call: WebhookCall = Field()


def _transcript(turns: list[dict[str, Any]] | None) -> list[dict[str, str]] | None:
    if turns is None:
        return None
    out = []
    for turn in turns[:MAX_TRANSCRIPT_TURNS]:
        role = "agent" if turn.get("role") == "agent" else "user"
        text = str(turn.get("content") or "").strip()
        if text:
            out.append({"role": role, "text": text})
    return out


def _moment(millis: int | None) -> datetime | None:
    return datetime.fromtimestamp(millis / 1000, UTC) if millis else None


async def apply_event(session: AsyncSession, event: WebhookEvent) -> str:
    """Returns what happened: "recorded", "ignored" (not an event we use) or "unrouted"."""
    if event.event not in HANDLED_EVENTS:
        return "ignored"
    call = event.call
    place = await resolve_place(session, call)
    if place is None:
        logger.warning("Retell call %s could not be routed to a location", call.call_id)
        return "unrouted"
    log, _ = await get_or_create_call(session, place, call)

    log.from_number = call.from_number or log.from_number
    log.to_number = call.to_number or log.to_number
    if started := _moment(call.start_timestamp):
        log.started_at = started

    if event.event in ("call_ended", "call_analyzed"):
        if ended := _moment(call.end_timestamp):
            log.ended_at = ended
            log.duration_seconds = max(0, round((ended - log.started_at).total_seconds()))
        if (turns := _transcript(call.transcript_object)) is not None:
            log.transcript = turns
        if call.disconnection_reason:
            log.disconnection_reason = call.disconnection_reason[:100]
        summary = (call.call_analysis or {}).get("call_summary")
        if summary:
            log.summary = str(summary)
        _settle_outcome(log)

    await session.commit()
    return "recorded"


def _settle_outcome(log: Any) -> None:
    """A call that did nothing is failed or abandoned; real outcomes are never overwritten."""
    if log.outcome != CallOutcome.info_only:
        return
    reason = (log.disconnection_reason or "").lower()
    if "error" in reason or "failed" in reason:
        log.outcome = CallOutcome.failed
    elif log.transcript is not None and not any(t["role"] == "user" for t in log.transcript):
        log.outcome = CallOutcome.abandoned
