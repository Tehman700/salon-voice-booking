"""What the voice agent can do, as tools.

Each tool is a thin, voice-friendly wrapper over the same booking service the dashboard uses,
so every booking rule (hours, double booking, notice period) applies to phone calls too. A tool
never raises to Retell: it always answers `{"success": bool, "message": str, ...}`, and
`success` is true only if the backend really did the thing. The agent is told to claim a booking
only on `success: true`, so it cannot promise something that did not happen.

The caller is never a signed-in user: the call is routed to one location (by the number that was
dialled), and every tool runs as a location-scoped principal for that location only.
"""

import hashlib
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_utils import InvalidPhoneError, normalize_phone
from app.core.errors import AppError, ConflictError
from app.core.principal import Principal
from app.models.booking import Appointment, AppointmentStatus, BookingSource, Customer
from app.models.call import CallLog, CallOutcome
from app.models.catalog import LocationService, Service
from app.models.location import Location
from app.models.schedule import LocationClosure, LocationHours
from app.models.staff import Staff, StaffService
from app.models.user import Role
from app.repositories.tenant import AppointmentRepository
from app.schemas.booking import BookingCreate, BookingUpdate, CustomerIn
from app.schemas.catalog import AvailabilityRequest
from app.services import bookings as bookings_service
from app.services.availability import find_slots

logger = logging.getLogger(__name__)

SEARCH_DAYS = 7
MAX_SLOTS_OFFERED = 6
MAX_BOOKINGS_LISTED = 5
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_OF_DAY = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24)}

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Clock = Annotated[str, StringConstraints(pattern=r"^\d{1,2}:\d{2}$")]  # 24-hour "15:30"


# --- What Retell sends ---


class RetellCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    call_id: str = Field(min_length=1, max_length=100)
    from_number: str | None = None
    to_number: str | None = None
    start_timestamp: int | None = None  # unix ms
    end_timestamp: int | None = None
    retell_llm_dynamic_variables: dict[str, Any] = Field(default_factory=dict)
    # "inbound" (a customer rang the salon) or "outbound" (the salon's line rang the customer).
    direction: str | None = None

    @property
    def outbound(self) -> bool:
        return self.direction == "outbound"

    @property
    def salon_number(self) -> str | None:
        """The salon's end of the call: the number dialled in, or the line that dialled out."""
        return self.from_number if self.outbound else self.to_number

    @property
    def customer_number(self) -> str | None:
        """The customer's end of the call."""
        return self.to_number if self.outbound else self.from_number


class FunctionRequest(BaseModel):
    """A custom-function call. (Retell's "payload: args only" setting must be off.)"""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    call: RetellCall


# --- Tool arguments ---


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class NoArgs(_Args):
    pass


class ListStaffArgs(_Args):
    service_id: uuid.UUID | None = None


class CheckAvailabilityArgs(_Args):
    service_id: uuid.UUID
    date: date
    staff_id: uuid.UUID | None = None
    time_of_day: Literal["morning", "afternoon", "evening"] | None = None
    after: Clock | None = None


class CreateBookingArgs(_Args):
    service_id: uuid.UUID
    staff_id: uuid.UUID
    date: date
    time: Clock
    customer_name: Name
    phone: str | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class FindBookingsArgs(_Args):
    phone: str | None = None
    customer_name: str | None = None


class RescheduleArgs(_Args):
    reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=12)]
    customer_name: Name
    date: date
    time: Clock
    phone: str | None = None
    staff_id: uuid.UUID | None = None


class CancelArgs(_Args):
    reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=12)]
    customer_name: Name
    phone: str | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


# --- Routing a call to a location ---


@dataclass(frozen=True)
class Place:
    """The location a call belongs to, as plain values (safe to keep after a rollback)."""

    business_id: uuid.UUID
    location_id: uuid.UUID
    name: str
    timezone: str
    country: str | None
    phone: str | None
    address: str | None


