"""customers appointments and audit events

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31 17:06:02.586269

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Created once, up front: booking_source is shared by two tables, and a second CREATE TYPE inside
# create_table would fail.
appointment_status = postgresql.ENUM(
    "booked", "completed", "cancelled", "no_show", name="appointment_status", create_type=False
)
booking_source = postgresql.ENUM("voice", "dashboard", name="booking_source", create_type=False)


def upgrade() -> None:
    appointment_status.create(op.get_bind(), checkfirst=False)
    booking_source.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "customers",
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_customers_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("business_id", "id", name="uq_customers_business_id_id"),
        sa.UniqueConstraint("business_id", "phone", name="uq_customers_business_id_phone"),
    )
    op.create_index(op.f("ix_customers_business_id"), "customers", ["business_id"], unique=False)
    op.create_table(
        "appointments",
        sa.Column("reference", sa.String(length=8), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("staff_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            appointment_status,
            server_default=sa.text("'booked'"),
            nullable=False,
        ),
        sa.Column("source", booking_source, nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
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
        postgresql.ExcludeConstraint(
            (sa.column("staff_id"), "="),
            (sa.text("tstzrange(starts_at, blocked_until, '[)')"), "&&"),
            where=sa.text("status <> 'cancelled'"),
            using="gist",
            name="ex_appointments_staff_no_overlap",
        ),
        sa.CheckConstraint(
            "ends_at <= blocked_until", name=op.f("ck_appointments_buffer_not_negative")
        ),
        sa.CheckConstraint("price_minor >= 0", name=op.f("ck_appointments_price_non_negative")),
        sa.CheckConstraint("starts_at < ends_at", name=op.f("ck_appointments_start_before_end")),
        sa.ForeignKeyConstraint(
            ["business_id", "customer_id"],
            ["customers.business_id", "customers.id"],
            name=op.f("fk_appointments_business_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "location_id"],
            ["locations.business_id", "locations.id"],
            name=op.f("fk_appointments_business_id_locations"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "service_id"],
            ["services.business_id", "services.id"],
            name=op.f("fk_appointments_business_id_services"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "staff_id"],
            ["staff.business_id", "staff.id"],
            name=op.f("fk_appointments_business_id_staff"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_appointments_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_appointments_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
        sa.UniqueConstraint("business_id", "id", name="uq_appointments_business_id_id"),
        sa.UniqueConstraint(
            "business_id", "idempotency_key", name="uq_appointments_business_id_idempotency_key"
        ),
        sa.UniqueConstraint(
            "business_id", "reference", name="uq_appointments_business_id_reference"
        ),
    )
    op.create_index(
        op.f("ix_appointments_business_id"), "appointments", ["business_id"], unique=False
    )
    op.create_index(
        op.f("ix_appointments_customer_id"), "appointments", ["customer_id"], unique=False
    )
    op.create_index(
        op.f("ix_appointments_location_id"), "appointments", ["location_id"], unique=False
    )
    op.create_index(op.f("ix_appointments_starts_at"), "appointments", ["starts_at"], unique=False)
    op.create_table(
        "appointment_events",
        sa.Column("appointment_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("source", booking_source, nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_appointment_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "appointment_id"],
            ["appointments.business_id", "appointments.id"],
            name=op.f("fk_appointment_events_business_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_appointment_events_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_events")),
    )
    op.create_index(
        op.f("ix_appointment_events_appointment_id"),
        "appointment_events",
        ["appointment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_appointment_events_business_id"),
        "appointment_events",
        ["business_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_appointment_events_business_id"), table_name="appointment_events")
    op.drop_index(op.f("ix_appointment_events_appointment_id"), table_name="appointment_events")
    op.drop_table("appointment_events")
    op.drop_index(op.f("ix_appointments_starts_at"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_location_id"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_customer_id"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_business_id"), table_name="appointments")
    op.drop_table("appointments")
    op.drop_index(op.f("ix_customers_business_id"), table_name="customers")
    op.drop_table("customers")
    booking_source.drop(op.get_bind(), checkfirst=False)
    appointment_status.drop(op.get_bind(), checkfirst=False)
