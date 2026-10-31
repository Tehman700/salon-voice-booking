"""Small API-level helpers shared by the tests."""

from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import Role, User

PASSWORD = "correct-horse-battery"
REFRESH_COOKIE = "refresh_token"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def location_payload(name: str = "Main Street", timezone: str = "Asia/Karachi") -> dict[str, Any]:
    return {"name": name, "timezone": timezone, "phone": "+923001234567", "country": "PK"}


@dataclass
class Session:
    """A signed-in user, as returned by signup / login / accept-invite."""

    access_token: str
    refresh_token: str
    user: dict[str, Any]

    @property
    def headers(self) -> dict[str, str]:
        return bearer(self.access_token)

    @property
    def id(self) -> str:
        return str(self.user["id"])

    @property
    def location_ids(self) -> list[str]:
        return [str(i) for i in self.user["location_ids"]]


def _session_from(response: Response) -> Session:
    assert response.status_code in (200, 201), response.text
    body = response.json()
    return Session(
        access_token=body["access_token"],
        refresh_token=response.cookies.get(REFRESH_COOKIE) or "",
        user=body["user"],
    )


async def signup(
    client: AsyncClient,
    *,
    business_name: str = "Glow Salon",
    email: str = "owner@glow.example.com",
    mode: str = "single",
    locations: list[dict[str, Any]] | None = None,
) -> Session:
    response = await client.post(
        "/auth/signup",
        json={
            "business_name": business_name,
            "owner_full_name": "Olivia Owner",
            "email": email,
            "password": PASSWORD,
            "location_mode": mode,
            "locations": locations or [location_payload()],
        },
    )
    client.cookies.clear()  # tests pass the refresh cookie explicitly, never implicitly
    return _session_from(response)


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> Session:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    client.cookies.clear()
    return _session_from(response)


async def refresh(client: AsyncClient, refresh_token: str | None) -> Response:
    # The cookie goes in a header (not the client's jar) so concurrent calls can't interfere.
    headers = {"Cookie": f"{REFRESH_COOKIE}={refresh_token}"} if refresh_token is not None else {}
    response = await client.post("/auth/refresh", headers=headers)
    client.cookies.clear()
    return response


async def create_location(client: AsyncClient, owner: Session, name: str) -> dict[str, Any]:
    response = await client.post("/locations", json=location_payload(name), headers=owner.headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def invite(
    client: AsyncClient,
    inviter: Session,
    *,
    email: str,
    role: str,
    location_id: str | None = None,
) -> Response:
    return await client.post(
        "/users/invite",
        json={"email": email, "role": role, "location_id": location_id},
        headers=inviter.headers,
    )


async def accept_invite(
    client: AsyncClient, token: str, *, full_name: str = "New Member", password: str = PASSWORD
) -> Response:
    response = await client.post(
        "/auth/accept-invite", json={"token": token, "full_name": full_name, "password": password}
    )
    client.cookies.clear()
    return response


async def join_team(
    client: AsyncClient,
    inviter: Session,
    *,
    email: str,
    role: str,
    location_id: str | None = None,
) -> Session:
    """Invite someone and have them accept, returning their signed-in session."""
    invited = await invite(client, inviter, email=email, role=role, location_id=location_id)
    assert invited.status_code == 201, invited.text
    return _session_from(await accept_invite(client, invited.json()["token"]))


async def create_platform_admin(
    client: AsyncClient, db: AsyncSession, email: str = "admin@platform.example.com"
) -> Session:
    db.add(
        User(
            email=email,
            password_hash=hash_password(PASSWORD),
            full_name="Platform Admin",
            role=Role.platform_admin,
        )
    )
    await db.commit()
    return await login(client, email)


@dataclass
class World:
    """Two unrelated businesses, used for authorization and isolation tests.

    Business A (multiple): locations Downtown + Uptown; owner, a manager and a staff member in
    Downtown, plus a manager in Uptown.  Business B (single): one location and an owner.
    """

    owner_a: Session
    manager_a: Session  # Downtown
    staff_a: Session  # Downtown
    manager_a_uptown: Session
    downtown: dict[str, Any]
    uptown: dict[str, Any]
    owner_b: Session
    location_b: dict[str, Any]


async def build_world(client: AsyncClient) -> World:
    owner_a = await signup(
        client,
        business_name="Alpha Salons",
        email="owner@alpha.example.com",
        mode="multiple",
        locations=[location_payload("Downtown"), location_payload("Uptown")],
    )
    listing = await client.get("/locations", headers=owner_a.headers)
    by_name = {loc["name"]: loc for loc in listing.json()["items"]}
    downtown, uptown = by_name["Downtown"], by_name["Uptown"]

    manager_a = await join_team(
        client,
        owner_a,
        email="manager@alpha.example.com",
        role="manager",
        location_id=downtown["id"],
    )
    staff_a = await join_team(
        client, owner_a, email="staff@alpha.example.com", role="staff", location_id=downtown["id"]
    )
    manager_a_uptown = await join_team(
        client,
        owner_a,
        email="uptown@alpha.example.com",
        role="manager",
        location_id=uptown["id"],
    )

    owner_b = await signup(client, business_name="Beta Cuts", email="owner@beta.example.com")
    location_b = (await client.get("/locations", headers=owner_b.headers)).json()["items"][0]
    return World(
        owner_a=owner_a,
        manager_a=manager_a,
        staff_a=staff_a,
        manager_a_uptown=manager_a_uptown,
        downtown=downtown,
        uptown=uptown,
        owner_b=owner_b,
        location_b=location_b,
    )
