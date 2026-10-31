import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.invite import Invite
from app.models.refresh_token import RefreshToken
from app.models.user import User
from tests.helpers import (
    PASSWORD,
    REFRESH_COOKIE,
    accept_invite,
    bearer,
    create_platform_admin,
    invite,
    join_team,
    location_payload,
    login,
    refresh,
    signup,
)


def _forge_token(user_id: str, **overrides: object) -> str:
    """A well-formed access token, signed with the real secret unless told otherwise."""
    settings = get_settings()
    assert settings.jwt_secret is not None
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": user_id,
        "bid": None,
        "role": "owner",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": uuid.uuid4().hex,
    }
    claims.update(overrides)
    secret = str(overrides.get("_secret", settings.jwt_secret.get_secret_value()))
    claims.pop("_secret", None)
    return jwt.encode(claims, secret, algorithm="HS256")


# --- Sign-up ---


async def test_signup_single_location(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/signup",
        json={
            "business_name": "Glow Salon",
            "owner_full_name": "Olivia Owner",
            "email": "olivia@glow.example.com",
            "password": PASSWORD,
            "location_mode": "single",
            "locations": [location_payload("Main Street")],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    user = body["user"]
    assert user["role"] == "owner"
    assert user["email"] == "olivia@glow.example.com"
    assert user["business"]["name"] == "Glow Salon"
    assert user["business"]["location_mode"] == "single"
    assert len(user["location_ids"]) == 1

    business = await client.get("/business", headers=bearer(body["access_token"]))
    assert business.json()["cancellation_window_minutes"] == 120  # the default policy
    assert business.json()["default_timezone"] == "Asia/Karachi"


async def test_signup_sets_a_hardened_refresh_cookie(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/signup",
        json={
            "business_name": "Glow Salon",
            "owner_full_name": "Olivia Owner",
            "email": "olivia@glow.example.com",
            "password": PASSWORD,
            "location_mode": "single",
            "locations": [location_payload()],
        },
    )
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f"{REFRESH_COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/auth" in cookie
    assert f"max-age={30 * 24 * 60 * 60}" in cookie
    assert "secure" not in cookie  # test environment is plain http


async def test_signup_multiple_locations_with_duplicate_names_get_unique_slugs(
    client: AsyncClient,
) -> None:
    owner = await signup(
        client,
        mode="multiple",
        locations=[location_payload("Main"), location_payload("Main"), location_payload("Main")],
    )
    assert len(owner.location_ids) == 3
    listing = await client.get("/locations", headers=owner.headers)
    assert sorted(loc["slug"] for loc in listing.json()["items"]) == ["main", "main-2", "main-3"]


async def test_two_businesses_with_the_same_name_get_unique_slugs(client: AsyncClient) -> None:
    first = await signup(client, business_name="Glow", email="a@glow.example.com")
    second = await signup(client, business_name="Glow", email="b@glow.example.com")
    slugs = []
    for owner in (first, second):
        slugs.append((await client.get("/business", headers=owner.headers)).json()["slug"])
    assert slugs == ["glow", "glow-2"]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"password": "short"}, "password"),
        ({"email": "not-an-email"}, "email"),
        ({"business_name": "   "}, "business_name"),
        ({"locations": []}, "locations"),
        ({"locations": [{"name": "A", "timezone": "Mars/Olympus"}]}, "locations.0.timezone"),
        (
            {"locations": [{"name": "A", "timezone": "UTC", "phone": "0300123"}]},
            "locations.0.phone",
        ),
        ({"locations": [{"name": "A", "timezone": "UTC", "country": "pk"}]}, "locations.0.country"),
        ({"location_mode": "chain"}, "location_mode"),
    ],
)
async def test_signup_validation_errors(
    client: AsyncClient, overrides: dict[str, object], field: str
) -> None:
    payload: dict[str, object] = {
        "business_name": "Glow Salon",
        "owner_full_name": "Olivia Owner",
        "email": "olivia@glow.example.com",
        "password": PASSWORD,
        "location_mode": "single",
        "locations": [location_payload()],
    }
    payload.update(overrides)
    response = await client.post("/auth/signup", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert field in error["details"]


async def test_signup_single_mode_rejects_several_locations(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/signup",
        json={
            "business_name": "Glow Salon",
            "owner_full_name": "Olivia Owner",
            "email": "olivia@glow.example.com",
            "password": PASSWORD,
            "location_mode": "single",
            "locations": [location_payload("A"), location_payload("B")],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_signup_duplicate_email_is_a_conflict_regardless_of_case(
    client: AsyncClient,
) -> None:
    await signup(client, email="olivia@glow.example.com")
    response = await client.post(
        "/auth/signup",
        json={
            "business_name": "Another",
            "owner_full_name": "Someone Else",
            "email": "OLIVIA@Glow.Example.com",
            "password": PASSWORD,
            "location_mode": "single",
            "locations": [location_payload()],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_signup_stores_an_argon2_hash_never_the_password(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client, email="olivia@glow.example.com")
    stored = await db.scalar(select(User.password_hash))
    assert stored is not None
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


async def test_concurrent_signups_with_one_email_create_exactly_one_account(
    client: AsyncClient, db: AsyncSession
) -> None:
    payload = {
        "business_name": "Glow Salon",
        "owner_full_name": "Olivia Owner",
        "email": "olivia@glow.example.com",
        "password": PASSWORD,
        "location_mode": "single",
        "locations": [location_payload()],
    }
    results = await asyncio.gather(*(client.post("/auth/signup", json=payload) for _ in range(5)))
    assert sorted(r.status_code for r in results) == [201, 409, 409, 409, 409]
    assert len((await db.scalars(select(User.id))).all()) == 1


# --- Login ---


async def test_login_success(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, email="olivia@glow.example.com")
    session = await login(client, "OLIVIA@glow.example.com")  # case-insensitive
    assert session.user["email"] == "olivia@glow.example.com"
    assert session.refresh_token
    assert await db.scalar(select(User.last_login_at)) is not None


async def test_login_failures_are_indistinguishable(client: AsyncClient, db: AsyncSession) -> None:
    owner = await signup(client, email="olivia@glow.example.com")
    staff = await join_team(
        client,
        owner,
        email="sam@glow.example.com",
        role="staff",
        location_id=owner.location_ids[0],
    )
    await db.execute(update(User).where(User.id == uuid.UUID(staff.id)).values(is_active=False))
    await db.commit()

    attempts = [
        ("olivia@glow.example.com", "wrong-password-1"),  # wrong password
        ("nobody@glow.example.com", PASSWORD),  # unknown email
        ("sam@glow.example.com", PASSWORD),  # correct password, deactivated account
    ]
    responses = [
        await client.post("/auth/login", json={"email": e, "password": p}) for e, p in attempts
    ]
    assert all(r.status_code == 401 for r in responses)
    assert all(r.json() == responses[0].json() for r in responses)
    assert responses[0].json()["error"]["code"] == "invalid_credentials"
    assert all("set-cookie" not in r.headers for r in responses)


# --- Access tokens ---


async def test_me_requires_a_token(client: AsyncClient) -> None:
    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}):
        response = await client.get("/auth/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"


async def test_me_for_each_role(client: AsyncClient, db: AsyncSession) -> None:
    owner = await signup(
        client,
        mode="multiple",
        locations=[location_payload("Downtown"), location_payload("Uptown")],
    )
    downtown = owner.location_ids[0]
    manager = await join_team(
        client, owner, email="m@glow.example.com", role="manager", location_id=downtown
    )
    admin = await create_platform_admin(client, db)

    owner_me = (await client.get("/auth/me", headers=owner.headers)).json()
    manager_me = (await client.get("/auth/me", headers=manager.headers)).json()
    admin_me = (await client.get("/auth/me", headers=admin.headers)).json()

    assert owner_me["role"] == "owner"
    assert sorted(owner_me["location_ids"]) == sorted(owner.location_ids)
    assert manager_me["role"] == "manager"
    assert manager_me["location_ids"] == [downtown]
    assert admin_me["role"] == "platform_admin"
    assert admin_me["business"] is None
    assert admin_me["location_ids"] == []


async def test_expired_token_is_reported_as_expired(client: AsyncClient) -> None:
    owner = await signup(client)
    expired = _forge_token(owner.id, exp=datetime.now(UTC) - timedelta(seconds=5))
    response = await client.get("/auth/me", headers=bearer(expired))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


async def test_forged_tokens_are_rejected(client: AsyncClient) -> None:
    owner = await signup(client)
    wrong_secret = _forge_token(owner.id, _secret="x" * 40)
    unsigned = jwt.encode(
        {"sub": owner.id, "exp": datetime.now(UTC) + timedelta(minutes=5)}, "", "none"
    )
    garbage = "not.a.jwt"
    for token in (wrong_secret, unsigned, garbage):
        response = await client.get("/auth/me", headers=bearer(token))
        assert response.status_code == 401, token
        assert response.json()["error"]["code"] == "not_authenticated"


async def test_token_for_unknown_user_is_rejected(client: AsyncClient) -> None:
    await signup(client)
    response = await client.get("/auth/me", headers=bearer(_forge_token(str(uuid.uuid4()))))
    assert response.status_code == 401


async def test_deactivated_user_loses_access_immediately(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = await signup(client)
    staff = await join_team(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    assert (await client.get("/auth/me", headers=staff.headers)).status_code == 200

    await db.execute(update(User).where(User.id == uuid.UUID(staff.id)).values(is_active=False))
    await db.commit()

    assert (await client.get("/auth/me", headers=staff.headers)).status_code == 401
    assert (await refresh(client, staff.refresh_token)).status_code == 401


# --- Refresh tokens ---


async def test_refresh_rotates_the_token(client: AsyncClient) -> None:
    owner = await signup(client)
    response = await refresh(client, owner.refresh_token)
    assert response.status_code == 200
    new_cookie = response.cookies.get(REFRESH_COOKIE)
    assert new_cookie and new_cookie != owner.refresh_token
    body = response.json()
    assert body["user"]["id"] == owner.id
    assert (await client.get("/auth/me", headers=bearer(body["access_token"]))).status_code == 200

    # The new cookie keeps working.
    assert (await refresh(client, new_cookie)).status_code == 200


async def test_reusing_a_rotated_refresh_token_ends_the_whole_session(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = await signup(client)
    rotated = await refresh(client, owner.refresh_token)
    newest = rotated.cookies.get(REFRESH_COOKIE)
    assert newest

    # Someone presents the old token again: treated as theft.
    replay = await refresh(client, owner.refresh_token)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "not_authenticated"

    # ... and the legitimate newest token of that family is revoked too.
    assert (await refresh(client, newest)).status_code == 401
    unrevoked = await db.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    assert unrevoked.all() == []


async def test_reuse_does_not_affect_other_sessions(client: AsyncClient) -> None:
    await signup(client, email="olivia@glow.example.com")
    first = await login(client, "olivia@glow.example.com")
    second = await login(client, "olivia@glow.example.com")

    await refresh(client, first.refresh_token)
    assert (await refresh(client, first.refresh_token)).status_code == 401  # replay
    assert (await refresh(client, second.refresh_token)).status_code == 200  # other device fine


async def test_concurrent_refreshes_with_one_token_only_succeed_once(client: AsyncClient) -> None:
    owner = await signup(client)
    results = await asyncio.gather(
        refresh(client, owner.refresh_token), refresh(client, owner.refresh_token)
    )
    assert sorted(r.status_code for r in results) == [200, 401]


async def test_expired_refresh_token(client: AsyncClient, db: AsyncSession) -> None:
    owner = await signup(client)
    await db.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()
    response = await refresh(client, owner.refresh_token)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


@pytest.mark.parametrize("cookie", [None, "", "never-issued-token"])
async def test_refresh_without_a_valid_cookie(client: AsyncClient, cookie: str | None) -> None:
    response = await refresh(client, cookie)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_refresh_tokens_are_stored_hashed(client: AsyncClient, db: AsyncSession) -> None:
    owner = await signup(client)
    stored = (await db.scalars(select(RefreshToken.token_hash))).all()
    assert len(stored) == 1
    assert owner.refresh_token not in stored
    assert len(stored[0]) == 64  # SHA-256 hex


# --- Logout ---


async def test_logout_revokes_the_session_and_clears_the_cookie(client: AsyncClient) -> None:
    owner = await signup(client)
    response = await client.post(
        "/auth/logout", headers={"Cookie": f"{REFRESH_COOKIE}={owner.refresh_token}"}
    )
    assert response.status_code == 204
    assert response.content == b""
    cleared = response.headers["set-cookie"].lower()
    assert cleared.startswith(f"{REFRESH_COOKIE}=")
    assert "max-age=0" in cleared
    assert "path=/auth" in cleared

    assert (await refresh(client, owner.refresh_token)).status_code == 401


async def test_logout_is_idempotent_without_a_cookie(client: AsyncClient) -> None:
    assert (await client.post("/auth/logout")).status_code == 204


async def test_logout_leaves_other_devices_signed_in(client: AsyncClient) -> None:
    await signup(client, email="olivia@glow.example.com")
    laptop = await login(client, "olivia@glow.example.com")
    phone = await login(client, "olivia@glow.example.com")
    await client.post(
        "/auth/logout", headers={"Cookie": f"{REFRESH_COOKIE}={laptop.refresh_token}"}
    )
    assert (await refresh(client, laptop.refresh_token)).status_code == 401
    assert (await refresh(client, phone.refresh_token)).status_code == 200


# --- Invitations ---


async def test_accept_invite_creates_the_account_and_signs_in(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = await signup(client)
    location_id = owner.location_ids[0]
    invited = await invite(
        client, owner, email="Sam@Glow.example.com", role="staff", location_id=location_id
    )
    assert invited.status_code == 201

    response = await accept_invite(client, invited.json()["token"], full_name="Sam Stylist")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "staff"
    assert body["user"]["full_name"] == "Sam Stylist"
    assert body["user"]["location_ids"] == [location_id]
    assert REFRESH_COOKIE in response.cookies

    # They can sign in normally afterwards.
    assert (await login(client, "sam@glow.example.com")).user["role"] == "staff"
    invite_row = await db.scalar(select(Invite))
    assert invite_row is not None and invite_row.accepted_at is not None


async def test_invite_tokens_are_stored_hashed(client: AsyncClient, db: AsyncSession) -> None:
    owner = await signup(client)
    invited = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    stored = await db.scalar(select(Invite.token_hash))
    assert stored is not None
    assert invited.json()["token"] != stored
    assert len(stored) == 64


async def test_invite_can_only_be_used_once(client: AsyncClient) -> None:
    owner = await signup(client)
    invited = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    token = invited.json()["token"]
    assert (await accept_invite(client, token)).status_code == 200
    again = await accept_invite(client, token)
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "invalid_invite"


async def test_unknown_and_expired_invites_look_the_same(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = await signup(client)
    invited = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    await db.execute(update(Invite).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    await db.commit()

    expired = await accept_invite(client, invited.json()["token"])
    unknown = await accept_invite(client, "this-token-was-never-issued")
    assert expired.status_code == unknown.status_code == 400
    assert expired.json() == unknown.json()


async def test_accept_invite_when_the_email_registered_in_the_meantime(
    client: AsyncClient,
) -> None:
    owner = await signup(client)
    invited = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    await signup(client, business_name="Sam's Own", email="sam@glow.example.com")
    response = await accept_invite(client, invited.json()["token"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_accept_invite_validates_the_password(client: AsyncClient) -> None:
    owner = await signup(client)
    invited = await invite(
        client, owner, email="sam@glow.example.com", role="staff", location_id=owner.location_ids[0]
    )
    response = await accept_invite(client, invited.json()["token"], password="short")
    assert response.status_code == 422
    assert "password" in response.json()["error"]["details"]
