import uuid

from pydantic import BaseModel, ConfigDict

from app.models.business import LocationMode
from app.schemas.common import CancellationWindow, Name, Timezone


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    location_mode: LocationMode
    default_timezone: str
    cancellation_window_minutes: int


class BusinessUpdate(BaseModel):
    """Partial update. Omitted (or null) fields are left unchanged."""

    name: Name | None = None
    default_timezone: Timezone | None = None
    cancellation_window_minutes: CancellationWindow | None = None