def _place(location: Location) -> Place:
    address = ", ".join(p for p in (location.address_line1, location.city) if p) or None
    return Place(
        business_id=location.business_id,
        location_id=location.id,
        name=location.name,
        timezone=location.timezone,
        country=location.country,
        phone=location.phone,
        address=address,
    )


def _digits(raw: str | None, country: str | None) -> str | None:
    if not raw:
        return None
    try:
        return normalize_phone(raw, country)
    except InvalidPhoneError:
        return None


async def resolve_place(
    session: AsyncSession, call: RetellCall, pinned_location: uuid.UUID | None = None
) -> Place | None:
    """Which location is this call for?

    In order: a `location_id` written into the tool or webhook URL (one agent per location, the
    simplest setup), a `location_id` dynamic variable, or the salon's number on the call (the
    number dialled in, or the line that dialled out) matched to a location's phone. This is the
    one lookup that deliberately spans businesses (it is how a call finds its business). The
    request is already signed by Retell, so these hints are trusted; anything unknown or
    ambiguous routes nowhere.
    """
    pinned: str | uuid.UUID | None = pinned_location or call.retell_llm_dynamic_variables.get(
        "location_id"
    )
    if pinned:
        try:
            location = await session.get(Location, uuid.UUID(str(pinned)))
        except ValueError:
            return None
        return _place(location) if location and location.is_active else None

    dialled = _digits(call.salon_number, None)
    if dialled is None:
        return None
    matches = [
        loc
        for loc in await session.scalars(
            select(Location).where(Location.phone.is_not(None), Location.is_active.is_(True))
        )
        if _digits(loc.phone, loc.country) == dialled
    ]
    return _place(matches[0]) if len(matches) == 1 else None


def _customer_caller_id(from_number: str | None, place: Place) -> str | None:
    """The caller's number, unless it is the salon's own line (as with browser test calls)."""
    if (
        from_number
        and place.phone
        and (_digits(from_number, place.country) == _digits(place.phone, place.country))
    ):
        return None
    return from_number


def principal_for(place: Place) -> Principal:
    """The voice agent acts like a manager of this one location, and never forces anything."""
    return Principal(
        user_id=None,
        business_id=place.business_id,
        role=Role.manager,
        location_id=place.location_id,
    )


async def get_or_create_call(
    session: AsyncSession, place: Place, call: RetellCall
) -> tuple[CallLog, bool]:
    """The log row for this call, created on first sight. Returns (row, created)."""
    started = (
        datetime.fromtimestamp(call.start_timestamp / 1000, UTC)
        if call.start_timestamp
        else datetime.now(UTC)
    )
    created = await session.scalar(
        insert(CallLog)
        .values(
            business_id=place.business_id,
            location_id=place.location_id,
            retell_call_id=call.call_id,
            from_number=call.from_number,
            to_number=call.to_number,
            started_at=started,
            outcome=CallOutcome.info_only,
        )
        .on_conflict_do_nothing(index_elements=["retell_call_id"])
        .returning(CallLog.id)
    )
    log = await session.scalar(select(CallLog).where(CallLog.retell_call_id == call.call_id))
    assert log is not None
    if log.business_id != place.business_id or log.location_id != place.location_id:
        # The same Retell call id turning up for a different location is never legitimate.
        raise ConflictError("This call belongs to another location.", code="call_mismatch")
    return log, created is not None


# --- Formatting for speech ---


