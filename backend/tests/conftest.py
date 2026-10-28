"""Shared fixtures. Tests run against a real PostgreSQL database (TEST_DATABASE_URL).

Inside a Claude worktree (.claude/worktrees/<name>/) the database name gets a `_<name>`
suffix, so parallel sessions never wipe each other's test database.
"""

import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _test_database_url() -> str:
    url = make_url(
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+asyncpg://salon:salon@localhost:5544/salon_test"
        )
    )
    parts = BACKEND_DIR.parts
    for i in range(len(parts) - 2):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees":
            suffix = re.sub(r"[^a-z0-9]+", "_", parts[i + 2].lower()).strip("_")
            url = url.set(database=f"{url.database}_{suffix}")
            break
    return url.render_as_string(hide_password=False)


TEST_DATABASE_URL = _test_database_url()
# Must be set before the app reads its settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"

import asyncio  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    return cfg


async def _ensure_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    await admin.dispose()


async def _reset_schema() -> None:
    await _ensure_database()
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Start every test session from an empty schema migrated to head."""
    get_settings.cache_clear()
    asyncio.run(_reset_schema())
    command.upgrade(alembic_config(), "head")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
