"""tenancy and auth tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31 13:23:39.148354

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Created once, up front: both `users` and `invites` use user_role, and a second CREATE TYPE
# inside create_table would fail.
location_mode = postgresql.ENUM("single", "multiple", name="location_mode", create_type=False)
user_role = postgresql.ENUM(
    "platform_admin", "owner", "manager", "staff", name="user_role", create_type=False
)


def upgrade() -> None:
    location_mode.create(op.get_bind(), checkfirst=False)
    user_role.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "businesses",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("location_mode", location_mode, nullable=False),
        sa.Column("default_timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "cancellation_window_minutes",
            sa.Integer(),
            server_default=sa.text("120"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            "cancellation_window_minutes >= 0",
            name=op.f("ck_businesses_cancellation_window_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_businesses")),
        sa.UniqueConstraint("slug", name=op.f("uq_businesses_slug")),
    )
    op.create_table(
        "locations",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("address_line1", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("cancellation_window_minutes", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "cancellation_window_minutes IS NULL OR cancellation_window_minutes >= 0",
            name=op.f("ck_locations_cancellation_window_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_locations_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
        sa.UniqueConstraint("business_id", "id", name=op.f("uq_locations_business_id_id")),
        sa.UniqueConstraint("business_id", "slug", name=op.f("uq_locations_business_id_slug")),
    )
    op.create_index(op.f("ix_locations_business_id"), "locations", ["business_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("business_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column(
            "role",
            user_role,
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            "(role = 'platform_admin' AND business_id IS NULL AND location_id IS NULL) OR (role = 'owner' AND business_id IS NOT NULL AND location_id IS NULL) OR (role IN ('manager', 'staff') AND business_id IS NOT NULL AND location_id IS NOT NULL)",
            name=op.f("ck_users_role_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "location_id"],
            ["locations.business_id", "locations.id"],
            name=op.f("fk_users_business_id_locations"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_users_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_business_id"), "users", ["business_id"], unique=False)
    op.create_table(
        "invites",
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column(
            "role",
            user_role,
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(role = 'owner' AND location_id IS NULL) OR (role IN ('manager', 'staff') AND location_id IS NOT NULL)",
            name=op.f("ck_invites_role_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id", "location_id"],
            ["locations.business_id", "locations.id"],
            name=op.f("fk_invites_business_id_locations"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_invites_business_id_businesses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_invites_invited_by_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )
    op.create_index(op.f("ix_invites_business_id"), "invites", ["business_id"], unique=False)
    op.create_index(op.f("ix_invites_email"), "invites", ["email"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_invites_email"), table_name="invites")
    op.drop_index(op.f("ix_invites_business_id"), table_name="invites")
    op.drop_table("invites")
    op.drop_index(op.f("ix_users_business_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_locations_business_id"), table_name="locations")
    op.drop_table("locations")
    op.drop_table("businesses")

    user_role.drop(op.get_bind(), checkfirst=False)
    location_mode.drop(op.get_bind(), checkfirst=False)
