import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, Timestamps, UUIDPrimaryKey


class AppointmentStatus(enum.StrEnum):
    booked = "booked"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class BookingSource(enum.StrEnum):
    voice = "voice"
    dashboard = "dashboard"


appointment_status_enum = Enum(
    AppointmentStatus,
    name="appointment_status",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)
booking_source_enum = Enum(
    BookingSource,
    name="booking_source",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Customer(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """Someone who books. Identified by phone number, shared across a business's locations."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("business_id", "id", name="uq_customers_business_id_id"),
        UniqueConstraint("business_id", "phone", name="uq_customers_business_id_phone"),
    )

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)  # normalised, e.g. +923001234567
    email: Mapped[str | None] = mapped_column(CITEXT)
    notes: Mapped[str | None] = mapped_column(Text)


class Appointment(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("business_id", "id", name="uq_appointments_business_id_id"),
        UniqueConstraint("business_id", "reference", name="uq_appointments_business_id_reference"),
        UniqueConstraint(
            "business_id", "idempotency_key", name="uq_appointments_business_id_idempotency_key"
        ),
        ForeignKeyConstraint(
            ["business_id", "location_id"], ["locations.business_id", "locations.id"]
        ),
        ForeignKeyConstraint(
            ["business_id", "service_id"], ["services.business_id", "services.id"]
        ),
        ForeignKeyConstraint(["business_id", "staff_id"], ["staff.business_id", "staff.id"]),
        ForeignKeyConstraint(
            ["business_id", "customer_id"], ["customers.business_id", "customers.id"]
        ),
        CheckConstraint("starts_at < ends_at", name="start_before_end"),
        CheckConstraint("ends_at <= blocked_until", name="buffer_not_negative"),
        CheckConstraint("price_minor >= 0", name="price_non_negative"),
        # The heart of double-booking prevention: no two live appointments of one staff member may
        # overlap in time, counting the service's cleanup buffer. Postgres enforces this on every
        # insert and update, even for requests that race each other, so it cannot be bypassed.
        ExcludeConstraint(
            ("staff_id", "="),
            (text("tstzrange(starts_at, blocked_until, '[)')"), "&&"),
            where=text("status <> 'cancelled'"),
            using="gist",
            name="ex_appointments_staff_no_overlap",
        ),
    )

    # Short, speakable code the customer can quote on the phone, e.g. K7Q2M.
    reference: Mapped[str] = mapped_column(String(8), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    staff_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # ends_at plus the service's cleanup buffer: the stretch during which the staff member is busy.
    blocked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[AppointmentStatus] = mapped_column(
        appointment_status_enum,
        nullable=False,
        default=AppointmentStatus.booked,
        server_default=text("'booked'"),
    )
    source: Mapped[BookingSource] = mapped_column(booking_source_enum, nullable=False)
    # Set when the voice agent booked it (the call log arrives with the voice module).
    call_id: Mapped[uuid.UUID | None] = mapped_column()
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Lets a client safely retry a create request (a dropped connection, a repeated tool call).
    idempotency_key: Mapped[str | None] = mapped_column(String(100))


class AppointmentEvent(UUIDPrimaryKey, TenantOwned, Base):
    """Append-only history of what happened to an appointment, and who did it."""

    __tablename__ = "appointment_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "appointment_id"],
            ["appointments.business_id", "appointments.id"],
            ondelete="CASCADE",
        ),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[BookingSource] = mapped_column(booking_source_enum, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
