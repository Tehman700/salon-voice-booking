import uuid
from datetime import date, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, UUIDPrimaryKey


class LocationHours(UUIDPrimaryKey, TenantOwned, Base):
    """When a location is open, in its local time. No row for a weekday means closed that day."""

    __tablename__ = "location_hours"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "location_id"],
            ["locations.business_id", "locations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("opens_at < closes_at", name="opens_before_closes"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 = Monday
    opens_at: Mapped[time] = mapped_column(Time, nullable=False)
    closes_at: Mapped[time] = mapped_column(Time, nullable=False)


class LocationClosure(UUIDPrimaryKey, TenantOwned, Base):
    """A whole day the location is closed (holiday, renovation...)."""

    __tablename__ = "location_closures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "location_id"],
            ["locations.business_id", "locations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("location_id", "closed_on", name="uq_location_closures_location_id_date"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    closed_on: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
