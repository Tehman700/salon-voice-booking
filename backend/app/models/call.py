import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, Timestamps, UUIDPrimaryKey


class CallOutcome(enum.StrEnum):
    booked = "booked"
    rescheduled = "rescheduled"
    cancelled = "cancelled"
    info_only = "info_only"
    failed = "failed"
    abandoned = "abandoned"


call_outcome_enum = Enum(
    CallOutcome,
    name="call_outcome",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class CallLog(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """One phone call handled by the voice agent."""

    __tablename__ = "call_logs"
    __table_args__ = (
        UniqueConstraint("business_id", "id", name="uq_call_logs_business_id_id"),
        # Retell's own call ids are globally unique, which also makes repeated webhooks harmless.
        UniqueConstraint("retell_call_id", name="uq_call_logs_retell_call_id"),
        ForeignKeyConstraint(
            ["business_id", "location_id"], ["locations.business_id", "locations.id"]
        ),
        ForeignKeyConstraint(
            ["business_id", "booking_id"],
            ["appointments.business_id", "appointments.id"],
        ),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_ok"),
    )

    retell_call_id: Mapped[str] = mapped_column(String(100), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    from_number: Mapped[str | None] = mapped_column(String(32))
    to_number: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[CallOutcome] = mapped_column(
        call_outcome_enum, nullable=False, default=CallOutcome.info_only
    )
    summary: Mapped[str | None] = mapped_column(Text)
    disconnection_reason: Mapped[str | None] = mapped_column(String(100))
    # [{"role": "agent" | "user", "text": "..."}]
    transcript: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB)
    # The booking this call made, moved or cancelled (the last one, if there were several).
    booking_id: Mapped[uuid.UUID | None] = mapped_column()
