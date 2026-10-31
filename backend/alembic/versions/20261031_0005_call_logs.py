"""call logs

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31 19:49:15.449338

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "call_logs",
        sa.Column("retell_call_id", sa.String(length=100), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("from_number", sa.String(length=32), nullable=True),
        sa.Column("to_number", sa.String(length=32), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "booked",
                "rescheduled",
                "cancelled",
                "info_only",
                "failed",
                "abandoned",
                name="call_outcome",
            ),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("disconnection_reason", sa.String(length=100), nullable=True),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("booking_id", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name=op.f("ck_call_logs_duration_ok"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "booking_id"],
            ["appointments.business_id", "appointments.id"],
            name=op.f("fk_call_logs_business_id_appointments"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "location_id"],
            ["locations.business_id", "locations.id"],
            name=op.f("fk_call_logs_business_id_locations"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_call_logs_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_logs")),
        sa.UniqueConstraint("business_id", "id", name="uq_call_logs_business_id_id"),
        sa.UniqueConstraint("retell_call_id", name="uq_call_logs_retell_call_id"),
    )
    op.create_index(op.f("ix_call_logs_business_id"), "call_logs", ["business_id"], unique=False)
    op.create_index(op.f("ix_call_logs_location_id"), "call_logs", ["location_id"], unique=False)
    op.create_index(op.f("ix_call_logs_started_at"), "call_logs", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_call_logs_started_at"), table_name="call_logs")
    op.drop_index(op.f("ix_call_logs_location_id"), table_name="call_logs")
    op.drop_index(op.f("ix_call_logs_business_id"), table_name="call_logs")
    op.drop_table("call_logs")
    sa.Enum(name="call_outcome").drop(op.get_bind(), checkfirst=False)
