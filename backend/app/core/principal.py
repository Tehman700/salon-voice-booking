import uuid
from dataclasses import dataclass

from app.models.user import Role


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, always tied to exactly one business.

    Built from the database on every request (not from token claims alone), so deactivating a
    user or changing their role takes effect immediately.
    """

    user_id: uuid.UUID
    business_id: uuid.UUID
    role: Role
    # Set for manager/staff, None for owners (who may act on every location).
    location_id: uuid.UUID | None

    @property
    def is_owner(self) -> bool:
        return self.role == Role.owner
