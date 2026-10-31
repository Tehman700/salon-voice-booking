"""Services, staff, schedules and availability."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import AnyPrincipal, ManagerPrincipal, SessionDep
from app.core.errors import error_responses
from app.schemas.catalog import (
    AvailabilityRequest,
    AvailabilityResponse,
    ClosureCreate,
    ClosureOut,
    HoursBlock,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
    StaffCreate,
    StaffOut,
    StaffUpdate,
    TimeOffCreate,
    TimeOffOut,
)
from app.schemas.common import Page
from app.services import availability as availability_service
from app.services import catalog as catalog_service
from app.services import scheduling, staffing

services_router = APIRouter(
    prefix="/services", tags=["services"], responses=error_responses(401, 403, 404)
)
staff_router = APIRouter(prefix="/staff", tags=["staff"], responses=error_responses(401, 403, 404))
schedule_router = APIRouter(
    prefix="/locations/{location_id}", tags=["schedules"], responses=error_responses(401, 403, 404)
)
availability_router = APIRouter(tags=["availability"], responses=error_responses(401, 403, 404))


# --- Services ---


@services_router.get("", summary="The service catalog")
async def list_services(principal: AnyPrincipal, session: SessionDep) -> Page[ServiceOut]:
    return Page(items=await catalog_service.list_services(session, principal))


@services_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Add a service (owner or manager)",
    responses=error_responses(409, 422),
)
async def create_service(
    body: ServiceCreate, principal: ManagerPrincipal, session: SessionDep
) -> ServiceOut:
    return await catalog_service.create_service(session, principal, body)


@services_router.patch(
    "/{service_id}",
    summary="Update a service (owner or manager)",
    description="Managers can change per-location overrides only for their own location.",
    responses=error_responses(409, 422),
)
async def update_service(
    service_id: uuid.UUID, body: ServiceUpdate, principal: ManagerPrincipal, session: SessionDep
) -> ServiceOut:
    return await catalog_service.update_service(session, principal, service_id, body)


@services_router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a service (owner or manager)",
    description="Services are never deleted, because past appointments refer to them.",
)
async def deactivate_service(
    service_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> Response:
    await catalog_service.deactivate_service(session, principal, service_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Staff ---


@staff_router.get("", summary="Staff the caller can see (optionally one location)")
async def list_staff(
    principal: AnyPrincipal, session: SessionDep, location_id: uuid.UUID | None = None
) -> Page[StaffOut]:
    return Page(items=await staffing.list_staff(session, principal, location_id))


@staff_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Add a staff member (owner, or a manager of that location)",
    description="Their working hours start as a copy of the location's opening hours.",
    responses=error_responses(409, 422),
)
async def create_staff(
    body: StaffCreate, principal: ManagerPrincipal, session: SessionDep
) -> StaffOut:
    return await staffing.create_staff(session, principal, body)


@staff_router.patch(
    "/{staff_id}",
    summary="Update a staff member",
    description="`service_ids`, if present, replaces the list. Only an owner can move staff.",
    responses=error_responses(409, 422),
)
async def update_staff(
    staff_id: uuid.UUID, body: StaffUpdate, principal: ManagerPrincipal, session: SessionDep
) -> StaffOut:
    return await staffing.update_staff(session, principal, staff_id, body)


@staff_router.delete(
    "/{staff_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a staff member",
    description="Staff are never deleted, because past appointments refer to them.",
)
async def deactivate_staff(
    staff_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> Response:
    await staffing.deactivate_staff(session, principal, staff_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.get("/{staff_id}/hours", summary="Weekly working hours (local time)")
async def get_staff_hours(
    staff_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> list[HoursBlock]:
    return await staffing.get_hours(session, principal, staff_id)


@staff_router.put(
    "/{staff_id}/hours",
    summary="Replace the weekly working hours",
    description="A day may have several blocks (split shifts); blocks of one day can't overlap.",
    responses=error_responses(422),
)
async def put_staff_hours(
    staff_id: uuid.UUID,
    body: list[HoursBlock],
    principal: ManagerPrincipal,
    session: SessionDep,
) -> list[HoursBlock]:
    return await staffing.set_hours(session, principal, staff_id, body)


@staff_router.get("/{staff_id}/time-off", summary="Time off, soonest first")
async def list_time_off(
    staff_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> list[TimeOffOut]:
    return await staffing.list_time_off(session, principal, staff_id)


@staff_router.post(
    "/{staff_id}/time-off",
    status_code=status.HTTP_201_CREATED,
    summary="Add time off",
    responses=error_responses(422),
)
async def add_time_off(
    staff_id: uuid.UUID, body: TimeOffCreate, principal: ManagerPrincipal, session: SessionDep
) -> TimeOffOut:
    return await staffing.add_time_off(session, principal, staff_id, body)


@staff_router.delete(
    "/{staff_id}/time-off/{time_off_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove time off",
)
async def remove_time_off(
    staff_id: uuid.UUID, time_off_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> Response:
    await staffing.remove_time_off(session, principal, staff_id, time_off_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Location opening hours and closures ---


@schedule_router.get("/hours", summary="Opening hours of a location (local time)")
async def get_location_hours(
    location_id: uuid.UUID, principal: AnyPrincipal, session: SessionDep
) -> list[HoursBlock]:
    return await scheduling.get_location_hours(session, principal, location_id)


@schedule_router.put(
    "/hours",
    summary="Replace a location's opening hours (owner, or a manager of it)",
    description="A weekday with no block is closed.",
    responses=error_responses(422),
)
async def put_location_hours(
    location_id: uuid.UUID,
    body: list[HoursBlock],
    principal: ManagerPrincipal,
    session: SessionDep,
) -> list[HoursBlock]:
    return await scheduling.set_location_hours(session, principal, location_id, body)


@schedule_router.get("/closures", summary="Days the location is closed")
async def list_closures(
    location_id: uuid.UUID, principal: AnyPrincipal, session: SessionDep
) -> list[ClosureOut]:
    return await scheduling.list_closures(session, principal, location_id)


@schedule_router.post(
    "/closures",
    status_code=status.HTTP_201_CREATED,
    summary="Close the location for a whole day",
    responses=error_responses(409, 422),
)
async def add_closure(
    location_id: uuid.UUID, body: ClosureCreate, principal: ManagerPrincipal, session: SessionDep
) -> ClosureOut:
    return await scheduling.add_closure(session, principal, location_id, body)


@schedule_router.delete(
    "/closures/{closure_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Reopen a closed day"
)
async def remove_closure(
    location_id: uuid.UUID, closure_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> Response:
    await scheduling.remove_closure(session, principal, location_id, closure_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Availability ---


@availability_router.post(
    "/availability",
    summary="Free appointment times",
    description=(
        "Every start time on the given days (location-local dates, at most 31) when the service "
        "fits, for one staff member or any. Times are UTC instants."
    ),
    responses=error_responses(422),
)
async def find_availability(
    body: AvailabilityRequest, principal: AnyPrincipal, session: SessionDep
) -> AvailabilityResponse:
    return AvailabilityResponse(
        slots=await availability_service.find_slots(session, principal, body)
    )
