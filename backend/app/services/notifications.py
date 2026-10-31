"""Booking emails: written to an outbox with the booking change, delivered later by a sender.

The booking service calls `on_booking` inside its own transaction, just before it commits, so
the emails exist if and only if the change does. `deliver_due` sends whatever is due; the API
runs it in a loop (`run_sender`) when an email sender is configured.

Who gets what:
- the customer, if they gave an email address: confirmation, change, cancellation, and a
  reminder the day before;
- the salon, at the business's notification address: an alert for every booking, change and
  cancellation (most phone callers leave no email, so this is how the salon hears of them).
"""

import asyncio
import contextlib
import enum
import html
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.booking import Appointment, BookingSource, Customer
from app.models.business import Business
from app.models.catalog import Service
from app.models.location import Location
from app.models.notification import NotificationOutbox, OutboxStatus
from app.models.staff import Staff

logger = logging.getLogger(__name__)

REMINDER_BEFORE = timedelta(hours=24)
# Don't send a "see you tomorrow" reminder for a booking made a few hours before it.
REMINDER_MIN_LEAD = timedelta(hours=2)
MAX_ATTEMPTS = 5
BATCH = 50


class BookingChange(enum.StrEnum):
    created = "booking_created"
    rescheduled = "booking_rescheduled"
    cancelled = "booking_cancelled"


@dataclass(frozen=True)
class Details:
    """Everything an email about one appointment says, read once inside the transaction."""

    business: str
    salon: str
    address: str | None
    salon_phone: str | None
    service: str
    staff: str
    customer: str
    customer_email: str | None
    customer_phone: str
    notification_email: str | None
    when: str
    reference: str
    source: BookingSource
    starts_at: datetime


async def _details(session: AsyncSession, appointment: Appointment) -> Details:
    location = await session.get(Location, appointment.location_id)
    business = await session.get(Business, appointment.business_id)
    service = await session.get(Service, appointment.service_id)
    staff = await session.get(Staff, appointment.staff_id)
    customer = await session.get(Customer, appointment.customer_id)
    assert location and business and service and staff and customer
    local = appointment.starts_at.astimezone(ZoneInfo(location.timezone))
    hour = local.hour % 12 or 12
    when = (
        f"{local:%A} {local.day} {local:%B %Y} at {hour}:{local.minute:02d} "
        f"{'AM' if local.hour < 12 else 'PM'}"
    )
    address = ", ".join(p for p in (location.address_line1, location.city) if p) or None
    return Details(
        business=business.name,
        salon=location.name,
        address=address,
        salon_phone=location.phone,
        service=str(service.name),
        staff=staff.full_name,
        customer=customer.full_name,
        customer_email=customer.email,
        customer_phone=customer.phone,
        notification_email=business.notification_email,
        when=when,
        reference=appointment.reference,
        source=appointment.source,
        starts_at=appointment.starts_at,
    )


# --- What the emails say ---


@dataclass(frozen=True)
class Email:
    subject: str
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"

    @property
    def html(self) -> str:
        paragraphs = "".join(
            f'<p style="margin:0 0 12px">{html.escape(line)}</p>' for line in self.lines if line
        )
        return (
            '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;'
            f'color:#171717;max-width:560px">{paragraphs}</div>'
        )


def _visit(d: Details) -> list[str]:
    lines = [
        f"Service: {d.service} with {d.staff}",
        f"When: {d.when}",
        f"Where: {d.salon}" + (f", {d.address}" if d.address else ""),
        f"Reference: {d.reference}",
    ]
    return lines


def _contact(d: Details) -> str:
    return (
        f"To change or cancel, call {d.salon_phone} and quote your reference."
        if d.salon_phone
        else "To change or cancel, contact the salon and quote your reference."
    )


def customer_email(change: BookingChange | None, d: Details) -> Email:
    """change=None means the reminder."""
    hello = f"Hi {d.customer.split()[0]},"
    if change is BookingChange.created:
        return Email(
            f"Booking confirmed: {d.service} on {d.when}",
            [
                hello,
                "",
                f"Your appointment at {d.business} is booked.",
                "",
                *_visit(d),
                "",
                _contact(d),
            ],
        )
    if change is BookingChange.rescheduled:
        return Email(
            f"Booking moved: {d.service} is now on {d.when}",
            [
                hello,
                "",
                "Your appointment has been moved. The new details:",
                "",
                *_visit(d),
                "",
                _contact(d),
            ],
        )
    if change is BookingChange.cancelled:
        return Email(
            f"Booking cancelled: {d.service} on {d.when}",
            [
                hello,
                "",
                f"Your appointment at {d.business} has been cancelled.",
                "",
                *_visit(d),
                "",
                "We hope to see you another time.",
            ],
        )
    return Email(
        f"Reminder: {d.service} tomorrow, {d.when}",
        [hello, "", "A reminder of your appointment:", "", *_visit(d), "", _contact(d)],
    )


