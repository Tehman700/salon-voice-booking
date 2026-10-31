import asyncio
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invite import Invite
from app.models.user import User
from tests.helpers import (
    PASSWORD,
    accept_invite,
    build_world,
    create_location,
    invite,
    join_team,
    login,
    refresh,
    signup,
)

# --- Listing ---


async def test_owner_sees_the_whole_team_and_manager_only_their_location(
    client: AsyncClient,
) -> None:
    w = await build_world(client)

    owner_view = (await client.get("/users", headers=w.owner_a.headers)).json()["items"]
    manager_view = (await client.get("/users", headers=w.manager_a.headers)).json()["items"]

    assert {u["email"] for u in owner_view} == {
        "owner@alpha.example.com",
        "manager@alpha.example.com",
        "staff@alpha.example.com",
        "uptown@alpha.example.com",
    }
    assert {u["email"] for u in manager_view} == {
        "manager@alpha.example.com",
        "staff@alpha.example.com",
    }
    assert set(owner_view[0]) == {
        "id",
        "email",
        "full_name",
        "role",
        "location_id",
        "is_active",
        "last_login_at",
    }


async def test_staff_cannot_list_users(client: AsyncClient) -> None:
    w = await build_world(client)
    assert (await client.get("/users", headers=w.staff_a.headers)).status_code == 403


async def test_users_are_paginated_without_gaps_or_repeats(client: AsyncClient) -> None:
    owner = await signup(client)
    for i in range(6):
        await join_team(
            client,
            owner,
            email=f"staff{i}@glow.example.com",
            role="staff",
            location_id=owner.location_ids[0],
        )

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/users", params=params, headers=owner.headers)).json()
        seen.extend(u["email"] for u in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert pages == 3  # 7 users, 3 per page
    assert len(seen) == len(set(seen)) == 7


async def test_user_list_rejects_bad_limit_and_cursor(client: AsyncClient) -> None:
    owner = await signup(client)
    for params in ({"limit": 0}, {"limit": 201}):
        assert (await client.get("/users", params=params, headers=owner.headers)).status_code == 422
    bad_cursor = await client.get("/users", params={"cursor": "garbage"}, headers=owner.headers)
    assert bad_cursor.status_code == 422
    assert "cursor" in bad_cursor.json()["error"]["details"]


# --- Inviting ---


async def test_owner_can_invite_each_role(client: AsyncClient) -> None:
    owner = await signup(client)
    location_id = owner.location_ids[0]
    cases = [
        ("owner2@glow.example.com", "owner", None),
        ("manager@glow.example.com", "manager", location_id),
        ("staff@glow.example.com", "staff", location_id),
    ]
    for email, role, loc in cases:
        response = await invite(client, owner, email=email, role=role, location_id=loc)
        assert response.status_code == 201, response.text
        body = response.json()
        assert (body["email"], body["role"], body["location_id"]) == (email, role, loc)
        assert body["token"]
        assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)


async def test_manager_can_invite_staff_to_their_own_location_only(client: AsyncClient) -> None:
    w = await build_world(client)

    ok = await invite(
        client,
        w.manager_a,
        email="new@alpha.example.com",
        role="staff",
        location_id=w.downtown["id"],
    )
    assert ok.status_code == 201
    # Omitting the location defaults to the manager's own.
    default_location = await invite(
        client, w.manager_a, email="new2@alpha.example.com", role="staff"
    )
    assert default_location.status_code == 201
    assert default_location.json()["location_id"] == w.downtown["id"]

    wrong_role = await invite(
        client,
        w.manager_a,
        email="boss@alpha.example.com",
        role="manager",
        location_id=w.downtown["id"],
    )
    assert wrong_role.status_code == 403

    owner_role = await invite(client, w.manager_a, email="boss2@alpha.example.com", role="owner")
    assert owner_role.status_code == 403

    other_branch = await invite(
        client,
        w.manager_a,
        email="elsewhere@alpha.example.com",
        role="staff",
        location_id=w.uptown["id"],
    )
    assert other_branch.status_code == 404


async def test_staff_cannot_invite(client: AsyncClient) -> None:
    w = await build_world(client)
    response = await invite(
        client,
        w.staff_a,
        email="friend@alpha.example.com",
        role="staff",
        location_id=w.downtown["id"],
    )
    assert response.status_code == 403


async def test_invite_validation(client: AsyncClient) -> None:
    owner = await signup(client)
    location_id = owner.location_ids[0]

    owner_with_location = await invite(
        client, owner, email="a@glow.example.com", role="owner", location_id=location_id
    )
    assert owner_with_location.status_code == 422
    assert "location_id" in owner_with_location.json()["error"]["details"]

    staff_without_location = await invite(client, owner, email="b@glow.example.com", role="staff")
    assert staff_without_location.status_code == 422

    platform_admin = await invite(client, owner, email="c@glow.example.com", role="platform_admin")
    assert platform_admin.status_code == 422

    unknown_location = await invite(
        client, owner, email="d@glow.example.com", role="staff", location_id=str(uuid.uuid4())
    )
    assert unknown_location.status_code == 404

    bad_email = await invite(client, owner, email="nope", role="owner")
    assert bad_email.status_code == 422


async def test_cannot_invite_an_existing_user(client: AsyncClient) -> None:
    owner = await signup(client, email="olivia@glow.example.com")
    response = await invite(client, owner, email="OLIVIA@glow.example.com", role="owner")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_a_new_invitation_supersedes_the_previous_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = await signup(client)
    location_id = owner.location_ids[0]
    first = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=location_id
    )
    second = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=location_id
    )
    assert (await accept_invite(client, first.json()["token"])).status_code == 400
    assert (await accept_invite(client, second.json()["token"])).status_code == 200
    assert len((await db.scalars(select(Invite.id))).all()) == 2


