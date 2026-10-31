"""The service catalog: what a business sells, plus per-location price/duration overrides."""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.principal import Principal
from app.models.catalog import LocationService, Service
from app.models.location import Location
from app.repositories.tenant import ServiceRepository
from app.schemas.catalog import (
    LocationOverrideIn,
    LocationOverrideOut,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
)


class ServiceNameTakenError(ConflictError):
    code = "service_name_taken"
    message = "You already have a service with that name."


async def _overrides_by_service(
    session: AsyncSession, service_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[LocationService]]:
    grouped: dict[uuid.UUID, list[LocationService]] = defaultdict(list)
    if service_ids:
        rows = await session.scalars(
            select(LocationService)
            .where(LocationService.service_id.in_(service_ids))
            .order_by(LocationService.location_id)
        )
        for row in rows:
            grouped[row.service_id].append(row)
    return grouped


def _to_out(service: Service, overrides: list[LocationService]) -> ServiceOut:
    return ServiceOut(
        id=service.id,
        name=service.name,
        description=service.description,
        category=service.category,
        duration_minutes=service.duration_minutes,
        buffer_minutes=service.buffer_minutes,
        price_minor=service.price_minor,
        currency=service.currency,
        is_active=service.is_active,
        location_overrides=[LocationOverrideOut.model_validate(o) for o in overrides],
    )


async def _load(session: AsyncSession, service: Service) -> ServiceOut:
    overrides = await _overrides_by_service(session, [service.id])
    return _to_out(service, overrides.get(service.id, []))


async def list_services(session: AsyncSession, principal: Principal) -> list[ServiceOut]:
    stmt = ServiceRepository(session, principal).select().order_by(Service.name)
    services = list(await session.scalars(stmt))
    overrides = await _overrides_by_service(session, [s.id for s in services])
    return [_to_out(s, overrides.get(s.id, [])) for s in services]


async def get_service(
    session: AsyncSession, principal: Principal, service_id: uuid.UUID, *, for_update: bool = False
) -> Service:
    service = await ServiceRepository(session, principal).get(service_id, for_update=for_update)
    if service is None:
        raise NotFoundError
    return service


async def _apply_overrides(
    session: AsyncSession,
    principal: Principal,
    service: Service,
    provided: list[LocationOverrideIn],
) -> None:
    """Make the caller's editable locations match `provided`.

    Owners edit every location of the business. Managers edit only their own: rows for other
    locations are left untouched, so a manager saving the full form can't wipe or change them.
    """
    business_locations = set(
        await session.scalars(
            select(Location.id).where(Location.business_id == principal.business_id)
        )
    )
    if principal.is_owner:
        editable = business_locations
        if any(o.location_id not in business_locations for o in provided):
            raise NotFoundError
    else:
        editable = {principal.location_id} if principal.location_id else set()

    wanted = {
        o.location_id: o
        for o in provided
        if o.location_id in editable
        # A row that changes nothing isn't worth storing.
        and (o.price_minor is not None or o.duration_minutes is not None or not o.is_offered)
    }
    existing = {
        row.location_id: row
        for row in await session.scalars(
            select(LocationService).where(LocationService.service_id == service.id)
        )
    }
    for location_id in editable:
        row, new = existing.get(location_id), wanted.get(location_id)
        if new is None:
            if row is not None:
                await session.delete(row)
        elif row is None:
            session.add(
                LocationService(
                    business_id=principal.business_id,
                    location_id=location_id,
                    service_id=service.id,
                    price_minor=new.price_minor,
                    duration_minutes=new.duration_minutes,
                    is_offered=new.is_offered,
                )
            )
        else:
            row.price_minor = new.price_minor
            row.duration_minutes = new.duration_minutes
            row.is_offered = new.is_offered


async def create_service(
    session: AsyncSession, principal: Principal, body: ServiceCreate
) -> ServiceOut:
    service = Service(
        business_id=principal.business_id, **body.model_dump(exclude={"location_overrides"})
    )
    session.add(service)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ServiceNameTakenError from None
    await _apply_overrides(session, principal, service, body.location_overrides)
    await session.commit()
    return await _load(session, service)


async def update_service(
    session: AsyncSession, principal: Principal, service_id: uuid.UUID, body: ServiceUpdate
) -> ServiceOut:
    service = await get_service(session, principal, service_id, for_update=True)
    fields = body.model_fields_set
    for name in (
        "name",
        "duration_minutes",
        "buffer_minutes",
        "price_minor",
        "currency",
        "is_active",
    ):
        value = getattr(body, name)
        if value is not None:
            setattr(service, name, value)
    for name in ("description", "category"):  # nullable: an explicit null clears them
        if name in fields:
            setattr(service, name, getattr(body, name))
    if body.location_overrides is not None:
        await _apply_overrides(session, principal, service, body.location_overrides)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ServiceNameTakenError from None
    return await _load(session, service)


async def deactivate_service(
    session: AsyncSession, principal: Principal, service_id: uuid.UUID
) -> None:
    """Services are never deleted: past appointments refer to them. Deactivating hides them."""
    service = await get_service(session, principal, service_id, for_update=True)
    if service.is_active:
        service.is_active = False
        await session.commit()
