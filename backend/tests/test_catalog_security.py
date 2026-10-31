"""Who may use the catalog/schedule/availability endpoints, and that tenants stay separate."""

import uuid
from datetime import UTC, datetime, time
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import LocationService
from app.models.schedule import LocationHours
from app.models.staff import Staff, StaffService
from tests.helpers import World, build_world, create_platform_admin, create_service, create_staff

MONDAY = "2030-01-07"


class Fixture:
    def __init__(self, world: World, service: dict[str, Any], member: dict[str, Any]) -> None:
        self.w, self.service, self.member = world, service, member
        self.downtown = world.downtown["id"]

    def fill(self, path: str) -> str:
        return path.format(service=self.service["id"], member=self.member["id"], dt=self.downtown)


async def fixture(client: AsyncClient) -> Fixture:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Haircut")
    member = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    return Fixture(w, service, member)


ALL = {"owner", "manager", "staff"}
MANAGERS = {"owner", "manager"}

# (method, path, body, roles allowed). Destructive calls come last.
CASES: list[tuple[str, str, Any, set[str]]] = [
    ("GET", "/services", None, ALL),
    ("POST", "/services", {"name": "New", "duration_minutes": 30, "price_minor": 100}, MANAGERS),
    ("PATCH", "/services/{service}", {"price_minor": 5}, MANAGERS),
    ("GET", "/staff", None, ALL),
    ("POST", "/staff", {"location_id": "{dt}", "full_name": "New Person"}, MANAGERS),
    ("PATCH", "/staff/{member}", {"title": "Lead"}, MANAGERS),
    ("GET", "/staff/{member}/hours", None, MANAGERS),
    ("PUT", "/staff/{member}/hours", [{"weekday": 1, "start": "10:00", "end": "12:00"}], MANAGERS),
    ("GET", "/staff/{member}/time-off", None, MANAGERS),
    (
        "POST",
        "/staff/{member}/time-off",
        {"starts_at": "2031-01-01T00:00:00Z", "ends_at": "2031-01-02T00:00:00Z"},
        MANAGERS,
    ),
    ("GET", "/locations/{dt}/hours", None, ALL),
    ("PUT", "/locations/{dt}/hours", [{"weekday": 0, "start": "09:00", "end": "17:00"}], MANAGERS),
    ("GET", "/locations/{dt}/closures", None, ALL),
    ("POST", "/locations/{dt}/closures", {"date": "2031-06-01"}, MANAGERS),
    (
        "POST",
        "/availability",
        {"location_id": "{dt}", "service_id": "{service}", "date_from": MONDAY, "date_to": MONDAY},
        ALL,
    ),
    ("DELETE", "/staff/{member}", None, MANAGERS),
    ("DELETE", "/services/{service}", None, MANAGERS),
]


def _body(value: Any, fx: Fixture) -> Any:
    if isinstance(value, dict):
        return {k: (fx.fill(v) if isinstance(v, str) else v) for k, v in value.items()}
    return value


async def test_every_endpoint_enforces_its_roles(client: AsyncClient, db: AsyncSession) -> None:
    fx = await fixture(client)
    admin = await create_platform_admin(client, db)
    problems: list[str] = []

    for method, path, body, allowed in CASES:
        url, payload = fx.fill(path), _body(body, fx)

        async def call(
            headers: dict[str, str], url: str = url, payload: Any = payload, method: str = method
        ) -> int:
            return (await client.request(method, url, json=payload, headers=headers)).status_code

        if (status := await call({})) != 401:
            problems.append(f"anonymous {method} {path}: {status}")
        if (status := await call(admin.headers)) != 403:
            problems.append(f"platform admin {method} {path}: {status}")
        for role, session in (
            ("staff", fx.w.staff_a),
            ("manager", fx.w.manager_a),
            ("owner", fx.w.owner_a),
        ):
            status = await call(session.headers)
            # 409 means "allowed, but it clashes with what an earlier caller just created".
            if role in allowed and status in (401, 403):
                problems.append(f"{role} should be allowed on {method} {path}: {status}")
            if role not in allowed and status != 403:
                problems.append(f"{role} should be forbidden on {method} {path}: {status}")
    assert problems == []


async def test_another_business_gets_404_for_every_resource_it_does_not_own(
    client: AsyncClient,
) -> None:
    fx = await fixture(client)
    attacker = fx.w.owner_b
    attacks: list[tuple[str, str, Any]] = [
        ("PATCH", f"/services/{fx.service['id']}", {"price_minor": 1}),
        ("DELETE", f"/services/{fx.service['id']}", None),
        ("PATCH", f"/staff/{fx.member['id']}", {"full_name": "pwned"}),
        ("DELETE", f"/staff/{fx.member['id']}", None),
        ("GET", f"/staff/{fx.member['id']}/hours", None),
        ("PUT", f"/staff/{fx.member['id']}/hours", []),
        ("GET", f"/staff/{fx.member['id']}/time-off", None),
        (
            "POST",
            f"/staff/{fx.member['id']}/time-off",
            {"starts_at": "2031-01-01T00:00:00Z", "ends_at": "2031-01-02T00:00:00Z"},
        ),
        ("GET", f"/locations/{fx.downtown}/hours", None),
        ("PUT", f"/locations/{fx.downtown}/hours", []),
        ("GET", f"/locations/{fx.downtown}/closures", None),
        ("POST", f"/locations/{fx.downtown}/closures", {"date": "2031-06-01"}),
        ("POST", "/staff", {"location_id": fx.downtown, "full_name": "Intruder"}),
        (
            "POST",
            "/availability",
            {
                "location_id": fx.downtown,
                "service_id": fx.service["id"],
                "date_from": MONDAY,
                "date_to": MONDAY,
            },
        ),
    ]
    for method, path, body in attacks:
        response = await client.request(method, path, json=body, headers=attacker.headers)
        assert response.status_code == 404, (method, path, response.text)

    # ...and nothing changed.
    service = (await client.get("/services", headers=fx.w.owner_a.headers)).json()["items"][0]
    assert (service["price_minor"], service["is_active"]) == (350000, True)
    member = (await client.get("/staff", headers=fx.w.owner_a.headers)).json()["items"][0]
    assert (member["full_name"], member["is_active"]) == ("Dana", True)
    assert (
        len(
            (
                await client.get(f"/staff/{fx.member['id']}/hours", headers=fx.w.owner_a.headers)
            ).json()
        )
        == 6
    )


