"""Shapes for services, staff, schedules and availability (see docs/api-contract.md)."""

import uuid
from datetime import date, datetime, time
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.common import Name

HHMM = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Duration = Annotated[int, Field(ge=5, le=480)]
Buffer = Annotated[int, Field(ge=0, le=120)]
Price = Annotated[int, Field(ge=0, le=100_000_000)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def format_hhmm(value: time) -> str:
    return value.strftime("%H:%M")


# --- Services ---


class LocationOverrideIn(BaseModel):
    location_id: uuid.UUID
    price_minor: Price | None = None
    duration_minutes: Duration | None = None
    is_offered: bool = True


class ServiceBase(BaseModel):
    name: Name
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
    ) = None
    category: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    duration_minutes: Duration
    buffer_minutes: Buffer = 0
    price_minor: Price
    currency: Currency = "PKR"
    is_active: bool = True


class ServiceCreate(ServiceBase):
    location_overrides: list[LocationOverrideIn] = []


class ServiceUpdate(BaseModel):
    """Partial update. `location_overrides`, if present, replaces the ones the caller may edit."""

    name: Name | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
    ) = None
    category: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    duration_minutes: Duration | None = None
    buffer_minutes: Buffer | None = None
    price_minor: Price | None = None
    currency: Currency | None = None
    is_active: bool | None = None
    location_overrides: list[LocationOverrideIn] | None = None


class LocationOverrideOut(LocationOverrideIn):
    model_config = ConfigDict(from_attributes=True)


class ServiceOut(ServiceBase):
    id: uuid.UUID
    location_overrides: list[LocationOverrideOut]


# --- Staff ---


class StaffCreate(BaseModel):
    location_id: uuid.UUID
    full_name: Name
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    color: Color = "#0070f3"
    service_ids: list[uuid.UUID] = []
    is_active: bool = True
    user_id: uuid.UUID | None = None

    @field_validator("service_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(value))


class StaffUpdate(BaseModel):
    """Partial update. `title: null` clears it; `service_ids` replaces the whole list."""

    location_id: uuid.UUID | None = None
    full_name: Name | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    color: Color | None = None
    service_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None
    user_id: uuid.UUID | None = None


class StaffOut(BaseModel):
    id: uuid.UUID
    location_id: uuid.UUID
    user_id: uuid.UUID | None
    full_name: str
    title: str | None
    color: str
    service_ids: list[uuid.UUID]
    is_active: bool


# --- Schedules ---


class HoursBlock(BaseModel):
    weekday: Annotated[int, Field(ge=0, le=6)]  # 0 = Monday
    start: HHMM
    end: HHMM

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class TimeOffCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: Reason | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("times must include a timezone, e.g. 2026-11-03T09:00:00Z")
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        return self


class TimeOffOut(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None


class ClosureCreate(BaseModel):
    date: date
    reason: Reason | None = None


class ClosureOut(BaseModel):
    id: uuid.UUID
    date: date
    reason: str | None


# --- Availability ---

MAX_AVAILABILITY_DAYS = 31


class AvailabilityRequest(BaseModel):
    location_id: uuid.UUID
    service_id: uuid.UUID
    staff_id: uuid.UUID | None = None  # omit for "any staff"
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        days = (self.date_to - self.date_from).days
        if days < 0:
            raise ValueError("date_to must not be before date_from")
        if days >= MAX_AVAILABILITY_DAYS:
            raise ValueError(f"ask for at most {MAX_AVAILABILITY_DAYS} days at a time")
        return self


class SlotOut(BaseModel):
    starts_at: datetime
    ends_at: datetime
    staff_id: uuid.UUID
    staff_name: str


class AvailabilityResponse(BaseModel):
    slots: list[SlotOut]
