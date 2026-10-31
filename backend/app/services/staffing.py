"""Staff members: who they are, what they do, when they work, and time off."""

import uuid
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from app.core.principal import Principal
from app.models.catalog import Service
from app.models.schedule import LocationHours
from app.models.staff import Staff, StaffService, StaffTimeOff, StaffWorkingHours
from app.repositories.tenant import LocationRepository, StaffRepository, UserRepository
from app.schemas.catalog import (
    HoursBlock,
    StaffCreate,
    StaffOut,
    StaffUpdate,
    TimeOffCreate,
    TimeOffOut,
    format_hhmm,
    parse_hhmm,
)
from app.services.scheduling import validate_blocks


class UserAlreadyLinkedError(ConflictError):
    code = "user_already_linked"
    message = "That user is already linked to another staff member."


async def _service_ids(
    session: AsyncSession, staff_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    grouped: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if staff_ids:
        rows = await session.execute(
            select(StaffService.staff_id, StaffService.service_id).where(
                StaffService.staff_id.in_(staff_ids)
            )
        )
        for staff_id, service_id in rows:
            grouped[staff_id].append(service_id)
    return grouped


def _to_out(member: Staff, service_ids: list[uuid.UUID]) -> StaffOut:
    return StaffOut(
        id=member.id,
        location_id=member.location_id,
        user_id=member.user_id,
        full_name=member.full_name,
        title=member.title,
        color=member.color,
        service_ids=sorted(service_ids, key=str),
        is_active=member.is_active,
    )


async def _load(session: AsyncSession, member: Staff) -> StaffOut:
    return _to_out(member, (await _service_ids(session, [member.id])).get(member.id, []))


async def get_staff(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID, *, for_update: bool = False
) -> Staff:
    member = await StaffRepository(session, principal).get(staff_id, for_update=for_update)
    if member is None:
        raise NotFoundError
    return member


async def list_staff(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID | None
) -> list[StaffOut]:
    stmt = StaffRepository(session, principal).select().order_by(Staff.full_name, Staff.id)
    if location_id is not None:
        stmt = stmt.where(Staff.location_id == location_id)
    members = list(await session.scalars(stmt))
    services = await _service_ids(session, [m.id for m in members])
    return [_to_out(m, services.get(m.id, [])) for m in members]


async def _check_services_exist(
    session: AsyncSession, principal: Principal, service_ids: list[uuid.UUID]
) -> None:
    if not service_ids:
        return
    found = set(
        await session.scalars(
            select(Service.id).where(
                Service.business_id == principal.business_id, Service.id.in_(service_ids)
            )
        )
    )
    if found != set(service_ids):
        raise NotFoundError


async def _set_services(
    session: AsyncSession, principal: Principal, member: Staff, service_ids: list[uuid.UUID]
) -> None:
    await _check_services_exist(session, principal, service_ids)
    await session.execute(delete(StaffService).where(StaffService.staff_id == member.id))
    for service_id in service_ids:
        session.add(
            StaffService(
                business_id=principal.business_id, staff_id=member.id, service_id=service_id
            )
        )


async def _check_user_link(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID | None
) -> None:
    if user_id is not None and await UserRepository(session, principal).get(user_id) is None:
        raise NotFoundError


async def create_staff(session: AsyncSession, principal: Principal, body: StaffCreate) -> StaffOut:
    location = await LocationRepository(session, principal).get(body.location_id)
    if location is None:
        raise NotFoundError
    if not location.is_active:
        raise ValidationFailedError(details={"location_id": ["That location is deactivated"]})
    await _check_user_link(session, principal, body.user_id)

    member = Staff(
        business_id=principal.business_id,
        location_id=location.id,
        user_id=body.user_id,
        full_name=body.full_name,
        title=body.title,
        color=body.color,
        is_active=body.is_active,
    )
    session.add(member)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise UserAlreadyLinkedError from None
    await _set_services(session, principal, member, body.service_ids)

    # Start from the location's opening hours; the manager can then adjust this person's week.
    opening = await session.scalars(
        select(LocationHours).where(LocationHours.location_id == location.id)
    )
    for row in opening:
        session.add(
            StaffWorkingHours(
                business_id=principal.business_id,
                staff_id=member.id,
                weekday=row.weekday,
                start_time=row.opens_at,
                end_time=row.closes_at,
            )
        )
    await session.commit()
    return await _load(session, member)


async def update_staff(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID, body: StaffUpdate
) -> StaffOut:
    member = await get_staff(session, principal, staff_id, for_update=True)
    fields = body.model_fields_set

    if body.location_id is not None and body.location_id != member.location_id:
        if not principal.is_owner:
            raise ForbiddenError("Only an owner can move staff between locations.")
        target = await LocationRepository(session, principal).get(body.location_id)
        if target is None:
            raise NotFoundError
        if not target.is_active:
            raise ValidationFailedError(details={"location_id": ["That location is deactivated"]})
        member.location_id = target.id
    if body.full_name is not None:
        member.full_name = body.full_name
    if body.color is not None:
        member.color = body.color
    if body.is_active is not None:
        member.is_active = body.is_active
    if "title" in fields:
        member.title = body.title
    if "user_id" in fields:
        await _check_user_link(session, principal, body.user_id)
        member.user_id = body.user_id
    if body.service_ids is not None:
        await _set_services(session, principal, member, list(dict.fromkeys(body.service_ids)))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise UserAlreadyLinkedError from None
    return await _load(session, member)


async def deactivate_staff(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID
) -> None:
    """Staff are never deleted: past appointments refer to them. Deactivating stops new bookings."""
    member = await get_staff(session, principal, staff_id, for_update=True)
    if member.is_active:
        member.is_active = False
        await session.commit()


# --- Working hours ---


async def get_hours(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID
) -> list[HoursBlock]:
    await get_staff(session, principal, staff_id)
    rows = await session.scalars(
        select(StaffWorkingHours)
        .where(StaffWorkingHours.staff_id == staff_id)
        .order_by(StaffWorkingHours.weekday, StaffWorkingHours.start_time)
    )
    return [
        HoursBlock(weekday=r.weekday, start=format_hhmm(r.start_time), end=format_hhmm(r.end_time))
        for r in rows
    ]


async def set_hours(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID, blocks: list[HoursBlock]
) -> list[HoursBlock]:
    await get_staff(session, principal, staff_id, for_update=True)
    ordered = validate_blocks(blocks)
    await session.execute(delete(StaffWorkingHours).where(StaffWorkingHours.staff_id == staff_id))
    for block in ordered:
        session.add(
            StaffWorkingHours(
                business_id=principal.business_id,
                staff_id=staff_id,
                weekday=block.weekday,
                start_time=parse_hhmm(block.start),
                end_time=parse_hhmm(block.end),
            )
        )
    await session.commit()
    return ordered


# --- Time off ---


def _time_off_out(row: StaffTimeOff) -> TimeOffOut:
    return TimeOffOut(
        id=row.id,
        staff_id=row.staff_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        reason=row.reason,
    )


async def list_time_off(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID
) -> list[TimeOffOut]:
    await get_staff(session, principal, staff_id)
    rows = await session.scalars(
        select(StaffTimeOff)
        .where(StaffTimeOff.staff_id == staff_id)
        .order_by(StaffTimeOff.starts_at)
    )
    return [_time_off_out(r) for r in rows]


async def add_time_off(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID, body: TimeOffCreate
) -> TimeOffOut:
    await get_staff(session, principal, staff_id)
    row = StaffTimeOff(
        business_id=principal.business_id,
        staff_id=staff_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        reason=body.reason,
    )
    session.add(row)
    await session.commit()
    return _time_off_out(row)


async def remove_time_off(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID, time_off_id: uuid.UUID
) -> None:
    await get_staff(session, principal, staff_id)
    result = await session.execute(
        delete(StaffTimeOff).where(
            StaffTimeOff.id == time_off_id, StaffTimeOff.staff_id == staff_id
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFoundError
    await session.commit()
