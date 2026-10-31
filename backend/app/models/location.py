from sqlalchemy import Boolean, CheckConstraint, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, Timestamps, UUIDPrimaryKey


class Location(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """One physical salon. A single-salon business simply has exactly one."""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("business_id", "slug", name="uq_locations_business_id_slug"),
        # Lets child tables reference (business_id, id) so a row can never point at another
        # business's location.
        UniqueConstraint("business_id", "id", name="uq_locations_business_id_id"),
        CheckConstraint(
            "cancellation_window_minutes IS NULL OR cancellation_window_minutes >= 0",
            name="cancellation_window_non_negative",
        ),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    # NULL -> inherit the business default.
    cancellation_window_minutes: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
