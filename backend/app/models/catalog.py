import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, Timestamps, UUIDPrimaryKey

DEFAULT_CURRENCY = "PKR"


class Service(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """Something a salon sells (haircut, facial...). Shared by every location of a business."""

    __tablename__ = "services"
    __table_args__ = (
        # Lets child tables reference (business_id, id) so a row can never mix two businesses.
        UniqueConstraint("business_id", "id", name="uq_services_business_id_id"),
        UniqueConstraint("business_id", "name", name="uq_services_business_id_name"),
        CheckConstraint("duration_minutes BETWEEN 5 AND 480", name="duration_range"),
        CheckConstraint("buffer_minutes BETWEEN 0 AND 120", name="buffer_range"),
        CheckConstraint("price_minor >= 0", name="price_non_negative"),
    )

    name: Mapped[str] = mapped_column(CITEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(60))
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Cleanup time after the service; it blocks the stylist but is not part of the appointment.
    buffer_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_CURRENCY, server_default=DEFAULT_CURRENCY
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class LocationService(TenantOwned, Base):
    """A location's own price/duration for a service, or a decision not to offer it there."""

    __tablename__ = "location_services"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "location_id"],
            ["locations.business_id", "locations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["business_id", "service_id"],
            ["services.business_id", "services.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("price_minor IS NULL OR price_minor >= 0", name="price_non_negative"),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes BETWEEN 5 AND 480", name="duration_range"
        ),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    service_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # NULL -> use the service's own value.
    price_minor: Mapped[int | None] = mapped_column(Integer)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    is_offered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
