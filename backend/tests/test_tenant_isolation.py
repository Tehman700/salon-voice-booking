"""Cross-tenant isolation: one business must never see or change another's data.

Later modules (services, staff, bookings, ...) must extend these tests with their own endpoints.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.business import Business, LocationMode
from app.models.invite import Invite
from app.models.location import Location
from app.models.user import Role, User
from tests.helpers import PASSWORD, World, bearer, build_world


def _attacks_on_business_b(w: World) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Every request that targets business B's resources by id."""
    return [
        ("GET", f"/locations/{w.location_b['id']}", None),
        ("PATCH", f"/locations/{w.location_b['id']}", {"name": "pwned"}),
        ("PATCH", f"/locations/{w.location_b['id']}", {"is_active": False}),
        ("DELETE", f"/locations/{w.location_b['id']}", None),
        ("PATCH", f"/users/{w.owner_b.id}", {"is_active": False}),
        ("PATCH", f"/users/{w.owner_b.id}", {"role": "staff", "location_id": w.location_b["id"]}),
        (
            "POST",
            "/users/invite",
            {
                "email": "intruder@evil.example.com",
                "role": "staff",
                "location_id": w.location_b["id"],
            },
        ),
    ]


async def _assert_business_b_untouched(client: AsyncClient, w: World) -> None:
    location = (
        await client.get(f"/locations/{w.location_b['id']}", headers=w.owner_b.headers)
    ).json()
    assert location["name"] == "Main Street"
    assert location["is_active"] is True
    users = (await client.get("/users", headers=w.owner_b.headers)).json()["items"]
    assert [(u["email"], u["role"], u["is_active"]) for u in users] == [
        ("owner@beta.example.com", "owner", True)
    ]


async def test_owner_of_another_business_gets_404_everywhere(client: AsyncClient) -> None:
    w = await build_world(client)
    for method, path, body in _attacks_on_business_b(w):
        response = await client.request(method, path, json=body, headers=w.owner_a.headers)
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["error"]["code"] == "not_found"
    await _assert_business_b_untouched(client, w)


@pytest.mark.parametrize("actor", ["manager_a", "staff_a", "manager_a_uptown"])
async def test_lower_roles_of_another_business_never_succeed(
    client: AsyncClient, actor: str
) -> None:
    w = await build_world(client)
    session = getattr(w, actor)
    for method, path, body in _attacks_on_business_b(w):
        response = await client.request(method, path, json=body, headers=session.headers)
        assert response.status_code in (403, 404), (actor, method, path, response.text)
    await _assert_business_b_untouched(client, w)


async def test_the_other_direction_is_isolated_too(client: AsyncClient) -> None:
    w = await build_world(client)
    attacks = [
        ("GET", f"/locations/{w.downtown['id']}", None),
        ("PATCH", f"/locations/{w.downtown['id']}", {"name": "pwned"}),
        ("DELETE", f"/locations/{w.uptown['id']}", None),
        ("PATCH", f"/users/{w.staff_a.id}", {"is_active": False}),
        ("PATCH", f"/users/{w.owner_a.id}", {"is_active": False}),
    ]
    for method, path, body in attacks:
        response = await client.request(method, path, json=body, headers=w.owner_b.headers)
        assert response.status_code == 404, (method, path)
    assert (await client.get("/auth/me", headers=w.staff_a.headers)).status_code == 200
    names = [
        loc["name"]
        for loc in (await client.get("/locations", headers=w.owner_a.headers)).json()["items"]
    ]
    assert sorted(names) == ["Downtown", "Uptown"]


async def test_listings_never_include_another_business(client: AsyncClient) -> None:
    w = await build_world(client)
    a_locations = (await client.get("/locations", headers=w.owner_a.headers)).json()["items"]
    b_locations = (await client.get("/locations", headers=w.owner_b.headers)).json()["items"]
    assert w.location_b["id"] not in {loc["id"] for loc in a_locations}
    assert {w.downtown["id"], w.uptown["id"]}.isdisjoint({loc["id"] for loc in b_locations})

    a_users = (await client.get("/users", headers=w.owner_a.headers)).json()["items"]
    assert all(u["email"].endswith("@alpha.example.com") for u in a_users)
    assert w.owner_b.id not in {u["id"] for u in a_users}


async def test_a_pagination_cursor_cannot_be_used_to_reach_other_tenants(
    client: AsyncClient,
) -> None:
    w = await build_world(client)
    first_page = (await client.get("/users", params={"limit": 1}, headers=w.owner_a.headers)).json()
    assert first_page["next_cursor"]
    # Replaying A's cursor as B only ever yields B's own users.
    as_b = await client.get(
        "/users", params={"cursor": first_page["next_cursor"]}, headers=w.owner_b.headers
    )
    assert as_b.status_code == 200
    assert all(u["email"].endswith("@beta.example.com") for u in as_b.json()["items"])


async def test_token_claims_are_not_trusted_for_the_business(client: AsyncClient) -> None:
    """A token naming business B but belonging to a user of A still resolves to A."""
    w = await build_world(client)
    me_b = (await client.get("/auth/me", headers=w.owner_b.headers)).json()
    settings = get_settings()
    assert settings.jwt_secret is not None
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": w.owner_a.id,
            "bid": me_b["business"]["id"],
            "role": "owner",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    business = (await client.get("/business", headers=bearer(forged))).json()
    assert business["name"] == "Alpha Salons"
    assert business["id"] != me_b["business"]["id"]


