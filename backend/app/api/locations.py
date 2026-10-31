import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import AnyPrincipal, ManagerPrincipal, OwnerPrincipal, SessionDep
from app.core.errors import error_responses
from app.schemas.common import Page
from app.schemas.location import LocationInput, LocationOut, LocationUpdate
from app.services import tenancy

router = APIRouter(
    prefix="/locations", tags=["locations"], responses=error_responses(401, 403, 404)
)


@router.get("", summary="Locations the caller can access")
async def list_locations(principal: AnyPrincipal, session: SessionDep) -> Page[LocationOut]:
    business = await tenancy.get_business(session, principal)
    locations = await tenancy.list_locations(session, principal)
    return Page(items=[LocationOut.build(loc, business) for loc in locations])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Add a location (owner)",
    description="Adding a second location switches the business to `location_mode: multiple`.",
    responses=error_responses(409, 422),
)
async def create_location(
    body: LocationInput, principal: OwnerPrincipal, session: SessionDep
) -> LocationOut:
    location = await tenancy.create_location(session, principal, body)
    return LocationOut.build(location, await tenancy.get_business(session, principal))


@router.get("/{location_id}", summary="One location (owner, or a manager of it)")
async def get_location(
    location_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> LocationOut:
    location = await tenancy.get_location(session, principal, location_id)
    return LocationOut.build(location, await tenancy.get_business(session, principal))


@router.patch(
    "/{location_id}",
    summary="Update a location (owner, or a manager of it)",
    description="Only an owner may change `is_active`. `cancellation_window_minutes: null` "
    "makes the location inherit the business default.",
    responses=error_responses(409, 422),
)
async def update_location(
    location_id: uuid.UUID, body: LocationUpdate, principal: ManagerPrincipal, session: SessionDep
) -> LocationOut:
    location = await tenancy.update_location(session, principal, location_id, body)
    return LocationOut.build(location, await tenancy.get_business(session, principal))


@router.delete(
    "/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a location (owner)",
    description="Soft delete. The last active location cannot be deactivated.",
    responses=error_responses(409),
)
async def deactivate_location(
    location_id: uuid.UUID, principal: OwnerPrincipal, session: SessionDep
) -> Response:
    await tenancy.deactivate_location(session, principal, location_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
