import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.conftest import TEST_DATABASE_URL, alembic_config


async def _installed_extensions() -> set[str]:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT extname FROM pg_extension"))
        names = {row[0] for row in rows}
    await engine.dispose()
    return names


def test_required_extensions_installed() -> None:
    assert {"btree_gist", "citext"} <= asyncio.run(_installed_extensions())


def test_models_match_migrations() -> None:
    """Fails if a model changed without a matching Alembic migration."""
    command.check(alembic_config())


def test_downgrade_and_upgrade_roundtrip() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert {"btree_gist", "citext"} <= asyncio.run(_installed_extensions())
