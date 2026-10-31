"""Find free appointment times: load what the engine needs, then ask it."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.availability import (
    Interval,
    LocationSchedule,
    StaffSchedule,
    compute_slots,
    local_to_utc,
)
from app.core.errors import NotFoundError
from app.core.principal import Principal
from app.models.booking import Appointment, AppointmentStatus
from app.models.catalog import LocationService
from app.models.schedule import LocationClosure, LocationHours
from app.models.staff import Staff, StaffService, StaffTimeOff, StaffWorkingHours
from app.repositories.tenant import LocationRepository, ServiceRepository
from app.schemas.catalog import AvailabilityRequest, SlotOut


async def load_busy_intervals(
    session: AsyncSession,
    staff_ids: list[uuid.UUID],
    window_start: datetime,
    window_end: datetime,
    *,
    exclude_appointment_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, list[Interval]]:
    """Live appointments per staff member, each extended by its cleanup buffer.

    Matches the database rule that forbids overlapping appointments exactly: the range is
    [starts_at, blocked_until).
    """
    stmt = select(Appointment.staff_id, Appointment.starts_at, Appointment.blocked_until).where(
        Appointment.staff_id.in_(staff_ids),
        Appointment.status != AppointmentStatus.cancelled,
        Appointment.starts_at < window_end,
        Appointment.blocked_until > window_start,
    )
    if exclude_appointment_id is not None:
        stmt = stmt.where(Appointment.id != exclude_appointment_id)
    busy: dict[uuid.UUID, list[Interval]] = defaultdict(list)
    for staff_id, starts_at, blocked_until in await session.execute(stmt):
        busy[staff_id].append((starts_at, blocked_until))
    return busy


async def find_slots(
    session: AsyncSession,
    principal: Principal,
    request: AvailabilityRequest,
    *,
    now: datetime | None = None,
    exclude_appointment_id: uuid.UUID | None = None,
) -> list[SlotOut]:
    now = now or datetime.now(UTC)

    location = await LocationRepository(session, principal).get(request.location_id)
    service = await ServiceRepository(session, principal).get(request.service_id)
    if location is None or service is None:
        raise NotFoundError
    if not location.is_active or not service.is_active:
        return []

    override = await session.scalar(
        select(LocationService).where(
            LocationService.location_id == location.id, LocationService.service_id == service.id
        )
    )
    if override is not None and not override.is_offered:
        return []
    duration = (override.duration_minutes if override else None) or service.duration_minutes

    staff_stmt = (
        select(Staff)
        .join(StaffService, StaffService.staff_id == Staff.id)
        .where(
            Staff.business_id == principal.business_id,
            Staff.location_id == location.id,
            Staff.is_active.is_(True),
            StaffService.service_id == service.id,
        )
        .order_by(Staff.full_name, Staff.id)
    )
    if request.staff_id is not None:
        staff_stmt = staff_stmt.where(Staff.id == request.staff_id)
    members = list(await session.scalars(staff_stmt))
    if not members:
        # No one can do this here (or the requested person is unknown, inactive, at another
        # location or doesn't offer the service). We don't reveal which.
        return []

    tz = ZoneInfo(location.timezone)
    days = [
        request.date_from + timedelta(days=i)
        for i in range((request.date_to - request.date_from).days + 1)
    ]
    window_start = local_to_utc(days[0] - timedelta(days=1), dtime(0), tz) or now
    window_end = local_to_utc(days[-1] + timedelta(days=2), dtime(0), tz) or now
    staff_ids = [m.id for m in members]

    opening: dict[int, list[tuple[dtime, dtime]]] = defaultdict(list)
    for row in await session.scalars(
        select(LocationHours).where(LocationHours.location_id == location.id)
    ):
        opening[row.weekday].append((row.opens_at, row.closes_at))

    closed = frozenset(
        await session.scalars(
            select(LocationClosure.closed_on).where(
                LocationClosure.location_id == location.id,
                LocationClosure.closed_on.between(days[0], days[-1]),
            )
        )
    )

    hours: dict[uuid.UUID, dict[int, list[tuple[dtime, dtime]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row2 in await session.scalars(
        select(StaffWorkingHours).where(StaffWorkingHours.staff_id.in_(staff_ids))
    ):
        hours[row2.staff_id][row2.weekday].append((row2.start_time, row2.end_time))

    time_off: dict[uuid.UUID, list[Interval]] = defaultdict(list)
    for off in await session.scalars(
        select(StaffTimeOff).where(
            StaffTimeOff.staff_id.in_(staff_ids),
            StaffTimeOff.starts_at < window_end,
            StaffTimeOff.ends_at > window_start,
        )
    ):
        time_off[off.staff_id].append((off.starts_at, off.ends_at))

    busy = await load_busy_intervals(
        session, staff_ids, window_start, window_end, exclude_appointment_id=exclude_appointment_id
    )

    results = compute_slots(
        location=LocationSchedule(timezone=tz, opening_hours=dict(opening), closed_dates=closed),
        staff=[
            StaffSchedule(
                staff_id=m.id,
                name=m.full_name,
                working_hours=dict(hours.get(m.id, {})),
                time_off=time_off.get(m.id, []),
                busy=busy.get(m.id, []),
            )
            for m in members
        ],
        days=days,
        duration_minutes=duration,
        buffer_minutes=service.buffer_minutes,
        now=now,
    )
    return [
        SlotOut(
            starts_at=r.starts_at, ends_at=r.ends_at, staff_id=r.staff_id, staff_name=r.staff_name
        )
        for r in results
    ]
