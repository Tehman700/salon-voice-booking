"""notification outbox

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31 22:42:25.779460

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("appointment_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("to_email", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "sent", "failed", "skipped", name="outbox_status"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "send_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "appointment_id"],
            ["appointments.business_id", "appointments.id"],
            name=op.f("fk_notification_outbox_business_id_appointments"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_notification_outbox_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_outbox")),
    )
    op.create_index(
        op.f("ix_notification_outbox_appointment_id"),
        "notification_outbox",
        ["appointment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_outbox_business_id"),
        "notification_outbox",
        ["business_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["send_after"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.add_column(
        "businesses", sa.Column("notification_email", sa.String(length=254), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("businesses", "notification_email")
    op.drop_index(
        "ix_notification_outbox_due",
        table_name="notification_outbox",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_notification_outbox_business_id"), table_name="notification_outbox")
    op.drop_index(op.f("ix_notification_outbox_appointment_id"), table_name="notification_outbox")
    op.drop_table("notification_outbox")
    sa.Enum(name="outbox_status").drop(op.get_bind(), checkfirst=False)
