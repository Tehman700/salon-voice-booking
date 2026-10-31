import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, Timestamps, UUIDPrimaryKey


class Staff(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """Someone who takes appointments at one location (not necessarily a dashboard user)."""

    __tablename__ = "staff"
    __table_args__ = (
        UniqueConstraint("business_id", "id", name="uq_staff_business_id_id"),
        ForeignKeyConstraint(
            ["business_id", "location_id"], ["locations.business_id", "locations.id"]
        ),
        CheckConstraint("color ~ '^#[0-9a-fA-F]{6}$'", name="color_hex"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    # Links the person to a dashboard login, so staff can be limited to their own bookings.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str | None] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(
        String(7), nullable=False, default="#0070f3", server_default="#0070f3"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class StaffService(TenantOwned, Base):
    """Which services a staff member performs."""

    __tablename__ = "staff_services"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "staff_id"], ["staff.business_id", "staff.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["business_id", "service_id"],
            ["services.business_id", "services.id"],
            ondelete="CASCADE",
        ),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    service_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class StaffWorkingHours(UUIDPrimaryKey, TenantOwned, Base):
    """One block of a staff member's week, in the location's local time. A day may have several."""

    __tablename__ = "staff_working_hours"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "staff_id"], ["staff.business_id", "staff.id"], ondelete="CASCADE"
        ),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="start_before_end"),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 = Monday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class StaffTimeOff(UUIDPrimaryKey, TenantOwned, Base):
    __tablename__ = "staff_time_off"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "staff_id"], ["staff.business_id", "staff.id"], ondelete="CASCADE"
        ),
        CheckConstraint("starts_at < ends_at", name="start_before_end"),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
