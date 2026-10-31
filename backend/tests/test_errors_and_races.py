"""Error response shapes, and races between simultaneous requests."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.errors import ForbiddenError
from app.core.principal import Principal
from app.models.user import Role, User
from app.schemas.user import InviteRequest
from app.services import users as users_service
from tests.helpers import (
    PASSWORD,
    REFRESH_COOKIE,
    accept_invite,
    invite,
    location_payload,
    login,
    signup,
)

# --- Error shapes ---


async def test_unknown_route_uses_the_standard_error_shape(client: AsyncClient) -> None:
    response = await client.get("/no/such/route")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


async def test_wrong_method_uses_the_standard_error_shape(client: AsyncClient) -> None:
    response = await client.put("/auth/login")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_malformed_json_is_a_validation_error(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/login", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_invalid_path_parameter_is_a_validation_error(client: AsyncClient) -> None:
    owner = await signup(client)
    response = await client.get("/locations/not-a-uuid", headers=owner.headers)
    assert response.status_code == 422
    assert "location_id" in response.json()["error"]["details"]


async def test_validation_details_map_each_field_to_its_messages(client: AsyncClient) -> None:
    response = await client.post("/auth/login", json={"email": "nope", "password": ""})
    details = response.json()["error"]["details"]
    assert set(details) == {"email", "password"}
    assert all(isinstance(messages, list) and messages for messages in details.values())


async def test_error_responses_never_leak_internals(client: AsyncClient) -> None:
    response = await client.post("/auth/login", json={"email": "a@example.com", "password": "x"})
    text = response.text.lower()
    assert "traceback" not in text
    assert "sqlalchemy" not in text


async def test_the_openapi_schema_documents_the_error_shape(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert "ErrorResponse" in schema["components"]["schemas"]
    login_responses = schema["paths"]["/auth/login"]["post"]["responses"]
    assert "401" in login_responses


# --- Password hash upgrades ---


async def test_login_upgrades_outdated_password_hashes(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client, email="olivia@glow.example.com")
    before = await db.scalar(select(User.password_hash))
    assert before is not None and "m=8,t=1" in before

    stronger = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=16, parallelism=1),))
    monkeypatch.setattr(security, "_password_hasher", lambda: stronger)
    await login(client, "olivia@glow.example.com")

    after = await db.scalar(select(User.password_hash))
    assert after is not None and "m=16,t=2" in after
    # The upgraded hash keeps working.
    assert (await login(client, "olivia@glow.example.com")).user["role"] == "owner"


# --- Races ---


async def test_concurrent_signups_with_the_same_business_name_all_succeed(
    client: AsyncClient,
) -> None:
    def payload(i: int) -> dict[str, object]:
        return {
            "business_name": "Glow Salon",
            "owner_full_name": f"Owner {i}",
            "email": f"owner{i}@glow.example.com",
            "password": PASSWORD,
            "location_mode": "single",
            "locations": [location_payload()],
        }

    results = await asyncio.gather(
        *(client.post("/auth/signup", json=payload(i)) for i in range(4))
    )
    assert [r.status_code for r in results] == [201, 201, 201, 201]
    slugs = set()
    for r in results:
        token = r.json()["access_token"]
        slugs.add(
            (await client.get("/business", headers={"Authorization": f"Bearer {token}"})).json()[
                "slug"
            ]
        )
    assert len(slugs) == 4  # glow-salon, glow-salon-2, ...


async def test_concurrent_location_creation_with_the_same_name_gets_distinct_slugs(
    client: AsyncClient,
) -> None:
    owner = await signup(client)
    results = await asyncio.gather(
        *(
            client.post("/locations", json=location_payload("Uptown"), headers=owner.headers)
            for _ in range(4)
        )
    )
    assert [r.status_code for r in results] == [201, 201, 201, 201]
    assert len({r.json()["slug"] for r in results}) == 4


async def test_an_invitation_cannot_be_accepted_twice_at_once(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = await signup(client)
    invited = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    token = invited.json()["token"]
    results = await asyncio.gather(*(accept_invite(client, token) for _ in range(3)))
    assert sorted(r.status_code for r in results) == [200, 400, 400]
    assert (
        len((await db.scalars(select(User.id).where(User.email == "sam@glow.example.com"))).all())
        == 1
    )


async def test_logout_with_an_unknown_token_is_still_a_success(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/logout", headers={"Cookie": f"{REFRESH_COOKIE}=never-issued"}
    )
    assert response.status_code == 204


# --- Defence in depth ---


async def test_the_service_layer_refuses_staff_even_if_the_route_guard_is_bypassed(
    db: AsyncSession,
) -> None:
    staff = Principal(
        user_id=uuid.uuid4(), business_id=uuid.uuid4(), role=Role.staff, location_id=uuid.uuid4()
    )
    with pytest.raises(ForbiddenError):
        await users_service.create_invite(
            db,
            staff,
            InviteRequest(email="x@example.com", role=Role.staff, location_id=uuid.uuid4()),
        )