def salon_email(change: BookingChange, d: Details) -> Email:
    how = "by phone (voice agent)" if d.source is BookingSource.voice else "from the dashboard"
    verb = {
        BookingChange.created: ("New booking", "was booked"),
        BookingChange.rescheduled: ("Booking moved", "was moved"),
        BookingChange.cancelled: ("Booking cancelled", "was cancelled"),
    }[change]
    return Email(
        f"{verb[0]}: {d.customer}, {d.service}, {d.when}",
        [
            f"An appointment at {d.salon} {verb[1]} {how}.",
            "",
            f"Customer: {d.customer} ({d.customer_phone})",
            *_visit(d),
        ],
    )


# --- Writing to the outbox (inside the booking transaction) ---


def _row(
    business_id: object,
    appointment_id: object,
    kind: str,
    to: str,
    email: Email,
    send_after: datetime,
) -> NotificationOutbox:
    return NotificationOutbox(
        business_id=business_id,
        appointment_id=appointment_id,
        kind=kind,
        to_email=to,
        subject=email.subject[:200],
        body_text=email.text,
        body_html=email.html,
        status=OutboxStatus.pending,
        attempts=0,
        send_after=send_after,
    )


async def on_booking(
    session: AsyncSession, appointment: Appointment, change: BookingChange, *, now: datetime
) -> None:
    """Queue the emails for a booking change. Call before the change's transaction commits."""
    d = await _details(session, appointment)

    # Any reminder already queued is about the old time (or a booking that no longer exists).
    if change is not BookingChange.created:
        await session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.appointment_id == appointment.id,
                NotificationOutbox.kind == "booking_reminder",
                NotificationOutbox.status == OutboxStatus.pending,
            )
            .values(status=OutboxStatus.skipped, last_error="Superseded by a later change")
        )

    rows = []
    if d.customer_email:
        rows.append(
            _row(
                appointment.business_id,
                appointment.id,
                change.value,
                d.customer_email,
                customer_email(change, d),
                now,
            )
        )
        remind_at = d.starts_at - REMINDER_BEFORE
        if change is not BookingChange.cancelled and d.starts_at - now >= REMINDER_MIN_LEAD:
            rows.append(
                _row(
                    appointment.business_id,
                    appointment.id,
                    "booking_reminder",
                    d.customer_email,
                    customer_email(None, d),
                    max(remind_at, now),
                )
            )
    if d.notification_email:
        rows.append(
            _row(
                appointment.business_id,
                appointment.id,
                f"{change.value}_salon",
                d.notification_email,
                salon_email(change, d),
                now,
            )
        )
    session.add_all(rows)


# --- Sending ---


class Sender(Protocol):
    async def send(self, *, to: str, subject: str, text: str, html: str) -> None: ...


class SesSender:
    """Amazon SES (API v2), using the server's IAM role for credentials."""

    def __init__(self, from_address: str, region: str) -> None:
        import boto3  # imported here so tests and local runs never need AWS

        self.from_address = from_address
        self.client = boto3.client("sesv2", region_name=region)

    async def send(self, *, to: str, subject: str, text: str, html: str) -> None:
        await asyncio.to_thread(
            self.client.send_email,
            FromEmailAddress=self.from_address,
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text, "Charset": "UTF-8"},
                        "Html": {"Data": html, "Charset": "UTF-8"},
                    },
                }
            },
        )


def backoff(attempts: int) -> timedelta:
    """1, 2, 4, 8 minutes between tries."""
    return timedelta(minutes=2 ** (attempts - 1))


async def deliver_due(
    session: AsyncSession, sender: Sender, *, now: datetime | None = None, limit: int = BATCH
) -> int:
    """Send every pending email that is due. Returns how many were sent.

    Rows are claimed with SKIP LOCKED, so two senders never send the same email.
    """
    now = now or datetime.now(UTC)
    rows = list(
        await session.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == OutboxStatus.pending,
                NotificationOutbox.send_after <= now,
            )
            .order_by(NotificationOutbox.send_after, NotificationOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    sent = 0
    for row in rows:
        row.attempts += 1
        try:
            await sender.send(
                to=row.to_email, subject=row.subject, text=row.body_text, html=row.body_html
            )
        except Exception as exc:  # any failure is retried, then given up on
            row.last_error = f"{type(exc).__name__}: {exc}"[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = OutboxStatus.failed
                logger.error("Gave up on email %s to %s: %s", row.id, row.to_email, exc)
            else:
                row.send_after = now + backoff(row.attempts)
        else:
            row.status = OutboxStatus.sent
            row.sent_at = now
            row.last_error = None
            sent += 1
    await session.commit()
    return sent


def configured_sender() -> Sender | None:
    settings = get_settings()
    if not settings.email_from:
        return None
    return SesSender(settings.email_from_header, settings.email_region)


async def run_sender(
    sessionmaker: Callable[[], AsyncSession],
    sender: Sender,
    stop: asyncio.Event,
    *,
    interval: float,
) -> None:
    """Deliver due emails every `interval` seconds until `stop` is set. Never crashes the API."""
    while not stop.is_set():
        try:
            async with sessionmaker() as session:
                await deliver_due(session, sender)
        except Exception:
            logger.exception("Email sender pass failed; will retry")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