def spoken_time(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def spoken_day(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day:%B} {day.day}"


def spoken_reference(reference: str) -> str:
    return " ".join(reference.upper())


def _slot_json(
    starts_at: datetime, tz: ZoneInfo, staff_id: uuid.UUID, staff_name: str
) -> dict[str, str]:
    local = starts_at.astimezone(tz)
    return {
        "date": local.date().isoformat(),
        "time": local.strftime("%H:%M"),
        "spoken": f"{spoken_day(local.date())} at {spoken_time(local)}",
        "staff_id": str(staff_id),
        "staff_name": staff_name,
    }


def _local_start(day: date, clock: str, tz: ZoneInfo) -> datetime | None:
    """A local date and 24-hour time as an aware datetime, or None if it can't exist."""
    hour, minute = (int(part) for part in clock.split(":"))
    if hour > 23 or minute > 59:
        return None
    local = datetime.combine(day, dtime(hour, minute), tzinfo=tz)
    # A time skipped by a clock change does not round-trip.
    if local.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None
    return local


def ok(message: str, **data: Any) -> dict[str, Any]:
    return {"success": True, "message": message, **data}


def fail(code: str, message: str, **data: Any) -> dict[str, Any]:
    return {"success": False, "error": code, "message": message, **data}


# --- The tools ---


@dataclass(frozen=True)
class Ctx:
    session: AsyncSession
    principal: Principal
    place: Place
    call_log_id: uuid.UUID
    retell_call_id: str
    caller_phone: str | None
    now: datetime

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.place.timezone)

    def phone(self, given: str | None) -> str | None:
        return (
            _digits(given, self.place.country)
            if given
            else _digits(self.caller_phone, self.place.country)
        )

    def key(self, action: str, *parts: object) -> str:
        """Same call, same action, same details -> same key, so a repeated tool call is a retry."""
        raw = "|".join([self.retell_call_id, action, *map(str, parts)])
        return "retell-" + hashlib.sha256(raw.encode()).hexdigest()[:40]


async def _alternatives(ctx: Ctx, error: AppError) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for alt in (error.details or {}).get("alternatives", []):
        out.append(
            _slot_json(
                datetime.fromisoformat(alt["starts_at"]),
                ctx.tz,
                uuid.UUID(alt["staff_id"]),
                alt["staff_name"],
            )
        )
    return out


async def _record(ctx: Ctx, outcome: CallOutcome, booking_id: uuid.UUID) -> None:
    await ctx.session.execute(
        update(CallLog)
        .where(CallLog.id == ctx.call_log_id)
        .values(outcome=outcome, booking_id=booking_id)
    )
    await ctx.session.commit()


async def _failure(ctx: Ctx, error: AppError) -> dict[str, Any]:
    """Turn a refusal from the booking service into something the agent can say."""
    await ctx.session.rollback()
    salon = f" Please call the salon on {ctx.place.phone}." if ctx.place.phone else ""
    if error.code == "slot_unavailable":
        alternatives = await _alternatives(ctx, error)
        return fail(
            "slot_unavailable",
            "That time is no longer available. Offer the caller one of the alternatives.",
            alternatives=alternatives,
        )
    if error.code == "cancellation_window_passed":
        minutes = (error.details or {}).get("window_minutes", 0)
        hours = f"{minutes // 60} hours" if minutes and minutes % 60 == 0 else f"{minutes} minutes"
        return fail(
            "too_late_to_change",
            f"Changes and cancellations need at least {hours} notice, so the agent cannot do "
            f"this now.{salon}",
        )
    if error.code == "booking_not_active":
        return fail("not_active", "That booking is already cancelled or finished.")
    if error.status_code in (404, 422):
        return fail("invalid_request", "Those details were not accepted. Check them and retry.")
    return fail("failed", f"Something went wrong, nothing was changed.{salon}")


async def get_salon_info(ctx: Ctx, _: NoArgs) -> dict[str, Any]:
    rows = (
        await ctx.session.execute(
            select(LocationHours.weekday, LocationHours.opens_at, LocationHours.closes_at)
            .where(LocationHours.location_id == ctx.place.location_id)
            .order_by(LocationHours.weekday, LocationHours.opens_at)
        )
    ).all()
    hours = [
        f"{WEEKDAYS[w]}: {spoken_time(datetime.combine(ctx.now.date(), o))} to "
        f"{spoken_time(datetime.combine(ctx.now.date(), c))}"
        for w, o, c in rows
    ]
    local_now = ctx.now.astimezone(ctx.tz)
    return ok(
        f"{ctx.place.name}.",
        name=ctx.place.name,
        address=ctx.place.address,
        phone=ctx.place.phone,
        opening_hours=hours or ["Closed every day"],
        today=local_now.date().isoformat(),
        today_spoken=spoken_day(local_now.date()),
        time_now=spoken_time(local_now),
        timezone=ctx.place.timezone,
    )