async def test_invite_token_is_hidden_when_not_exposed(
    client: AsyncClient, monkeypatch: object
) -> None:
    from app.core.config import get_settings

    owner = await signup(client)
    settings = get_settings()
    original = settings.expose_invite_tokens
    settings.expose_invite_tokens = False
    try:
        response = await invite(client, owner, email="sam@glow.example.com", role="owner")
    finally:
        settings.expose_invite_tokens = original
    assert response.status_code == 201
    assert response.json()["token"] is None


# --- Updating users ---


async def test_owner_changes_role_and_location(client: AsyncClient) -> None:
    w = await build_world(client)
    response = await client.patch(
        f"/users/{w.staff_a.id}",
        json={"role": "manager", "location_id": w.uptown["id"]},
        headers=w.owner_a.headers,
    )
    assert response.status_code == 200
    assert response.json()["role"] == "manager"
    assert response.json()["location_id"] == w.uptown["id"]

    me = (await client.get("/auth/me", headers=w.staff_a.headers)).json()
    assert me["role"] == "manager"  # takes effect on the very next request
    assert me["location_ids"] == [w.uptown["id"]]


async def test_promoting_to_owner_drops_the_location(client: AsyncClient) -> None:
    w = await build_world(client)
    response = await client.patch(
        f"/users/{w.manager_a.id}", json={"role": "owner"}, headers=w.owner_a.headers
    )
    assert response.status_code == 200
    assert response.json()["role"] == "owner"
    assert response.json()["location_id"] is None
    me = (await client.get("/auth/me", headers=w.manager_a.headers)).json()
    assert sorted(me["location_ids"]) == sorted([w.downtown["id"], w.uptown["id"]])


async def test_user_update_validation(client: AsyncClient) -> None:
    w = await build_world(client)
    url = f"/users/{w.staff_a.id}"

    owner_with_location = await client.patch(
        url,
        json={"role": "owner", "location_id": w.downtown["id"]},
        headers=w.owner_a.headers,
    )
    assert owner_with_location.status_code == 422

    clearing_location = await client.patch(
        url, json={"location_id": None}, headers=w.owner_a.headers
    )
    assert clearing_location.status_code == 422  # staff must keep a location

    unknown_location = await client.patch(
        url, json={"location_id": str(uuid.uuid4())}, headers=w.owner_a.headers
    )
    assert unknown_location.status_code == 404

    platform_admin = await client.patch(
        url, json={"role": "platform_admin"}, headers=w.owner_a.headers
    )
    assert platform_admin.status_code == 422


async def test_only_owners_can_update_users(client: AsyncClient) -> None:
    w = await build_world(client)
    for session in (w.manager_a, w.staff_a):
        response = await client.patch(
            f"/users/{w.staff_a.id}", json={"is_active": False}, headers=session.headers
        )
        assert response.status_code == 403


async def test_deactivating_a_user_ends_all_their_sessions(client: AsyncClient) -> None:
    w = await build_world(client)
    response = await client.patch(
        f"/users/{w.staff_a.id}", json={"is_active": False}, headers=w.owner_a.headers
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    assert (await client.get("/auth/me", headers=w.staff_a.headers)).status_code == 401
    assert (await refresh(client, w.staff_a.refresh_token)).status_code == 401
    failed_login = await client.post(
        "/auth/login", json={"email": "staff@alpha.example.com", "password": PASSWORD}
    )
    assert failed_login.status_code == 401

    reactivated = await client.patch(
        f"/users/{w.staff_a.id}", json={"is_active": True}, headers=w.owner_a.headers
    )
    assert reactivated.status_code == 200
    assert (await login(client, "staff@alpha.example.com")).user["role"] == "staff"


async def test_the_last_active_owner_cannot_be_removed(client: AsyncClient) -> None:
    owner = await signup(client)
    for payload in (
        {"is_active": False},
        {"role": "manager", "location_id": owner.location_ids[0]},
    ):
        response = await client.patch(f"/users/{owner.id}", json=payload, headers=owner.headers)
        assert response.status_code == 409, payload
        assert response.json()["error"]["code"] == "last_owner"


async def test_a_second_owner_makes_demotion_possible(client: AsyncClient) -> None:
    owner = await signup(client)
    second = await join_team(client, owner, email="partner@glow.example.com", role="owner")
    response = await client.patch(
        f"/users/{owner.id}",
        json={"role": "manager", "location_id": owner.location_ids[0]},
        headers=second.headers,
    )
    assert response.status_code == 200


async def test_two_owners_cannot_remove_each_other_at_the_same_time(
    client: AsyncClient, db: AsyncSession
) -> None:
    first = await signup(client)
    second = await join_team(client, first, email="partner@glow.example.com", role="owner")
    results = await asyncio.gather(
        client.patch(f"/users/{second.id}", json={"is_active": False}, headers=first.headers),
        client.patch(f"/users/{first.id}", json={"is_active": False}, headers=second.headers),
    )
    codes = sorted(r.status_code for r in results)
    assert codes in ([200, 409], [200, 401])  # the loser is either refused or already signed out
    active_owners = await db.scalars(select(User.id).where(User.is_active.is_(True)))
    assert len(active_owners.all()) == 1


async def test_location_created_later_is_assignable(client: AsyncClient) -> None:
    owner = await signup(client)
    staff = await join_team(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    uptown = await create_location(client, owner, "Uptown")
    moved = await client.patch(
        f"/users/{staff.id}", json={"location_id": uptown["id"]}, headers=owner.headers
    )
    assert moved.status_code == 200
    assert moved.json()["location_id"] == uptown["id"]
