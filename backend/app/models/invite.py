import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, UUIDPrimaryKey
from app.models.user import Role, role_enum


class Invite(UUIDPrimaryKey, TenantOwned, Base):
    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint(
            "(role = 'owner' AND location_id IS NULL)"
            " OR (role IN ('manager', 'staff') AND location_id IS NOT NULL)",
            name="role_scope",
        ),
        ForeignKeyConstraint(
            ["business_id", "location_id"], ["locations.business_id", "locations.id"]
        ),
    )

    location_id: Mapped[uuid.UUID | None] = mapped_column()
    email: Mapped[str] = mapped_column(CITEXT, index=True, nullable=False)
    role: Mapped[Role] = mapped_column(role_enum, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