async def _offered_services(ctx: Ctx) -> list[dict[str, Any]]:
    offers = {
        o.service_id: o
        for o in await ctx.session.scalars(
            select(LocationService).where(LocationService.location_id == ctx.place.location_id)
        )
    }
    staffed = set(
        await ctx.session.scalars(
            select(StaffService.service_id)
            .join(Staff, Staff.id == StaffService.staff_id)
            .where(Staff.location_id == ctx.place.location_id, Staff.is_active.is_(True))
        )
    )
    out: list[dict[str, Any]] = []
    services = await ctx.session.scalars(
        select(Service)
        .where(Service.business_id == ctx.place.business_id, Service.is_active.is_(True))
        .order_by(Service.category, Service.name)
    )
    for service in services:
        override = offers.get(service.id)
        if service.id not in staffed or (override is not None and not override.is_offered):
            continue
        price = (override.price_minor if override else None) or service.price_minor
        minutes = (override.duration_minutes if override else None) or service.duration_minutes
        out.append(
            {
                "service_id": str(service.id),
                "name": str(service.name),
                "category": service.category,
                "minutes": minutes,
                "price": price // 100,
                "currency": service.currency,
            }
        )
    return out


async def list_services(ctx: Ctx, _: NoArgs) -> dict[str, Any]:
    services = await _offered_services(ctx)
    if not services:
        return fail("none", "There are no services to book at this salon right now.")
    return ok(f"{len(services)} services.", services=services)


async def list_staff(ctx: Ctx, args: ListStaffArgs) -> dict[str, Any]:
    stmt = (
        select(Staff)
        .where(Staff.location_id == ctx.place.location_id, Staff.is_active.is_(True))
        .order_by(Staff.full_name)
    )
    if args.service_id:
        stmt = stmt.join(StaffService, StaffService.staff_id == Staff.id).where(
            StaffService.service_id == args.service_id
        )
    staff = [
        {"staff_id": str(s.id), "name": s.full_name, "title": s.title}
        for s in await ctx.session.scalars(stmt)
    ]
    return ok(f"{len(staff)} stylists.", staff=staff)


def _spread(items: list[Any], count: int) -> list[Any]:
    if len(items) <= count:
        return items
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


async def _closed_on(ctx: Ctx, day: date) -> bool:
    """No opening hours that weekday, or a closure (holiday) on that date."""
    has_hours = await ctx.session.scalar(
        select(LocationHours.id).where(
            LocationHours.location_id == ctx.place.location_id,
            LocationHours.weekday == day.weekday(),
        )
    )
    closure = await ctx.session.scalar(
        select(LocationClosure.id).where(
            LocationClosure.location_id == ctx.place.location_id,
            LocationClosure.closed_on == day,
        )
    )
    return has_hours is None or closure is not None


