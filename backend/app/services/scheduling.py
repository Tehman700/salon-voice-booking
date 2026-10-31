"""Opening hours, working hours, closures and time off."""

import uuid
from datetime import time
from itertools import pairwise

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.principal import Principal
from app.models.location import Location
from app.models.schedule import LocationClosure, LocationHours
from app.repositories.tenant import LocationRepository
from app.schemas.catalog import (
    ClosureCreate,
    ClosureOut,
    HoursBlock,
    format_hhmm,
    parse_hhmm,
)

# New locations open Monday to Saturday, 10:00-19:00, until the owner changes it.
DEFAULT_OPEN = time(10, 0)
DEFAULT_CLOSE = time(19, 0)
DEFAULT_OPEN_WEEKDAYS = range(0, 6)


class ClosureExistsError(ConflictError):
    code = "closure_exists"
    message = "The location is already marked closed on that date."


def validate_blocks(blocks: list[HoursBlock], *, field: str = "blocks") -> list[HoursBlock]:
    """Blocks of one weekday must not overlap. Returns them sorted."""
    ordered = sorted(blocks, key=lambda b: (b.weekday, b.start))
    for earlier, later in pairwise(ordered):
        if earlier.weekday == later.weekday and later.start < earlier.end:
            raise ValidationFailedError(
                details={field: [f"Overlapping hours on weekday {later.weekday}"]}
            )
    return ordered


def add_default_hours(
    session: AsyncSession, business_id: uuid.UUID, location_id: uuid.UUID
) -> None:
    for weekday in DEFAULT_OPEN_WEEKDAYS:
        session.add(
            LocationHours(
                business_id=business_id,
                location_id=location_id,
                weekday=weekday,
                opens_at=DEFAULT_OPEN,
                closes_at=DEFAULT_CLOSE,
            )
        )


async def _location(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID
) -> Location:
    location = await LocationRepository(session, principal).get(location_id)
    if location is None:
        raise NotFoundError
    return location


async def get_location_hours(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID
) -> list[HoursBlock]:
    await _location(session, principal, location_id)
    rows = await session.scalars(
        select(LocationHours)
        .where(LocationHours.location_id == location_id)
        .order_by(LocationHours.weekday, LocationHours.opens_at)
    )
    return [
        HoursBlock(weekday=r.weekday, start=format_hhmm(r.opens_at), end=format_hhmm(r.closes_at))
        for r in rows
    ]


async def set_location_hours(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID, blocks: list[HoursBlock]
) -> list[HoursBlock]:
    await _location(session, principal, location_id)
    ordered = validate_blocks(blocks)
    await session.execute(delete(LocationHours).where(LocationHours.location_id == location_id))
    for block in ordered:
        session.add(
            LocationHours(
                business_id=principal.business_id,
                location_id=location_id,
                weekday=block.weekday,
                opens_at=parse_hhmm(block.start),
                closes_at=parse_hhmm(block.end),
            )
        )
    await session.commit()
    return ordered


async def list_closures(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID
) -> list[ClosureOut]:
    await _location(session, principal, location_id)
    rows = await session.scalars(
        select(LocationClosure)
        .where(LocationClosure.location_id == location_id)
        .order_by(LocationClosure.closed_on)
    )
    return [ClosureOut(id=r.id, date=r.closed_on, reason=r.reason) for r in rows]


async def add_closure(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID, body: ClosureCreate
) -> ClosureOut:
    await _location(session, principal, location_id)
    closure = LocationClosure(
        business_id=principal.business_id,
        location_id=location_id,
        closed_on=body.date,
        reason=body.reason,
    )
    session.add(closure)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ClosureExistsError from None
    return ClosureOut(id=closure.id, date=closure.closed_on, reason=closure.reason)


async def remove_closure(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID, closure_id: uuid.UUID
) -> None:
    await _location(session, principal, location_id)
    result = await session.execute(
        delete(LocationClosure).where(
            LocationClosure.id == closure_id, LocationClosure.location_id == location_id
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFoundError
    await session.commit()
