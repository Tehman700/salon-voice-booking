import uuid
from typing import Self

from pydantic import BaseModel

from app.models.business import Business
from app.models.location import Location
from app.schemas.common import CancellationWindow, CountryCode, Name, Phone, Timezone


class LocationInput(BaseModel):
    name: Name
    timezone: Timezone
    phone: Phone | None = None
    address_line1: str | None = None
    city: str | None = None
    country: CountryCode | None = None


class LocationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    phone: str | None
    address_line1: str | None
    city: str | None
    country: str | None
    is_active: bool
    # null -> inherits the business default
    cancellation_window_minutes: int | None
    effective_cancellation_window_minutes: int

    @classmethod
    def build(cls, location: Location, business: Business) -> Self:
        override = location.cancellation_window_minutes
        return cls(
            id=location.id,
            name=location.name,
            slug=location.slug,
            timezone=location.timezone,
            phone=location.phone,
            address_line1=location.address_line1,
            city=location.city,
            country=location.country,
            is_active=location.is_active,
            cancellation_window_minutes=override,
            effective_cancellation_window_minutes=(
                override if override is not None else business.cancellation_window_minutes
            ),
        )


class LocationUpdate(BaseModel):
    """Partial update. Fields that are present are applied, including explicit nulls where a
    field is nullable (e.g. clearing `phone`, or `cancellation_window_minutes: null` to inherit)."""

    name: Name | None = None
    timezone: Timezone | None = None
    phone: Phone | None = None
    address_line1: str | None = None
    city: str | None = None
    country: CountryCode | None = None
    cancellation_window_minutes: CancellationWindow | None = None
    is_active: bool | None = None
