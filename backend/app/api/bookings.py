"""Bookings and customers."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status

from app.api.deps import AnyPrincipal, ManagerPrincipal, SessionDep
from app.core.errors import error_responses
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.models.booking import AppointmentStatus, BookingSource
from app.schemas.booking import (
    BookingCreate,
    BookingOut,
    BookingUpdate,
    CustomerDetail,
    CustomerSummary,
    Reason,
)
from app.schemas.common import Page
from app.services import bookings as bookings_service

MAX_BOOKING_PAGE = 500

bookings_router = APIRouter(
    prefix="/bookings", tags=["bookings"], responses=error_responses(401, 403, 404)
)
customers_router = APIRouter(
    prefix="/customers", tags=["customers"], responses=error_responses(401, 403, 404)
)


@bookings_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a booking",
    description=(
        "Needs an `Idempotency-Key` header: repeating the same request with the same key returns "
        "the original booking (200) instead of booking twice. If the time was taken, the response "
        "is `409 slot_unavailable` with `details.alternatives`, the nearest free slots."
    ),
    responses={
        200: {"model": BookingOut, "description": "A retry: the booking already existed"},
        **error_responses(409, 422),
    },
)
async def create_booking(
    body: BookingCreate,
    response: Response,
    principal: AnyPrincipal,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
) -> BookingOut:
    booking, created = await bookings_service.create_booking(
        session, principal, body, idempotency_key=idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return booking


@bookings_router.get("", summary="Bookings the caller can see, soonest first")
async def list_bookings(
    principal: AnyPrincipal,
    session: SessionDep,
    location_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    status_filter: Annotated[AppointmentStatus | None, Query(alias="status")] = None,
    source: BookingSource | None = None,
    from_: Annotated[
        str | None, Query(alias="from", description="Date (in the salon's timezone) or timestamp")
    ] = None,
    to: Annotated[str | None, Query(description="Date (inclusive) or timestamp")] = None,
    q: Annotated[str | None, Query(description="Customer name, phone or booking reference")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BOOKING_PAGE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> Page[BookingOut]:
    items, next_cursor = await bookings_service.list_bookings(
        session,
        principal,
        location_id=location_id,
        staff_id=staff_id,
        status=status_filter,
        source=source,
        from_=from_,
        to=to,
        q=q,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=items, next_cursor=next_cursor)


@bookings_router.get("/{booking_id}", summary="One booking")
async def get_booking(
    booking_id: uuid.UUID, principal: AnyPrincipal, session: SessionDep
) -> BookingOut:
    return await bookings_service.get_booking(session, principal, booking_id)


@bookings_router.patch(
    "/{booking_id}",
    summary="Reschedule, edit notes, or record the outcome",
    description=(
        "Set `starts_at` and/or `staff_id` to reschedule (the new time must be genuinely free). "
        "Inside the cancellation window this needs a manager and `?force=true`. "
        "`status: completed | no_show` records how the visit went (managers only)."
    ),
    responses=error_responses(409, 422),
)
async def update_booking(
    booking_id: uuid.UUID,
    body: BookingUpdate,
    principal: AnyPrincipal,
    session: SessionDep,
    force: bool = False,
) -> BookingOut:
    return await bookings_service.update_booking(session, principal, booking_id, body, force=force)


@bookings_router.delete(
    "/{booking_id}",
    summary="Cancel a booking",
    description=(
        "Frees the time immediately. Inside the cancellation window this returns "
        "`409 cancellation_window_passed` unless a manager adds `?force=true`."
    ),
    responses=error_responses(409),
)
async def cancel_booking(
    booking_id: uuid.UUID,
    principal: AnyPrincipal,
    session: SessionDep,
    force: bool = False,
    reason: Annotated[Reason | None, Query()] = None,
) -> BookingOut:
    return await bookings_service.cancel_booking(
        session, principal, booking_id, force=force, reason=reason
    )


# --- Customers (owners and managers) ---


@customers_router.get("", summary="Customers (owner: all; manager: those of their location)")
async def list_customers(
    principal: ManagerPrincipal,
    session: SessionDep,
    q: Annotated[str | None, Query(description="Name or phone")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> Page[CustomerSummary]:
    items, next_cursor = await bookings_service.list_customers(
        session, principal, q=q, limit=limit, cursor=cursor
    )
    return Page(items=items, next_cursor=next_cursor)


@customers_router.get("/{customer_id}", summary="A customer and their appointment history")
async def get_customer(
    customer_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep
) -> CustomerDetail:
    return await bookings_service.get_customer(session, principal, customer_id)
