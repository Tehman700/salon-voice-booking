"""Request/response shapes for bookings and customers (see docs/api-contract.md)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, EmailStr, StringConstraints, model_validator

from app.models.booking import AppointmentStatus, BookingSource
from app.schemas.common import Name

Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=30)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


def _require_timezone(value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError("include a timezone, e.g. 2026-11-03T09:00:00Z")


class CustomerIn(BaseModel):
    full_name: Name
    phone: Phone
    email: EmailStr | None = None


class BookingCreate(BaseModel):
    location_id: uuid.UUID
    service_id: uuid.UUID
    staff_id: uuid.UUID
    starts_at: datetime
    customer: CustomerIn
    notes: Notes | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        _require_timezone(self.starts_at)
        return self


class BookingUpdate(BaseModel):
    """Reschedule (`starts_at` and/or `staff_id`), edit `notes`, or mark the visit's outcome."""

    starts_at: datetime | None = None
    staff_id: uuid.UUID | None = None
    notes: Notes | None = None
    status: Literal[AppointmentStatus.completed, AppointmentStatus.no_show] | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        _require_timezone(self.starts_at)
        return self


class CustomerOut(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None


class BookingOut(BaseModel):
    id: uuid.UUID
    reference: str
    location_id: uuid.UUID
    service_id: uuid.UUID
    staff_id: uuid.UUID
    customer: CustomerOut
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    source: BookingSource
    call_id: uuid.UUID | None
    price_minor: int
    currency: str
    notes: str | None
    created_at: datetime
    cancelled_at: datetime | None
    cancellation_reason: str | None


class CustomerSummary(CustomerOut):
    notes: str | None
    created_at: datetime
    booking_count: int
    last_visit_at: datetime | None


class CustomerDetail(CustomerSummary):
    bookings: list[BookingOut]


__all__ = [
    "BookingCreate",
    "BookingOut",
    "BookingUpdate",
    "CustomerDetail",
    "CustomerIn",
    "CustomerOut",
    "CustomerSummary",
    "Reason",
]
