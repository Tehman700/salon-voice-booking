"""Who may call what: every protected endpoint against every kind of caller."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from tests.helpers import Session, World, build_world, create_platform_admin, location_payload

Body = Callable[[World], dict[str, Any] | None]


def _no_body(_: World) -> None:
    return None


# method, path ("{downtown}" etc. are filled in per world), request body, roles allowed.
# Roles: owner / manager (of Downtown) / staff (of Downtown). Platform admins and anonymous callers
# are never allowed on business endpoints.
CASES: list[tuple[str, str, Body, set[str]]] = [
    ("GET", "/business", _no_body, {"owner", "manager", "staff"}),
    ("PATCH", "/business", lambda w: {"name": "Renamed"}, {"owner"}),
    ("GET", "/locations", _no_body, {"owner", "manager", "staff"}),
    ("POST", "/locations", lambda w: location_payload("Third"), {"owner"}),
    ("GET", "/locations/{downtown}", _no_body, {"owner", "manager"}),
    ("PATCH", "/locations/{downtown}", lambda w: {"city": "Karachi"}, {"owner", "manager"}),
    ("DELETE", "/locations/{uptown}", _no_body, {"owner"}),
    ("GET", "/users", _no_body, {"owner", "manager"}),
    (
        "POST",
        "/users/invite",
        lambda w: {
            "email": "new@alpha.example.com",
            "role": "staff",
            "location_id": w.downtown["id"],
        },
        {"owner", "manager"},
    ),
    ("PATCH", "/users/{staff}", lambda w: {"is_active": True}, {"owner"}),
]


def _fill(path: str, w: World) -> str:
    return path.format(downtown=w.downtown["id"], uptown=w.uptown["id"], staff=w.staff_a.id)


@pytest.mark.parametrize(("method", "path", "body", "allowed"), CASES, ids=lambda v: str(v)[:40])
async def test_endpoint_access_by_role(
    client: AsyncClient,
    db: AsyncSession,
    method: str,
    path: str,
    body: Body,
    allowed: set[str],
) -> None:
    w = await build_world(client)
    admin = await create_platform_admin(client, db)
    url, payload = _fill(path, w), body(w)

    async def call(headers: dict[str, str]) -> int:
        return (await client.request(method, url, json=payload, headers=headers)).status_code

    # Callers who must be refused, checked before any allowed caller changes state.
    assert await call({}) == 401, "anonymous"
    assert await call(admin.headers) == 403, "platform admin has no business"
    callers: list[tuple[str, Session]] = [
        ("staff", w.staff_a),
        ("manager", w.manager_a),
        ("owner", w.owner_a),
    ]
    for role, session in callers:
        status = await call(session.headers)
        if role in allowed:
            assert status < 300, f"{role} should be allowed on {method} {path}, got {status}"
        else:
            assert status == 403, f"{role} should be forbidden on {method} {path}, got {status}"


async def test_auth_me_works_for_every_role(client: AsyncClient, db: AsyncSession) -> None:
    w = await build_world(client)
    admin = await create_platform_admin(client, db)
    assert (await client.get("/auth/me")).status_code == 401
    for session in (w.owner_a, w.manager_a, w.staff_a, admin):
        assert (await client.get("/auth/me", headers=session.headers)).status_code == 200


PUBLIC_PATHS = {
    "/health",
    "/health/ready",
    "/auth/signup",
    "/auth/login",
    "/auth/refresh",
    "/auth/logout",
    "/auth/accept-invite",
}


def _protected_routes() -> list[tuple[str, str]]:
    """Every (method, path) in the OpenAPI schema except the deliberately public ones."""
    paths: dict[str, dict[str, object]] = create_app().openapi()["paths"]
    http_methods = {"get", "post", "put", "patch", "delete"}
    return [
        (method.upper(), path)
        for path, operations in sorted(paths.items())
        if path not in PUBLIC_PATHS
        for method in sorted(operations)
        if method in http_methods
    ]


def test_the_route_guard_actually_covers_the_api() -> None:
    covered = _protected_routes()
    assert len(covered) >= 10, covered
    assert ("GET", "/users") in covered
    assert ("PATCH", "/locations/{location_id}") in covered


@pytest.mark.parametrize(("method", "path"), _protected_routes(), ids=lambda v: str(v))
async def test_every_non_public_route_requires_authentication(
    client: AsyncClient, method: str, path: str
) -> None:
    """Guards against a future endpoint being added without authentication."""
    concrete = path.replace("{location_id}", str(uuid.uuid4())).replace(
        "{user_id}", str(uuid.uuid4())
    )
    assert "{" not in concrete, f"teach this test how to fill in {path}"
    response = await client.request(method, concrete)
    assert response.status_code == 401, f"{method} {path} is reachable without a token"
