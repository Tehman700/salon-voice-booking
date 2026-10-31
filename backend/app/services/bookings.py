"""Create, reschedule, cancel and look up bookings.

Two layers keep a time from being sold twice. First the availability engine checks the request
against hours, time off, closures and existing appointments, so a customer is only ever told about
genuinely free times. Then the database itself refuses any overlapping appointment for a staff
member (an exclusion constraint), so two requests racing for the same time cannot both succeed:
the loser gets `slot_unavailable` together with nearby alternatives.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_utils import InvalidPhoneError, new_reference, normalize_phone
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.core.pagination import decode_cursor, encode_cursor
from app.core.principal import Principal
from app.models.booking import (
    Appointment,
    AppointmentEvent,
    AppointmentStatus,
    BookingSource,
    Customer,
)
from app.models.business import Business
from app.models.catalog import LocationService, Service
from app.models.location import Location
from app.models.staff import Staff, StaffService
from app.models.user import Role
from app.repositories.tenant import (
    AppointmentRepository,
    LocationRepository,
    ServiceRepository,
    StaffRepository,
)
from app.schemas.booking import (
    BookingCreate,
    BookingOut,
    BookingUpdate,
    CustomerDetail,
    CustomerOut,
    CustomerSummary,
)
from app.schemas.catalog import AvailabilityRequest, SlotOut
from app.services.availability import find_slots

ALTERNATIVES_SHOWN = 5
MAX_REFERENCE_ATTEMPTS = 5


class SlotUnavailableError(ConflictError):
    code = "slot_unavailable"
    message = "That time is no longer available."


class CancellationWindowPassedError(ConflictError):
    code = "cancellation_window_passed"
    message = "It is too close to the appointment to change it."


class BookingNotActiveError(ConflictError):
    code = "booking_not_active"
    message = "This booking is no longer active."


class IdempotencyKeyReusedError(ConflictError):
    code = "idempotency_key_reused"
    message = "That Idempotency-Key was already used for a different request."


async def _lock_staff(session: AsyncSession, *staff_ids: uuid.UUID) -> None:
    """Queue behind other bookings for the same staff members until this transaction ends.

    Bookings for one stylist are decided one at a time: each request looks at availability only
    after the previous one has committed, so the answer it gets is the truth. Locks are taken in
    a fixed order so two requests can never wait on each other. The database's no-overlap rule
    still backs this up if anything ever bypasses it.
    """
    for staff_id in sorted(set(staff_ids), key=str):
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(str(staff_id), 0)))
        )


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(details={field: [message]})


# --- Reading ---


def _out(appointment: Appointment, customer: Customer) -> BookingOut:
    return BookingOut(
        id=appointment.id,
        reference=appointment.reference,
        location_id=appointment.location_id,
        service_id=appointment.service_id,
        staff_id=appointment.staff_id,
        customer=CustomerOut(
            id=customer.id,
            full_name=customer.full_name,
            phone=customer.phone,
            email=customer.email,
        ),
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status,
        source=appointment.source,
        call_id=appointment.call_id,
        price_minor=appointment.price_minor,
        currency=appointment.currency,
        notes=appointment.notes,
        created_at=appointment.created_at,
        cancelled_at=appointment.cancelled_at,
        cancellation_reason=appointment.cancellation_reason,
    )


def _scoped(session: AsyncSession, principal: Principal, stmt: Any) -> Any:
    """Bookings the caller may see: their business, their location, and (for staff) their own."""
    stmt = AppointmentRepository(session, principal).scope(stmt)
    if principal.role == Role.staff:
        mine = select(Staff.id).where(
            Staff.user_id == principal.user_id, Staff.business_id == principal.business_id
        )
        stmt = stmt.where(Appointment.staff_id.in_(mine))
    return stmt


def _booking_query() -> Any:
    return select(Appointment, Customer).join(
        Customer,
        (Customer.id == Appointment.customer_id)
        & (Customer.business_id == Appointment.business_id),
    )


async def _fetch(
    session: AsyncSession,
    principal: Principal,
    booking_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> tuple[Appointment, Customer]:
    stmt = _scoped(session, principal, _booking_query()).where(Appointment.id == booking_id)
    if for_update:
        stmt = stmt.with_for_update(of=Appointment)
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFoundError
    return row[0], row[1]


async def get_booking(
    session: AsyncSession, principal: Principal, booking_id: uuid.UUID
) -> BookingOut:
    appointment, customer = await _fetch(session, principal, booking_id)
    return _out(appointment, customer)


def _parse_bound(value: str, tz: ZoneInfo, *, upper: bool) -> tuple[datetime, bool]:
    """A plain date means that whole day in the salon's timezone; a timestamp is used as is.

    Returns (instant, inclusive). An upper date bound is the start of the next day, exclusive.
    """
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            if upper:
                day += timedelta(days=1)
            return datetime.combine(day, time(0), tzinfo=tz).astimezone(UTC), not upper
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _invalid(
            "from" if not upper else "to", "Use a date (2026-11-03) or a timestamp"
        ) from None
    if parsed.tzinfo is None:
        raise _invalid("from" if not upper else "to", "Include a timezone in timestamps")
    return parsed.astimezone(UTC), True


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def list_bookings(
    session: AsyncSession,
    principal: Principal,
    *,
    location_id: uuid.UUID | None,
    staff_id: uuid.UUID | None,
    status: AppointmentStatus | None,
    source: BookingSource | None,
    from_: str | None,
    to: str | None,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[BookingOut], str | None]:
    stmt = _scoped(session, principal, _booking_query())
    if location_id:
        stmt = stmt.where(Appointment.location_id == location_id)
    if staff_id:
        stmt = stmt.where(Appointment.staff_id == staff_id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    if source:
        stmt = stmt.where(Appointment.source == source)
    if from_ or to:
        business = await session.get(Business, principal.business_id)
        tz = ZoneInfo(business.default_timezone if business else "UTC")
        if from_:
            start, _ = _parse_bound(from_, tz, upper=False)
            stmt = stmt.where(Appointment.starts_at >= start)
        if to:
            end, inclusive = _parse_bound(to, tz, upper=True)
            stmt = stmt.where(
                Appointment.starts_at <= end if inclusive else Appointment.starts_at < end
            )
    if q and q.strip():
        term = q.strip()
        conditions = [
            Customer.full_name.ilike(_like(term), escape="\\"),
            Appointment.reference == term.upper(),
        ]
        digits = "".join(ch for ch in term if ch.isdigit()).lstrip("0")
        if len(digits) >= 4:
            conditions.append(Customer.phone.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conditions))
    if cursor:
        after_start, after_id = decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(Appointment.starts_at, Appointment.id) > tuple_(after_start, after_id)
        )

    rows = list(
        (
            await session.execute(
                stmt.order_by(Appointment.starts_at, Appointment.id).limit(limit + 1)
            )
        ).all()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1][0]
        next_cursor = encode_cursor(last.starts_at, last.id)
    return [_out(a, c) for a, c in rows], next_cursor


# --- Rules shared by create and reschedule ---


async def _event(
    session: AsyncSession,
    principal: Principal | None,
    appointment: Appointment,
    event_type: str,
    source: BookingSource,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        AppointmentEvent(
            business_id=appointment.business_id,
            appointment_id=appointment.id,
            event_type=event_type,
            source=source,
            actor_user_id=principal.user_id if principal else None,
            data=data,
        )
    )


async def _bookable(
    session: AsyncSession,
    principal: Principal,
    location_id: uuid.UUID,
    service_id: uuid.UUID,
    staff_id: uuid.UUID,
) -> tuple[Location, Service, Staff, LocationService | None]:
    """Look everything up (other businesses' ids are 404) and check this staff member can do it."""
    location = await LocationRepository(session, principal).get(location_id)
    service = await ServiceRepository(session, principal).get(service_id)
    member = await StaffRepository(session, principal).get(staff_id)
    if location is None or service is None or member is None:
        raise NotFoundError
    if not location.is_active:
        raise _invalid("location_id", "That location is deactivated")
    if not service.is_active:
        raise _invalid("service_id", "That service is not available")
    if not member.is_active or member.location_id != location.id:
        raise _invalid("staff_id", "That staff member is not available at this location")
    does_service = await session.scalar(
        select(StaffService.staff_id).where(
            StaffService.staff_id == member.id, StaffService.service_id == service.id
        )
    )
    if does_service is None:
        raise _invalid("staff_id", "That staff member does not offer this service")
    override = await session.scalar(
        select(LocationService).where(
            LocationService.location_id == location.id, LocationService.service_id == service.id
        )
    )
    if override is not None and not override.is_offered:
        raise _invalid("service_id", "This service is not offered at that location")
    return location, service, member, override


async def _slot_is_free(
    session: AsyncSession,
    principal: Principal,
    location: Location,
    service: Service,
    member: Staff,
    start: datetime,
    now: datetime,
    exclude_appointment_id: uuid.UUID | None = None,
) -> bool:
    day = start.astimezone(ZoneInfo(location.timezone)).date()
    slots = await find_slots(
        session,
        principal,
        AvailabilityRequest(
            location_id=location.id,
            service_id=service.id,
            staff_id=member.id,
            date_from=day,
            date_to=day,
        ),
        now=now,
        exclude_appointment_id=exclude_appointment_id,
    )
    return any(slot.starts_at == start for slot in slots)


async def _unavailable(
    session: AsyncSession,
    principal: Principal,
    location: Location,
    service: Service,
    start: datetime,
    now: datetime,
    exclude_appointment_id: uuid.UUID | None = None,
) -> SlotUnavailableError:
    """The error for a taken time, with the nearest genuinely free alternatives attached."""
    day = start.astimezone(ZoneInfo(location.timezone)).date()
    slots: list[SlotOut] = await find_slots(
        session,
        principal,
        AvailabilityRequest(
            location_id=location.id,
            service_id=service.id,
            date_from=day,
            date_to=day + timedelta(days=1),
        ),
        now=now,
        exclude_appointment_id=exclude_appointment_id,
    )
    nearest = sorted(slots, key=lambda s: abs(s.starts_at - start))[:ALTERNATIVES_SHOWN]
    nearest.sort(key=lambda s: s.starts_at)
    return SlotUnavailableError(
        details={"alternatives": [s.model_dump(mode="json") for s in nearest]}
    )


def _normalise_phone(raw: str, country: str | None) -> str:
    try:
        return normalize_phone(raw, country)
    except InvalidPhoneError as exc:
        raise _invalid("customer.phone", str(exc)) from None


async def _window_minutes(session: AsyncSession, appointment: Appointment) -> int:
    location = await session.get(Location, appointment.location_id)
    business = await session.get(Business, appointment.business_id)
    assert location is not None and business is not None
    if location.cancellation_window_minutes is not None:
        return location.cancellation_window_minutes
    return business.cancellation_window_minutes


async def _check_notice(
    session: AsyncSession,
    principal: Principal,
    appointment: Appointment,
    now: datetime,
    force: bool,
) -> None:
    """Changing an appointment close to its start needs a manager's say-so."""
    if force and principal.role == Role.staff:
        raise ForbiddenError("Only a manager can override the notice period.")
    window = await _window_minutes(session, appointment)
    if appointment.starts_at - now < timedelta(minutes=window) and not force:
        raise CancellationWindowPassedError(
            f"Bookings can't be changed or cancelled less than {window} minutes before the start.",
            details={"window_minutes": window},
        )


# --- Creating ---


async def create_booking(
    session: AsyncSession,
    principal: Principal,
    body: BookingCreate,
    *,
    idempotency_key: str,
    source: BookingSource = BookingSource.dashboard,
    call_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> tuple[BookingOut, bool]:
    """Returns (booking, created). `created` is False when the key was already used (a retry)."""
    now = now or datetime.now(UTC)
    start = body.starts_at.astimezone(UTC)

    await _lock_staff(session, body.staff_id)

    # A retried request returns the original booking, even if things have changed since.
    existing = await session.scalar(
        select(Appointment).where(
            Appointment.business_id == principal.business_id,
            Appointment.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        original = await session.get(Location, existing.location_id)
        country = original.country if original else None
        phone = _normalise_phone(body.customer.phone, country)
        return await _replay(session, principal, existing, body, start, phone), False

    location, service, member, override = await _bookable(
        session, principal, body.location_id, body.service_id, body.staff_id
    )
    phone = _normalise_phone(body.customer.phone, location.country)

    if not await _slot_is_free(session, principal, location, service, member, start, now):
        raise await _unavailable(session, principal, location, service, start, now)

    duration = (override.duration_minutes if override else None) or service.duration_minutes
    price = (
        override.price_minor
        if override and override.price_minor is not None
        else service.price_minor
    )
    ends_at = start + timedelta(minutes=duration)

    insert_customer = pg_insert(Customer).values(
        business_id=principal.business_id,
        full_name=body.customer.full_name,
        phone=phone,
        email=body.customer.email,
    )
    customer_id = await session.scalar(
        insert_customer.on_conflict_do_update(
            constraint="uq_customers_business_id_phone",
            # A returning customer keeps their record; we only fill in a missing email.
            set_={
                "email": func.coalesce(Customer.__table__.c.email, insert_customer.excluded.email)
            },
        ).returning(Customer.id)
    )
    assert customer_id is not None

    appointment: Appointment | None = None
    for _ in range(MAX_REFERENCE_ATTEMPTS):
        candidate = Appointment(
            business_id=principal.business_id,
            reference=new_reference(),
            location_id=location.id,
            service_id=service.id,
            staff_id=member.id,
            customer_id=customer_id,
            starts_at=start,
            ends_at=ends_at,
            blocked_until=ends_at + timedelta(minutes=service.buffer_minutes),
            status=AppointmentStatus.booked,
            source=source,
            call_id=call_id,
            price_minor=price,
            currency=service.currency,
            notes=body.notes,
            created_by=principal.user_id,
            idempotency_key=idempotency_key,
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
        except IntegrityError as exc:
            problem = str(exc.orig)
            if "ex_appointments_staff_no_overlap" in problem or "idempotency_key" in problem:
                # Either another request got the time first, or an identical retry of this one did.
                await session.rollback()
                winner = await session.scalar(
                    select(Appointment).where(
                        Appointment.business_id == principal.business_id,
                        Appointment.idempotency_key == idempotency_key,
                    )
                )
                if winner is not None:
                    return await _replay(session, principal, winner, body, start, phone), False
                raise await _unavailable(
                    session, principal, location, service, start, now
                ) from None
            if "reference" in problem:
                continue  # extremely unlikely code clash: try another
            raise
        appointment = candidate
        break
    if appointment is None:
        raise ConflictError("Could not allocate a booking reference; please try again.")

    await _event(
        session,
        principal,
        appointment,
        "created",
        source,
        {"starts_at": start.isoformat(), "staff_id": str(member.id), "service_id": str(service.id)},
    )
    await session.commit()
    return await get_booking(session, principal, appointment.id), True


async def _replay(
    session: AsyncSession,
    principal: Principal,
    existing: Appointment,
    body: BookingCreate,
    start: datetime,
    phone: str,
) -> BookingOut:
    """The same request again gives the same booking; a different one with that key is an error."""
    customer = await session.get(Customer, existing.customer_id)
    same = (
        existing.location_id == body.location_id
        and existing.service_id == body.service_id
        and existing.staff_id == body.staff_id
        and existing.starts_at == start
        and customer is not None
        and customer.phone == phone
    )
    if not same:
        raise IdempotencyKeyReusedError
    return await get_booking(session, principal, existing.id)


# --- Changing ---


async def update_booking(
    session: AsyncSession,
    principal: Principal,
    booking_id: uuid.UUID,
    body: BookingUpdate,
    *,
    force: bool = False,
    source: BookingSource = BookingSource.dashboard,
    now: datetime | None = None,
) -> BookingOut:
    now = now or datetime.now(UTC)
    appointment, _ = await _fetch(session, principal, booking_id, for_update=True)
    fields = body.model_fields_set

    moving = body.starts_at is not None or body.staff_id is not None
    if (moving or body.status is not None) and appointment.status != AppointmentStatus.booked:
        raise BookingNotActiveError

    if body.status is not None:
        if principal.role == Role.staff:
            raise ForbiddenError("Only a manager can record how a visit went.")
        previous = appointment.status
        appointment.status = AppointmentStatus(body.status)
        await _event(
            session,
            principal,
            appointment,
            "status_changed",
            source,
            {"from": previous.value, "to": body.status.value},
        )

    if moving:
        await _lock_staff(session, appointment.staff_id, body.staff_id or appointment.staff_id)
        await _check_notice(session, principal, appointment, now, force)
        location, service, member, override = await _bookable(
            session,
            principal,
            appointment.location_id,
            appointment.service_id,
            body.staff_id or appointment.staff_id,
        )
        start = (body.starts_at or appointment.starts_at).astimezone(UTC)
        if not await _slot_is_free(
            session, principal, location, service, member, start, now, appointment.id
        ):
            raise await _unavailable(
                session, principal, location, service, start, now, appointment.id
            )
        duration = (override.duration_minutes if override else None) or service.duration_minutes
        before = {
            "starts_at": appointment.starts_at.isoformat(),
            "staff_id": str(appointment.staff_id),
        }
        appointment.starts_at = start
        appointment.ends_at = start + timedelta(minutes=duration)
        appointment.blocked_until = appointment.ends_at + timedelta(minutes=service.buffer_minutes)
        appointment.staff_id = member.id
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:
            if "ex_appointments_staff_no_overlap" not in str(exc.orig):
                raise
            session.expire(appointment)
            raise await _unavailable(
                session, principal, location, service, start, now, appointment.id
            ) from None
        await _event(
            session,
            principal,
            appointment,
            "rescheduled",
            source,
            {"from": before, "to": {"starts_at": start.isoformat(), "staff_id": str(member.id)}},
        )

    if "notes" in fields:
        appointment.notes = body.notes
    await session.commit()
    return await get_booking(session, principal, booking_id)


async def cancel_booking(
    session: AsyncSession,
    principal: Principal,
    booking_id: uuid.UUID,
    *,
    force: bool = False,
    reason: str | None = None,
    source: BookingSource = BookingSource.dashboard,
    now: datetime | None = None,
) -> BookingOut:
    now = now or datetime.now(UTC)
    appointment, _ = await _fetch(session, principal, booking_id, for_update=True)
    if appointment.status != AppointmentStatus.booked:
        raise BookingNotActiveError
    await _check_notice(session, principal, appointment, now, force)
    appointment.status = AppointmentStatus.cancelled
    appointment.cancelled_at = now
    appointment.cancellation_reason = reason or "Cancelled"
    await _event(
        session,
        principal,
        appointment,
        "cancelled",
        source,
        {"reason": appointment.cancellation_reason},
    )
    await session.commit()  # the time is free again as soon as this commits
    return await get_booking(session, principal, booking_id)


# --- Customers ---


def _customer_scope(principal: Principal) -> Any:
    """Appointments a caller may count for a customer: the whole business, or their location."""
    conditions: list[Any] = [Appointment.business_id == principal.business_id]
    if not principal.is_owner:
        conditions.append(Appointment.location_id == principal.location_id)
    return conditions


def _customer_stmt(principal: Principal) -> Any:
    visible = _customer_scope(principal)
    bookings = (
        select(func.count())
        .where(Appointment.customer_id == Customer.id, *visible)
        .scalar_subquery()
    )
    last_visit = (
        select(func.max(Appointment.starts_at))
        .where(
            Appointment.customer_id == Customer.id,
            Appointment.status == AppointmentStatus.completed,
            *visible,
        )
        .scalar_subquery()
    )
    stmt = select(Customer, bookings.label("booking_count"), last_visit.label("last_visit_at"))
    stmt = stmt.where(Customer.business_id == principal.business_id)
    if not principal.is_owner:
        # A manager sees customers who have booked at their own location.
        stmt = stmt.where(
            select(Appointment.id).where(Appointment.customer_id == Customer.id, *visible).exists()
        )
    return stmt


def _summary(
    customer: Customer, booking_count: int, last_visit_at: datetime | None
) -> CustomerSummary:
    return CustomerSummary(
        id=customer.id,
        full_name=customer.full_name,
        phone=customer.phone,
        email=customer.email,
        notes=customer.notes,
        created_at=customer.created_at,
        booking_count=booking_count,
        last_visit_at=last_visit_at,
    )


async def list_customers(
    session: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[CustomerSummary], str | None]:
    stmt = _customer_stmt(principal)
    if q and q.strip():
        term = q.strip()
        conditions = [Customer.full_name.ilike(_like(term), escape="\\")]
        digits = "".join(ch for ch in term if ch.isdigit()).lstrip("0")
        if len(digits) >= 3:
            conditions.append(Customer.phone.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conditions))
    if cursor:
        after_created, after_id = decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(Customer.created_at, Customer.id) > tuple_(after_created, after_id)
        )
    rows = list(
        (
            await session.execute(stmt.order_by(Customer.created_at, Customer.id).limit(limit + 1))
        ).all()
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1][0].created_at, rows[-1][0].id)
    return [_summary(c, count, last) for c, count, last in rows], next_cursor


async def get_customer(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID
) -> CustomerDetail:
    row = (
        await session.execute(_customer_stmt(principal).where(Customer.id == customer_id))
    ).first()
    if row is None:
        raise NotFoundError
    customer, count, last = row
    bookings = (
        await session.execute(
            _booking_query()
            .where(Appointment.customer_id == customer_id, *_customer_scope(principal))
            .order_by(Appointment.starts_at.desc())
        )
    ).all()
    summary = _summary(customer, count, last)
    return CustomerDetail(**summary.model_dump(), bookings=[_out(a, c) for a, c in bookings])
