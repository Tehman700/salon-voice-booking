"""Enable Postgres extensions used by the schema.

btree_gist: lets a GiST exclusion constraint mix `staff_id WITH =` and
`tstzrange(...) WITH &&`, which is how appointments are kept from overlapping.
citext: case-insensitive text for emails.

Revision ID: 0001
Revises:
Create Date: 2026-10-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
