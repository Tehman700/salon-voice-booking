from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.session import get_session
from app.main import create_app


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": None}


async def test_readiness_with_database(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_readiness_reports_unreachable_database() -> None:
    # Port 1 is never a Postgres server, so the connection attempt fails fast.
    dead_engine = create_async_engine("postgresql+asyncpg://nobody:x@127.0.0.1:1/none")

    async def dead_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(dead_engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = dead_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health/ready")
    await dead_engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}


async def test_cors_allows_configured_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_cors_rejects_unknown_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers
