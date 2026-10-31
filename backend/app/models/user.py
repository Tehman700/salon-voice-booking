import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import Timestamps, UUIDPrimaryKey


class Role(enum.StrEnum):
    platform_admin = "platform_admin"
    owner = "owner"
    manager = "manager"
    staff = "staff"


role_enum = Enum(
    Role,
    name="user_role",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)

# platform_admin: no business. owner: whole business. manager/staff: exactly one location.
ROLE_SCOPE_CHECK = (
    "(role = 'platform_admin' AND business_id IS NULL AND location_id IS NULL)"
    " OR (role = 'owner' AND business_id IS NOT NULL AND location_id IS NULL)"
    " OR (role IN ('manager', 'staff') AND business_id IS NOT NULL AND location_id IS NOT NULL)"
)


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(ROLE_SCOPE_CHECK, name="role_scope"),
        # With a NULL location_id this is not enforced (MATCH SIMPLE); otherwise the location must
        # belong to the same business.
        ForeignKeyConstraint(
            ["business_id", "location_id"], ["locations.business_id", "locations.id"]
        ),
    )

    # Nullable only for platform admins (enforced by role_scope).
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column()
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[Role] = mapped_column(role_enum, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
