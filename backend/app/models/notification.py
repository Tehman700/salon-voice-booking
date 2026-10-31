import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TenantOwned, Timestamps, UUIDPrimaryKey


class OutboxStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"  # gave up after too many attempts
    skipped = "skipped"  # no longer relevant (e.g. a reminder for a moved or cancelled booking)


outbox_status_enum = Enum(
    OutboxStatus,
    name="outbox_status",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class NotificationOutbox(UUIDPrimaryKey, TenantOwned, Timestamps, Base):
    """An email waiting to be sent, written in the same transaction as the change it describes.

    So an email is never sent for a change that rolled back, and never lost for one that
    committed: a background sender delivers whatever is due.
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["business_id", "appointment_id"],
            ["appointments.business_id", "appointments.id"],
        ),
        # The sender's query: due, pending rows, oldest first.
        Index(
            "ix_notification_outbox_due",
            "send_after",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    appointment_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    # booking_created | booking_rescheduled | booking_cancelled | booking_reminder, and a
    # "_salon" suffix for the copy that goes to the salon itself.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    to_email: Mapped[str] = mapped_column(String(254), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        outbox_status_enum, nullable=False, default=OutboxStatus.pending
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    send_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