async def test_listings_never_include_another_business(client: AsyncClient) -> None:
    fx = await fixture(client)
    assert (await client.get("/services", headers=fx.w.owner_b.headers)).json()["items"] == []
    assert (await client.get("/staff", headers=fx.w.owner_b.headers)).json()["items"] == []


async def test_a_business_cannot_reference_anothers_records_in_its_own_requests(
    client: AsyncClient,
) -> None:
    fx = await fixture(client)
    b = fx.w.owner_b
    b_service = await create_service(client, b, "Their service")
    b_location = fx.w.location_b["id"]

    # Staff of B cannot be given A's service, nor placed at A's location.
    assert (
        await client.post(
            "/staff",
            json={"location_id": b_location, "full_name": "X", "service_ids": [fx.service["id"]]},
            headers=b.headers,
        )
    ).status_code == 404
    # A cannot use B's service for its staff or override B's location.
    assert (
        await client.patch(
            f"/staff/{fx.member['id']}",
            json={"service_ids": [b_service["id"]]},
            headers=fx.w.owner_a.headers,
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/services/{fx.service['id']}",
            json={"location_overrides": [{"location_id": b_location, "is_offered": False}]},
            headers=fx.w.owner_a.headers,
        )
    ).status_code == 404


# --- The database refuses cross-business links even if application code were wrong ---


async def test_db_rejects_staff_at_another_businesss_location(
    client: AsyncClient, db: AsyncSession
) -> None:
    fx = await fixture(client)
    business_b = uuid.UUID(
        (await client.get("/business", headers=fx.w.owner_b.headers)).json()["id"]
    )
    db.add(Staff(business_id=business_b, location_id=uuid.UUID(fx.downtown), full_name="X"))
    with pytest.raises(IntegrityError, match="fk_staff_business_id_locations"):
        await db.commit()


async def test_db_rejects_linking_staff_to_another_businesss_service(
    client: AsyncClient, db: AsyncSession
) -> None:
    fx = await fixture(client)
    business_b = uuid.UUID(
        (await client.get("/business", headers=fx.w.owner_b.headers)).json()["id"]
    )
    db.add(
        StaffService(
            business_id=business_b,
            staff_id=uuid.UUID(fx.member["id"]),
            service_id=uuid.UUID(fx.service["id"]),
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_db_rejects_overrides_and_hours_across_businesses(
    client: AsyncClient, db: AsyncSession
) -> None:
    fx = await fixture(client)
    business_b = uuid.UUID(
        (await client.get("/business", headers=fx.w.owner_b.headers)).json()["id"]
    )
    db.add(
        LocationService(
            business_id=business_b,
            location_id=uuid.UUID(fx.downtown),
            service_id=uuid.UUID(fx.service["id"]),
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    db.add(
        LocationHours(
            business_id=business_b,
            location_id=uuid.UUID(fx.downtown),
            weekday=0,
            opens_at=time(9),
            closes_at=time(17),
        )
    )
    with pytest.raises(IntegrityError, match="fk_location_hours_business_id_locations"):
        await db.commit()


@pytest.mark.parametrize(
    ("statement_field", "values"),
    [
        ("staff_hours_reversed", {"start_time": time(12), "end_time": time(10)}),
        ("location_hours_reversed", {"opens_at": time(12), "closes_at": time(10)}),
    ],
)
async def test_db_rejects_hours_that_end_before_they_start(
    client: AsyncClient, db: AsyncSession, statement_field: str, values: dict[str, time]
) -> None:
    from app.models.staff import StaffWorkingHours

    fx = await fixture(client)
    business = uuid.UUID((await client.get("/business", headers=fx.w.owner_a.headers)).json()["id"])
    if statement_field.startswith("staff"):
        db.add(
            StaffWorkingHours(
                business_id=business, staff_id=uuid.UUID(fx.member["id"]), weekday=0, **values
            )
        )
    else:
        db.add(
            LocationHours(
                business_id=business, location_id=uuid.UUID(fx.downtown), weekday=0, **values
            )
        )
    with pytest.raises(IntegrityError, match="_before_"):
        await db.commit()


async def test_db_rejects_time_off_that_ends_before_it_starts(
    client: AsyncClient, db: AsyncSession
) -> None:
    from app.models.staff import StaffTimeOff

    fx = await fixture(client)
    business = uuid.UUID((await client.get("/business", headers=fx.w.owner_a.headers)).json()["id"])
    db.add(
        StaffTimeOff(
            business_id=business,
            staff_id=uuid.UUID(fx.member["id"]),
            starts_at=datetime(2031, 1, 2, tzinfo=UTC),
            ends_at=datetime(2031, 1, 1, tzinfo=UTC),
        )
    )
    with pytest.raises(IntegrityError, match="start_before_end"):
        await db.commit()
