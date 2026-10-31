"""Tenant-scoped data access.

Services never write their own queries against tenant tables. They go through a repository,
whose `select()` always filters on the caller's `business_id` (and, for managers and staff, on
their location). A row that belongs to another business or location simply does not exist from
the caller's point of view, so it comes back as "not found".
"""

import uuid
from typing import Any, ClassVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.principal import Principal
from app.models.invite import Invite
from app.models.location import Location
from app.models.mixins import UUIDPrimaryKey
from app.models.user import User


class TenantRepository[M: UUIDPrimaryKey]:
    model: type[M]
    # Column holding the owning business.
    business_column: ClassVar[InstrumentedAttribute[Any]]
    # Column tying a row to one location. Managers/staff only see rows where it equals their own
    # location; owners see the whole business. None -> rows are business-wide.
    location_column: ClassVar[InstrumentedAttribute[Any] | None] = None

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    def select(self) -> Select[M]:
        # Read the columns via the class: through an instance they'd act as ORM descriptors.
        cls = type(self)
        stmt = select(self.model).where(cls.business_column == self.principal.business_id)
        if not self.principal.is_owner and cls.location_column is not None:
            stmt = stmt.where(cls.location_column == self.principal.location_id)
        return stmt

    async def get(self, row_id: uuid.UUID, *, for_update: bool = False) -> M | None:
        stmt = self.select().where(self.model.id == row_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)


class LocationRepository(TenantRepository[Location]):
    model = Location
    business_column = Location.business_id
    location_column = Location.id


class UserRepository(TenantRepository[User]):
    model = User
    business_column = User.business_id
    location_column = User.location_id


class InviteRepository(TenantRepository[Invite]):
    model = Invite
    business_column = Invite.business_id
    location_column = Invite.location_id