async def test_role_claim_in_the_token_is_not_trusted(client: AsyncClient) -> None:
    w = await build_world(client)
    settings = get_settings()
    assert settings.jwt_secret is not None
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": w.staff_a.id,
            "role": "owner",  # claims to be an owner; the database says staff
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    assert (
        await client.patch("/business", json={"name": "x"}, headers=bearer(forged))
    ).status_code == 403


# --- The database enforces the same rules, independent of application code ---


async def _ids(client: AsyncClient) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    w = await build_world(client)
    b_business = (await client.get("/business", headers=w.owner_b.headers)).json()["id"]
    a_business = (await client.get("/business", headers=w.owner_a.headers)).json()["id"]
    return (
        uuid.UUID(a_business),
        uuid.UUID(b_business),
        uuid.UUID(w.downtown["id"]),
        uuid.UUID(w.location_b["id"]),
    )


def _user(**overrides: Any) -> User:
    values: dict[str, Any] = {
        "email": f"{uuid.uuid4().hex}@db.example.com",
        "password_hash": hash_password(PASSWORD),
        "full_name": "DB Test",
        "role": Role.staff,
    }
    values.update(overrides)
    return User(**values)


async def test_db_rejects_a_user_pointing_at_another_businesss_location(
    client: AsyncClient, db: AsyncSession
) -> None:
    _a_business, b_business, a_location, _ = await _ids(client)
    db.add(_user(business_id=b_business, location_id=a_location))
    with pytest.raises(IntegrityError, match="fk_users_business_id_locations"):
        await db.commit()


async def test_db_rejects_an_invite_for_another_businesss_location(
    client: AsyncClient, db: AsyncSession
) -> None:
    _a_business, b_business, a_location, _ = await _ids(client)
    inviter = await db.scalar(select(User).where(User.business_id == b_business))
    assert inviter is not None
    db.add(
        Invite(
            business_id=b_business,
            location_id=a_location,
            email="x@db.example.com",
            role=Role.staff,
            token_hash=uuid.uuid4().hex * 2,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            invited_by=inviter.id,
        )
    )
    with pytest.raises(IntegrityError, match="fk_invites_business_id_locations"):
        await db.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"role": Role.manager, "location_id": None},  # manager must have a location
        {"role": Role.staff, "location_id": None},
        {"role": Role.owner, "with_location": True},  # owner must not have one
        {"role": Role.platform_admin, "with_business": True},  # platform admin has no business
        {"role": Role.owner, "business_id": None},  # tenant users must have a business
    ],
    ids=[
        "manager-no-location",
        "staff-no-location",
        "owner-with-location",
        "admin-with-business",
        "owner-no-business",
    ],
)
async def test_db_rejects_inconsistent_role_scope(
    client: AsyncClient, db: AsyncSession, overrides: dict[str, Any]
) -> None:
    a_business, _, a_location, _ = await _ids(client)
    values = dict(overrides)
    if values.pop("with_location", False):
        values["business_id"], values["location_id"] = a_business, a_location
    elif values.pop("with_business", False):
        values["business_id"] = a_business
    else:
        values.setdefault("business_id", a_business)
    db.add(_user(**values))
    with pytest.raises(IntegrityError, match="role_scope"):
        await db.commit()


async def test_db_email_is_unique_ignoring_case(client: AsyncClient, db: AsyncSession) -> None:
    a_business, _, a_location, _ = await _ids(client)
    db.add(_user(email="OWNER@ALPHA.EXAMPLE.COM", business_id=a_business, location_id=a_location))
    with pytest.raises(IntegrityError, match="uq_users_email"):
        await db.commit()


async def test_db_location_slugs_are_unique_per_business_only(
    client: AsyncClient, db: AsyncSession
) -> None:
    _a_business, b_business, _, _ = await _ids(client)
    # Same slug in a business that doesn't have it yet: fine.
    db.add(Location(business_id=b_business, name="Downtown", slug="downtown", timezone="UTC"))
    await db.commit()
    # Same slug twice in one business: rejected.
    db.add(Location(business_id=b_business, name="Downtown 2", slug="downtown", timezone="UTC"))
    with pytest.raises(IntegrityError, match="uq_locations_business_id_slug"):
        await db.commit()


async def test_db_rejects_negative_cancellation_windows(
    client: AsyncClient, db: AsyncSession
) -> None:
    a_business, _, _, _ = await _ids(client)
    db.add(
        Location(
            business_id=a_business,
            name="Bad",
            slug="bad",
            timezone="UTC",
            cancellation_window_minutes=-5,
        )
    )
    with pytest.raises(IntegrityError, match="cancellation_window_non_negative"):
        await db.commit()
    await db.rollback()
    db.add(
        Business(
            name="Bad",
            slug="bad",
            location_mode=LocationMode.single,
            default_timezone="UTC",
            cancellation_window_minutes=-1,
        )
    )
    with pytest.raises(IntegrityError, match="cancellation_window_non_negative"):
        await db.commit()


async def test_deleting_a_business_removes_all_its_data_and_nothing_else(
    client: AsyncClient, db: AsyncSession
) -> None:
    w = await build_world(client)
    a_business = uuid.UUID((await client.get("/business", headers=w.owner_a.headers)).json()["id"])
    business = await db.get(Business, a_business)
    assert business is not None
    await db.delete(business)
    await db.commit()

    assert (await client.get("/auth/me", headers=w.owner_a.headers)).status_code == 401
    assert (await client.get("/auth/me", headers=w.owner_b.headers)).status_code == 200
