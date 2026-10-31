"""ORM models. Import every model module here so Alembic sees all tables."""

from app.models.booking import (
    Appointment,
    AppointmentEvent,
    AppointmentStatus,
    BookingSource,
    Customer,
)
from app.models.business import Business, LocationMode
from app.models.catalog import LocationService, Service
from app.models.invite import Invite
from app.models.location import Location
from app.models.refresh_token import RefreshToken
from app.models.schedule import LocationClosure, LocationHours
from app.models.staff import Staff, StaffService, StaffTimeOff, StaffWorkingHours
from app.models.user import Role, User

__all__ = [
    "Appointment",
    "AppointmentEvent",
    "AppointmentStatus",
    "BookingSource",
    "Business",
    "Customer",
    "Invite",
    "Location",
    "LocationClosure",
    "LocationHours",
    "LocationMode",
    "LocationService",
    "RefreshToken",
    "Role",
    "Service",
    "Staff",
    "StaffService",
    "StaffTimeOff",
    "StaffWorkingHours",
    "User",
]
