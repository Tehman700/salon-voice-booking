import uuid
from typing import Annotated, Literal, Self

from pydantic import BaseModel, EmailStr, Field, StringConstraints, model_validator

from app.models.business import LocationMode
from app.models.user import Role
from app.schemas.common import Name, Password
from app.schemas.location import LocationInput


class SignupRequest(BaseModel):
    business_name: Name
    owner_full_name: Name
    email: EmailStr
    password: Password
    location_mode: LocationMode
    locations: Annotated[list[LocationInput], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def _check_location_count(self) -> Self:
        if self.location_mode == LocationMode.single and len(self.locations) != 1:
            raise ValueError("A single-location business must have exactly one location")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class AcceptInviteRequest(BaseModel):
    token: Annotated[str, StringConstraints(min_length=10, max_length=200)]
    full_name: Name
    password: Password


class MeBusiness(BaseModel):
    id: uuid.UUID
    name: str
    location_mode: LocationMode


class Me(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    business: MeBusiness | None
    # Locations this user may act on: every location for owners, their own for manager/staff.
    location_ids: list[uuid.UUID]


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    user: Me