async def check_availability(ctx: Ctx, args: CheckAvailabilityArgs) -> dict[str, Any]:
    today = ctx.now.astimezone(ctx.tz).date()
    if args.date < today:
        return fail("past_date", "That date has already passed. Ask for a date from today on.")
    slots = await find_slots(
        ctx.session,
        ctx.principal,
        AvailabilityRequest(
            location_id=ctx.place.location_id,
            service_id=args.service_id,
            staff_id=args.staff_id,
            date_from=args.date,
            date_to=args.date + timedelta(days=SEARCH_DAYS - 1),
        ),
        now=ctx.now,
    )
    local = [(s, s.starts_at.astimezone(ctx.tz)) for s in slots]
    if args.time_of_day:
        low, high = TIME_OF_DAY[args.time_of_day]
        local = [(s, t) for s, t in local if low <= t.hour < high]
    if args.after:
        hour, minute = (int(p) for p in args.after.split(":"))
        local = [(s, t) for s, t in local if (t.hour, t.minute) >= (hour, minute)]
    if not local:
        return ok(
            f"Nothing free in the next {SEARCH_DAYS} days that matches. "
            "Offer a different time of day or stylist, or suggest calling the salon.",
            slots=[],
        )
    first_day = local[0][1].date()
    on_day = [(s, t) for s, t in local if t.date() == first_day]
    chosen = _spread(on_day, MAX_SLOTS_OFFERED)
    closed = await _closed_on(ctx, args.date)
    note = (
        ""
        if first_day == args.date
        else (
            f"The salon is closed on {spoken_day(args.date)}; the next day with space is "
            f"{spoken_day(first_day)}. "
            if closed
            else f"Nothing free on {spoken_day(args.date)}; the next day with space is "
            f"{spoken_day(first_day)}. "
        )
    )
    return ok(
        f"{note}Offer these times.",
        requested_date=args.date.isoformat(),
        slots_date=first_day.isoformat(),
        slots=[_slot_json(s.starts_at, ctx.tz, s.staff_id, s.staff_name) for s, _ in chosen],
    )


async def create_booking(ctx: Ctx, args: CreateBookingArgs) -> dict[str, Any]:
    phone = ctx.phone(args.phone)
    if phone is None and args.phone:
        return fail(
            "invalid_phone",
            "That phone number has too many or too few digits. Ask the caller to say it again "
            "slowly, then read it back one digit at a time before booking.",
        )
    if phone is None:
        return fail("need_phone", "Ask the caller for their phone number.")
    start = _local_start(args.date, args.time, ctx.tz)
    if start is None:
        return fail("invalid_time", "That time doesn't exist. Ask for another time.")
    service = await ctx.session.get(Service, args.service_id)
    member = await ctx.session.get(Staff, args.staff_id)
    if (
        service is None
        or member is None
        or service.business_id != ctx.place.business_id
        or member.location_id != ctx.place.location_id
    ):
        return fail("invalid_request", "That service or stylist was not found at this salon.")
    service_name, staff_name = str(service.name), member.full_name
    try:
        booking, _ = await bookings_service.create_booking(
            ctx.session,
            ctx.principal,
            BookingCreate(
                location_id=ctx.place.location_id,
                service_id=args.service_id,
                staff_id=args.staff_id,
                starts_at=start,
                customer=CustomerIn(full_name=args.customer_name, phone=phone),
                notes=args.notes,
            ),
            idempotency_key=ctx.key(
                "create", args.service_id, args.staff_id, start.isoformat(), phone, args.notes or ""
            ),
            source=BookingSource.voice,
            call_id=ctx.call_log_id,
            now=ctx.now,
        )
    except (AppError, ValidationError) as error:
        if isinstance(error, ValidationError):
            return fail("invalid_request", "Those details were not accepted.")
        return await _failure(ctx, error)
    await _record(ctx, CallOutcome.booked, booking.id)
    local = booking.starts_at.astimezone(ctx.tz)
    return ok(
        f"Booked: {service_name} with {staff_name} on {spoken_day(local.date())} at "
        f"{spoken_time(local)}.",
        reference=booking.reference,
        reference_spoken=spoken_reference(booking.reference),
        service=service_name,
        staff=staff_name,
        when=f"{spoken_day(local.date())} at {spoken_time(local)}",
        price=booking.price_minor // 100,
        currency=booking.currency,
        phone=booking.customer.phone,
    )


def _same_person(stored: str, spoken: str) -> bool:
    def tokens(text: str) -> set[str]:
        return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2}

    return bool(tokens(stored) & tokens(spoken))


