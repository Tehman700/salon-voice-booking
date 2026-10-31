"""Reading the call log for the dashboard."""

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.principal import Principal
from app.models.business import Business
from app.models.call import CallLog, CallOutcome
from app.models.location import Location
from app.repositories.tenant import CallLogRepository
from app.schemas.call import CallOut, CallStats, DayCount


def _out(log: CallLog) -> CallOut:
    return CallOut(
        id=log.id,
        retell_call_id=log.retell_call_id,
        location_id=log.location_id,
        from_number=log.from_number,
        started_at=log.started_at,
        ended_at=log.ended_at,
        duration_seconds=log.duration_seconds,
        outcome=log.outcome,
        summary=log.summary,
        transcript=log.transcript,
        booking_id=log.booking_id,
    )


def _day_bounds(
    from_: date | None, to: date | None, tz: ZoneInfo
) -> tuple[datetime | None, datetime | None]:
    """Whole local days: from the start of `from_` up to (not including) the day after `to`."""
    if from_ and to and to < from_:
        raise ValidationFailedError(details={"to": ["to must not be before from"]})
    start = datetime.combine(from_, dtime(0), tzinfo=tz).astimezone(UTC) if from_ else None
    end = (
        datetime.combine(to + timedelta(days=1), dtime(0), tzinfo=tz).astimezone(UTC)
        if to
        else None
    )
    return start, end


async def _business_tz(session: AsyncSession, principal: Principal) -> ZoneInfo:
    business = await session.get(Business, principal.business_id)
    return ZoneInfo(business.default_timezone if business else "UTC")


def _filtered(
    session: AsyncSession,
    principal: Principal,
    *,
    location_id: uuid.UUID | None,
    outcome: CallOutcome | None,
    start: datetime | None,
    end: datetime | None,
) -> Select[Any]:
    stmt: Select[Any] = CallLogRepository(session, principal).select()
    if location_id:
        stmt = stmt.where(CallLog.location_id == location_id)
    if outcome:
        stmt = stmt.where(CallLog.outcome == outcome)
    if start:
        stmt = stmt.where(CallLog.started_at >= start)
    if end:
        stmt = stmt.where(CallLog.started_at < end)
    return stmt


async def list_calls(
    session: AsyncSession,
    principal: Principal,
    *,
    location_id: uuid.UUID | None,
    outcome: CallOutcome | None,
    from_: date | None,
    to: date | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[CallOut], str | None]:
    start, end = _day_bounds(from_, to, await _business_tz(session, principal))
    stmt = _filtered(
        session, principal, location_id=location_id, outcome=outcome, start=start, end=end
    )
    if cursor:
        after_time, after_id = decode_cursor(cursor)
        # Newest first, so "after" the cursor means older.
        stmt = stmt.where(tuple_(CallLog.started_at, CallLog.id) < tuple_(after_time, after_id))
    rows = list(
        await session.scalars(
            stmt.order_by(CallLog.started_at.desc(), CallLog.id.desc()).limit(limit + 1)
        )
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].started_at, rows[-1].id)
    return [_out(r) for r in rows], next_cursor


async def get_call(session: AsyncSession, principal: Principal, call_id: uuid.UUID) -> CallOut:
    log = await CallLogRepository(session, principal).get(call_id)
    if log is None:
        raise NotFoundError
    return _out(log)


async def call_stats(
    session: AsyncSession,
    principal: Principal,
    *,
    location_id: uuid.UUID | None,
    from_: date | None,
    to: date | None,
) -> CallStats:
    default_tz = await _business_tz(session, principal)
    start, end = _day_bounds(from_, to, default_tz)
    stmt = _filtered(
        session, principal, location_id=location_id, outcome=None, start=start, end=end
    )
    rows = (
        await session.execute(
            stmt.with_only_columns(CallLog.started_at, CallLog.outcome, CallLog.location_id)
        )
    ).all()
    zones = {
        loc_id: ZoneInfo(tz)
        for loc_id, tz in await session.execute(
            select(Location.id, Location.timezone).where(
                Location.business_id == principal.business_id
            )
        )
    }
    by_outcome: Counter[CallOutcome] = Counter({o: 0 for o in CallOutcome})
    per_day: Counter[date] = Counter()
    for started_at, outcome, loc in rows:
        by_outcome[outcome] += 1
        per_day[started_at.astimezone(zones.get(loc, default_tz)).date()] += 1
    return CallStats(
        total=len(rows),
        by_outcome=dict(by_outcome),
        per_day=[DayCount(date=d, count=c) for d, c in sorted(per_day.items())],
    )
