import asyncio
import secrets

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.business import Business
from app.models.user import User
from app.scripts import seed as seed_module
from tests.helpers import login


async def test_seed_creates_a_usable_demo_business(client: AsyncClient, db: AsyncSession) -> None:
    assert await seed_module.seed(db, "demo-pass-123456") is True

    owner = await login(client, "owner@demo.example.com", "demo-pass-123456")
    manager = await login(client, "manager@demo.example.com", "demo-pass-123456")
    staff = await login(client, "staff@demo.example.com", "demo-pass-123456")

    assert owner.user["role"] == "owner"
    assert len(owner.location_ids) == 2
    assert len(manager.location_ids) == 1
    assert manager.location_ids == staff.location_ids
    business = (await client.get("/business", headers=owner.headers)).json()
    assert business["location_mode"] == "multiple"


async def test_seed_is_idempotent(db: AsyncSession) -> None:
    assert await seed_module.seed(db) is True
    assert await seed_module.seed(db) is False
    assert await db.scalar(select(func.count()).select_from(Business)) == 1
    assert await db.scalar(select(func.count()).select_from(User)) == 3


def test_seed_refuses_to_run_outside_local_environments() -> None:
    settings = get_settings()
    original = settings.environment
    settings.environment = "production"
    try:
        assert asyncio.run(seed_module.main()) == 1
    finally:
        settings.environment = original


def test_seed_command_creates_then_reports_existing(capsys: pytest.CaptureFixture[str]) -> None:
    assert asyncio.run(seed_module.main()) == 0
    first = capsys.readouterr().out
    assert "Created the demo business" in first
    assert "owner@demo.example.com" in first

    assert asyncio.run(seed_module.main()) == 0
    assert "already exists" in capsys.readouterr().out


def _main_in(
    environment: str, args: list[str], password: str | None, monkeypatch: pytest.MonkeyPatch
) -> int:
    settings = get_settings()
    original = settings.environment
    settings.environment = environment  # type: ignore[assignment]
    if password is None:
        monkeypatch.delenv("SEED_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("SEED_PASSWORD", password)
    try:
        return asyncio.run(seed_module.main(args))
    finally:
        settings.environment = original


def test_remote_seeding_needs_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _main_in("staging", [], secrets.token_urlsafe(16), monkeypatch) == 1


def test_remote_seeding_never_uses_the_public_default_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _main_in("staging", ["--allow-remote"], None, monkeypatch) == 1
    assert _main_in("staging", ["--allow-remote"], "short", monkeypatch) == 1


def test_remote_seeding_with_the_flag_and_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _main_in("staging", ["--allow-remote"], secrets.token_urlsafe(16), monkeypatch) == 0