async def _customer(ctx: Ctx, phone_given: str | None, name: str | None) -> Customer | None:
    """The customer behind this phone number, if the caller can vouch for being them.

    The caller's own number is trusted. A different number needs the name to match too, so
    nobody learns about or changes someone else's booking by guessing a phone number.
    """
    phone = ctx.phone(phone_given)
    if phone is None:
        return None
    customer = await ctx.session.scalar(
        select(Customer).where(
            Customer.business_id == ctx.place.business_id, Customer.phone == phone
        )
    )
    if customer is None:
        return None
    own_number = phone == _digits(ctx.caller_phone, ctx.place.country)
    if name is not None and not _same_person(customer.full_name, name):
        return None
    if not own_number and name is None:
        return None
    return customer


async def _upcoming(ctx: Ctx, customer: Customer) -> list[tuple[Appointment, str, str]]:
    query: Any = (
        select(Appointment, Service.name, Staff.full_name)
        .join(Service, Service.id == Appointment.service_id)
        .join(Staff, Staff.id == Appointment.staff_id)
        .where(
            Appointment.customer_id == customer.id,
            Appointment.status == AppointmentStatus.booked,
            Appointment.blocked_until > ctx.now,
        )
        .order_by(Appointment.starts_at)
        .limit(MAX_BOOKINGS_LISTED)
    )
    stmt = AppointmentRepository(ctx.session, ctx.principal).scope(query)
    return [(a, str(s), n) for a, s, n in (await ctx.session.execute(stmt)).all()]


def _describe(appointment: Appointment, service: str, staff: str, tz: ZoneInfo) -> dict[str, Any]:
    local = appointment.starts_at.astimezone(tz)
    return {
        "reference": appointment.reference,
        "reference_spoken": spoken_reference(appointment.reference),
        "service": service,
        "staff": staff,
        "staff_id": str(appointment.staff_id),
        "when": f"{spoken_day(local.date())} at {spoken_time(local)}",
    }


async def find_my_bookings(ctx: Ctx, args: FindBookingsArgs) -> dict[str, Any]:
    customer = await _customer(ctx, args.phone, args.customer_name)
    found = await _upcoming(ctx, customer) if customer else []
    if not found:
        return ok(
            "No upcoming bookings were found for this phone number.",
            bookings=[],
        )
    return ok(
        f"{len(found)} upcoming.",
        bookings=[_describe(a, s, n, ctx.tz) for a, s, n in found],
    )


async def _own_booking(
    ctx: Ctx, reference: str, phone: str | None, name: str
) -> tuple[Appointment, str, str] | None:
    customer = await _customer(ctx, phone, name)
    if customer is None:
        return None
    wanted = re.sub(r"[^A-Za-z0-9]", "", reference).upper()
    for appointment, service, staff in await _upcoming(ctx, customer):
        if appointment.reference == wanted:
            return appointment, service, staff
    return None


_NOT_FOUND = fail(
    "not_found",
    "No upcoming booking matches that reference, name and phone number. "
    "Ask the caller to check the reference, or use find_my_bookings.",
)


async def reschedule_booking(ctx: Ctx, args: RescheduleArgs) -> dict[str, Any]:
    start = _local_start(args.date, args.time, ctx.tz)
    if start is None:
        return fail("invalid_time", "That time doesn't exist. Ask for another time.")
    found = await _own_booking(ctx, args.reference, args.phone, args.customer_name)
    if found is None:
        return dict(_NOT_FOUND)
    appointment, service, _ = found
    booking_id, staff_before = appointment.id, appointment.staff_id
    try:
        updated = await bookings_service.update_booking(
            ctx.session,
            ctx.principal,
            booking_id,
            BookingUpdate(
                starts_at=start,
                staff_id=args.staff_id if args.staff_id != staff_before else None,
            ),
            source=BookingSource.voice,
            now=ctx.now,
        )
    except AppError as error:
        return await _failure(ctx, error)
    await _record(ctx, CallOutcome.rescheduled, booking_id)
    local = updated.starts_at.astimezone(ctx.tz)
    return ok(
        f"Moved: {service} is now on {spoken_day(local.date())} at {spoken_time(local)}.",
        reference=updated.reference,
        reference_spoken=spoken_reference(updated.reference),
        when=f"{spoken_day(local.date())} at {spoken_time(local)}",
    )


