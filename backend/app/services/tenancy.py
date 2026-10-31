"""The current business and its locations."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.principal import Principal
from app.core.slug import randomized_slug, slugify, unique_slug
from app.db.locks import lock_business
from app.models.business import Business, LocationMode
from app.models.location import Location
from app.repositories.tenant import LocationRepository
from app.schemas.business import BusinessUpdate
from app.schemas.location import LocationInput, LocationUpdate

# Columns where an explicit null in a PATCH body means "clear it".
_NULLABLE_LOCATION_FIELDS = (
    "phone",
    "address_line1",
    "city",
    "country",
    "cancellation_window_minutes",
)


_MAX_SLUG_ATTEMPTS = 5


class LastActiveLocationError(ConflictError):
    code = "last_active_location"
    message = "A business must keep at least one active location."


async def get_business(session: AsyncSession, principal: Principal) -> Business:
    business = await session.get(Business, principal.business_id)
    if business is None:  # the token is valid but the business is gone
        raise NotFoundError
    return business


async def update_business(
    session: AsyncSession, principal: Principal, body: BusinessUpdate
) -> Business:
    business = await get_business(session, principal)
    if body.name is not None:
        business.name = body.name
    if body.default_timezone is not None:
        business.default_timezone = body.default_timezone
    if body.cancellation_window_minutes is not None:
        business.cancellation_window_minutes = body.cancellation_window_minutes
    await session.commit()
    return business


async def list_locations(session: AsyncSession, principal: Principal) -> list[Location]:
    stmt = (
        LocationRepository(session, principal).select().order_by(Location.created_at, Location.name)
    )
    return list(await session.scalars(stmt))


async def get_location(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID
) -> Location:
    location = await LocationRepository(session, principal).get(location_id)
    if location is None:
        raise NotFoundError
    return location


def _free_location_slug(name: str, taken: set[str], *, retry: bool) -> str:
    base = slugify(name)
    return randomized_slug(base) if retry else unique_slug(base, taken)


async def create_location(
    session: AsyncSession, principal: Principal, body: LocationInput
) -> Location:
    for attempt in range(_MAX_SLUG_ATTEMPTS):
        business = await get_business(session, principal)
        taken = set(
            await session.scalars(select(Location.slug).where(Location.business_id == business.id))
        )
        location = Location(
            business_id=business.id,
            slug=_free_location_slug(body.name, taken, retry=attempt > 0),
            **body.model_dump(),
        )
        session.add(location)
        # Adding another salon is what turns a single-salon business into a multi-salon one.
        business.location_mode = LocationMode.multiple
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent request took the same slug first; recompute it and try again.
            await session.rollback()
        else:
            return location
    raise ConflictError(
        "Could not create the location; please try again.", code="location_conflict"
    )


async def update_location(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID, body: LocationUpdate
) -> Location:
    if body.is_active is not None:
        await lock_business(session, principal.business_id)
    location = await LocationRepository(session, principal).get(location_id, for_update=True)
    if location is None:
        raise NotFoundError
    fields = body.model_fields_set

    if body.is_active is not None and body.is_active != location.is_active:
        if not principal.is_owner:
            raise ForbiddenError("Only an owner can activate or deactivate a location.")
        await _set_active(session, principal, location, body.is_active)
    if body.name is not None:
        location.name = body.name
    if body.timezone is not None:
        location.timezone = body.timezone
    for field in _NULLABLE_LOCATION_FIELDS:
        if field in fields:
            setattr(location, field, getattr(body, field))

    await session.commit()
    return location


async def deactivate_location(
    session: AsyncSession, principal: Principal, location_id: uuid.UUID
) -> None:
    await lock_business(session, principal.business_id)
    location = await LocationRepository(session, principal).get(location_id, for_update=True)
    if location is None:
        raise NotFoundError
    if location.is_active:
        await _set_active(session, principal, location, False)
        await session.commit()


async def _set_active(
    session: AsyncSession, principal: Principal, location: Location, active: bool
) -> None:
    if not active:
        # Safe to read without row locks: callers hold the business lock (see lock_business).
        active_ids = list(
            await session.scalars(
                select(Location.id).where(
                    Location.business_id == principal.business_id, Location.is_active.is_(True)
                )
            )
        )
        if all(location_id == location.id for location_id in active_ids):
            raise LastActiveLocationError
    location.is_active = active
