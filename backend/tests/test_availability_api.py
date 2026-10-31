"""POST /availability end to end: real hours, time off, closures and overrides from the database."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from httpx import AsyncClient

from tests.helpers import Session, build_world, create_service, create_staff, signup

KARACHI = ZoneInfo("Asia/Karachi")
MONDAY = "2030-01-07"  # a Monday, safely in the future
TUESDAY = "2030-01-08"
SUNDAY = "2030-01-13"  # closed by default


def local_times(response_json: dict[str, Any]) -> list[str]:
    return [
        datetime.fromisoformat(s["starts_at"]).astimezone(KARACHI).strftime("%H:%M")
        for s in response_json["slots"]
    ]


async def ask(
    client: AsyncClient,
    who: Session,
    location_id: str,
    service_id: str,
    day: str = MONDAY,
    **extra: Any,
) -> Any:
    return await client.post(
        "/availability",
        json={
            "location_id": location_id,
            "service_id": service_id,
            "date_from": day,
            "date_to": day,
            **extra,
        },
        headers=who.headers,
    )


async def salon(client: AsyncClient) -> tuple[Session, str, dict[str, Any], dict[str, Any]]:
    """A single salon (open Mon-Sat 10-19) with a 60-minute haircut and one stylist who does it."""
    owner = await signup(client)
    location_id = owner.location_ids[0]
    service = await create_service(client, owner, "Haircut", duration_minutes=60)
    member = await create_staff(client, owner, location_id, "Sana", [service["id"]])
    return owner, location_id, service, member


async def test_a_normal_day_offers_every_fifteen_minutes_from_opening_to_the_last_fitting_start(
    client: AsyncClient,
) -> None:
    owner, location_id, service, member = await salon(client)
    response = await ask(client, owner, location_id, service["id"])
    assert response.status_code == 200
    times = local_times(response.json())
    assert times[0] == "10:00"
    assert times[-1] == "18:00"  # a 60-minute service must finish by 19:00
    assert len(times) == 33
    first = response.json()["slots"][0]
    assert first["staff_id"] == member["id"]
    assert first["staff_name"] == "Sana"
    assert first["starts_at"].endswith("Z")
    duration = datetime.fromisoformat(first["ends_at"]) - datetime.fromisoformat(first["starts_at"])
    assert duration.total_seconds() == 3600


async def test_closed_days_and_past_days_have_no_times(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    assert (await ask(client, owner, location_id, service["id"], SUNDAY)).json() == {"slots": []}
    assert (await ask(client, owner, location_id, service["id"], "2020-01-06")).json() == {
        "slots": []
    }


async def test_a_date_range_returns_each_open_day(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    response = await client.post(
        "/availability",
        json={
            "location_id": location_id,
            "service_id": service["id"],
            "date_from": MONDAY,
            "date_to": SUNDAY,
        },
        headers=owner.headers,
    )
    days = {s["starts_at"][:10] for s in response.json()["slots"]}
    assert days == {f"2030-01-{d:02d}" for d in range(7, 13)}  # Mon-Sat, Sunday closed


async def test_time_off_removes_the_blocked_times(client: AsyncClient) -> None:
    owner, location_id, service, member = await salon(client)
    await client.post(
        f"/staff/{member['id']}/time-off",
        json={
            "starts_at": "2030-01-07T05:00:00Z",
            "ends_at": "2030-01-07T06:00:00Z",
        },  # 10:00-11:00 local
        headers=owner.headers,
    )
    times = local_times((await ask(client, owner, location_id, service["id"])).json())
    assert times[0] == "11:00"


async def test_a_closure_removes_the_whole_day_until_it_is_lifted(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    closure = (
        await client.post(
            f"/locations/{location_id}/closures", json={"date": MONDAY}, headers=owner.headers
        )
    ).json()
    assert (await ask(client, owner, location_id, service["id"])).json() == {"slots": []}
    await client.delete(f"/locations/{location_id}/closures/{closure['id']}", headers=owner.headers)
    assert len((await ask(client, owner, location_id, service["id"])).json()["slots"]) == 33


async def test_staff_working_hours_narrow_the_day(client: AsyncClient) -> None:
    owner, location_id, service, member = await salon(client)
    await client.put(
        f"/staff/{member['id']}/hours",
        json=[
            {"weekday": 0, "start": "10:00", "end": "12:00"},
            {"weekday": 0, "start": "15:00", "end": "17:00"},
        ],
        headers=owner.headers,
    )
    times = local_times((await ask(client, owner, location_id, service["id"])).json())
    assert times[0] == "10:00" and "11:00" in times and "11:15" not in times
    assert "15:00" in times and times[-1] == "16:00"
    assert local_times((await ask(client, owner, location_id, service["id"], TUESDAY)).json()) == []


async def test_location_hours_cap_staff_hours(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    await client.put(
        f"/locations/{location_id}/hours",
        json=[{"weekday": 0, "start": "12:00", "end": "14:00"}],
        headers=owner.headers,
    )
    times = local_times((await ask(client, owner, location_id, service["id"])).json())
    assert times == ["12:00", "12:15", "12:30", "12:45", "13:00"]


async def test_a_longer_service_and_a_per_location_duration_override(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    await client.patch(
        f"/services/{service['id']}",
        json={"location_overrides": [{"location_id": location_id, "duration_minutes": 30}]},
        headers=owner.headers,
    )
    times = local_times((await ask(client, owner, location_id, service["id"])).json())
    assert times[-1] == "18:30"  # the override makes it a 30-minute service here


async def test_a_service_can_be_switched_off_at_one_location(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Facial")
    await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    await create_staff(client, w.owner_a, w.uptown["id"], "Uma", [service["id"]])
    await client.patch(
        f"/services/{service['id']}",
        json={"location_overrides": [{"location_id": w.uptown["id"], "is_offered": False}]},
        headers=w.owner_a.headers,
    )
    assert (await ask(client, w.owner_a, w.downtown["id"], service["id"])).json()["slots"]
    assert (await ask(client, w.owner_a, w.uptown["id"], service["id"])).json() == {"slots": []}


async def test_inactive_staff_and_services_are_not_offered(client: AsyncClient) -> None:
    owner, location_id, service, member = await salon(client)
    await client.delete(f"/staff/{member['id']}", headers=owner.headers)
    assert (await ask(client, owner, location_id, service["id"])).json() == {"slots": []}
    await client.patch(f"/staff/{member['id']}", json={"is_active": True}, headers=owner.headers)
    assert (await ask(client, owner, location_id, service["id"])).json()["slots"]
    await client.delete(f"/services/{service['id']}", headers=owner.headers)
    assert (await ask(client, owner, location_id, service["id"])).json() == {"slots": []}


async def test_only_staff_who_do_the_service_are_considered(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    other = await create_service(client, owner, "Manicure")
    await create_staff(client, owner, location_id, "Nails Only", [other["id"]])
    names = {
        s["staff_name"]
        for s in (await ask(client, owner, location_id, service["id"])).json()["slots"]
    }
    assert names == {"Sana"}


async def test_any_staff_versus_one_staff_member(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    ali = await create_staff(client, owner, location_id, "Ali", [service["id"]])
    everyone = (await ask(client, owner, location_id, service["id"])).json()["slots"]
    assert {s["staff_name"] for s in everyone} == {"Sana", "Ali"}
    assert len(everyone) == 66  # both are free at every time

    only_ali = (await ask(client, owner, location_id, service["id"], staff_id=ali["id"])).json()[
        "slots"
    ]
    assert {s["staff_id"] for s in only_ali} == {ali["id"]}
    assert len(only_ali) == 33


async def test_asking_for_staff_who_cannot_do_it_returns_nothing_rather_than_an_error(
    client: AsyncClient,
) -> None:
    owner, location_id, service, _ = await salon(client)
    other = await create_service(client, owner, "Manicure")
    nails = await create_staff(client, owner, location_id, "Nails Only", [other["id"]])
    assert (await ask(client, owner, location_id, service["id"], staff_id=nails["id"])).json() == {
        "slots": []
    }


async def test_every_role_may_ask_but_only_for_their_own_location(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Haircut")
    await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    for who in (w.owner_a, w.manager_a, w.staff_a):
        response = await ask(client, who, w.downtown["id"], service["id"])
        assert response.status_code == 200 and response.json()["slots"], who.user["role"]
    # A manager or staff member of Downtown can't look at Uptown.
    assert (await ask(client, w.manager_a, w.uptown["id"], service["id"])).status_code == 404
    assert (await ask(client, w.staff_a, w.uptown["id"], service["id"])).status_code == 404


async def test_other_businesses_locations_and_services_are_404(client: AsyncClient) -> None:
    w = await build_world(client)
    mine = await create_service(client, w.owner_a, "Haircut")
    theirs = await create_service(client, w.owner_b, "Haircut")
    assert (await ask(client, w.owner_a, w.location_b["id"], mine["id"])).status_code == 404
    assert (await ask(client, w.owner_a, w.downtown["id"], theirs["id"])).status_code == 404


async def test_the_date_range_is_validated(client: AsyncClient) -> None:
    owner, location_id, service, _ = await salon(client)
    too_long = await client.post(
        "/availability",
        json={
            "location_id": location_id,
            "service_id": service["id"],
            "date_from": "2030-01-01",
            "date_to": "2030-03-01",
        },
        headers=owner.headers,
    )
    backwards = await client.post(
        "/availability",
        json={
            "location_id": location_id,
            "service_id": service["id"],
            "date_from": MONDAY,
            "date_to": "2030-01-01",
        },
        headers=owner.headers,
    )
    assert too_long.status_code == backwards.status_code == 422
    exactly_a_month = await client.post(
        "/availability",
        json={
            "location_id": location_id,
            "service_id": service["id"],
            "date_from": "2030-01-01",
            "date_to": "2030-01-31",
        },
        headers=owner.headers,
    )
    assert exactly_a_month.status_code == 200


async def test_daylight_saving_changes_the_utc_time_of_the_same_local_slot(
    client: AsyncClient,
) -> None:
    owner = await signup(
        client,
        locations=[{"name": "NY", "timezone": "America/New_York"}],
    )
    location_id = owner.location_ids[0]
    service = await create_service(client, owner, "Cut", duration_minutes=30)
    await create_staff(client, owner, location_id, "Nia", [service["id"]])

    def first_utc_hour(response_json: dict[str, Any]) -> int:
        return datetime.fromisoformat(response_json["slots"][0]["starts_at"]).hour

    winter = (await ask(client, owner, location_id, service["id"], "2030-01-07")).json()
    summer = (await ask(client, owner, location_id, service["id"], "2030-07-01")).json()  # Monday
    assert first_utc_hour(winter) == 15  # 10:00 EST = 15:00 UTC
    assert first_utc_hour(summer) == 14  # 10:00 EDT = 14:00 UTC