async def cancel_booking(ctx: Ctx, args: CancelArgs) -> dict[str, Any]:
    found = await _own_booking(ctx, args.reference, args.phone, args.customer_name)
    if found is None:
        return dict(_NOT_FOUND)
    appointment, service, _ = found
    booking_id = appointment.id
    local = appointment.starts_at.astimezone(ctx.tz)
    try:
        await bookings_service.cancel_booking(
            ctx.session,
            ctx.principal,
            booking_id,
            reason=args.reason or "Cancelled by phone",
            source=BookingSource.voice,
            now=ctx.now,
        )
    except AppError as error:
        return await _failure(ctx, error)
    await _record(ctx, CallOutcome.cancelled, booking_id)
    return ok(
        f"Cancelled: {service} on {spoken_day(local.date())} at {spoken_time(local)}.",
        reference=args.reference.upper(),
    )


@dataclass(frozen=True)
class Tool:
    args: type[BaseModel]
    run: Callable[[Ctx, Any], Awaitable[dict[str, Any]]]


TOOLS: dict[str, Tool] = {
    "get_salon_info": Tool(NoArgs, get_salon_info),
    "list_services": Tool(NoArgs, list_services),
    "list_staff": Tool(ListStaffArgs, list_staff),
    "check_availability": Tool(CheckAvailabilityArgs, check_availability),
    "create_booking": Tool(CreateBookingArgs, create_booking),
    "find_my_bookings": Tool(FindBookingsArgs, find_my_bookings),
    "reschedule_booking": Tool(RescheduleArgs, reschedule_booking),
    "cancel_booking": Tool(CancelArgs, cancel_booking),
}


def _complaint(error: ValidationError) -> str:
    fields = sorted({str(e["loc"][0]) for e in error.errors() if e["loc"]})
    return "Missing or invalid: " + ", ".join(fields) + ". Ask the caller for it."


async def run_tool(
    session: AsyncSession,
    tool_name: str,
    request: FunctionRequest,
    *,
    location_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Route the call to its location, then run the tool. Never raises for a bad request."""
    tool = TOOLS.get(tool_name)
    if tool is None:
        return fail("unknown_tool", f"There is no tool called {tool_name}.")
    place = await resolve_place(session, request.call, location_id)
    if place is None:
        logger.warning(
            "Voice call %s (%s) could not be routed: salon number %s, dynamic variables %s",
            request.call.call_id,
            request.call.direction or "inbound",
            "present" if request.call.salon_number else "missing",
            sorted(request.call.retell_llm_dynamic_variables),
        )
        return fail("unknown_salon", "This phone line isn't linked to a salon.")
    try:
        log, _ = await get_or_create_call(session, place, request.call)
    except AppError as error:
        return fail(error.code, error.message)
    await session.commit()
    try:
        args = tool.args.model_validate(request.args)
    except ValidationError as error:
        return fail("invalid_arguments", _complaint(error))
    ctx = Ctx(
        session=session,
        principal=principal_for(place),
        place=place,
        call_log_id=log.id,
        retell_call_id=request.call.call_id,
        caller_phone=_customer_caller_id(request.call.customer_number, place),
        now=now or datetime.now(UTC),
    )
    try:
        return await tool.run(ctx, args)
    except AppError as error:
        return await _failure(ctx, error)


__all__ = ["TOOLS", "FunctionRequest", "RetellCall", "run_tool"]
