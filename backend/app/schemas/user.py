import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.user import Role


def _reject_platform_admin(value: Role | None) -> Role | None:
    if value == Role.platform_admin:
        raise ValueError("platform_admin cannot be assigned through this API")
    return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    location_id: uuid.UUID | None
    is_active: bool
    last_login_at: datetime | None


class UserUpdate(BaseModel):
    """Partial update; `location_id: null` is meaningful (owners have no location)."""

    role: Role | None = None
    location_id: uuid.UUID | None = None
    is_active: bool | None = None

    _check_role = field_validator("role")(_reject_platform_admin)


class InviteRequest(BaseModel):
    email: EmailStr
    role: Role
    location_id: uuid.UUID | None = None

    _check_role = field_validator("role")(_reject_platform_admin)


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    location_id: uuid.UUID | None
    expires_at: datetime
    # Only present while emails aren't wired up (local/test); see Settings.expose_invite_tokens.
    token: str | None = None
