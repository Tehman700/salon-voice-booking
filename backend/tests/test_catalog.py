"""Services, staff, working hours, time off and closures."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import build_world, create_service, create_staff, signup


async def _single_salon(client: AsyncClient) -> tuple[Any, str]:
    owner = await signup(client)
    return owner, owner.location_ids[0]


# --- Services ---


async def test_create_list_update_and_deactivate_a_service(client: AsyncClient) -> None:
    owner, _ = await _single_salon(client)
    created = await create_service(
        client, owner, "Women's haircut", description="Wash, cut, style", category="Hair"
    )
    assert created["currency"] == "PKR"
    assert created["is_active"] is True
    assert created["location_overrides"] == []

    listing = (await client.get("/services", headers=owner.headers)).json()
    assert [s["name"] for s in listing["items"]] == ["Women's haircut"]
    assert listing["next_cursor"] is None

    updated = await client.patch(
        f"/services/{created['id']}",
        json={"price_minor": 400000, "buffer_minutes": 10, "description": None},
        headers=owner.headers,
    )
    body = updated.json()
    assert (body["price_minor"], body["buffer_minutes"], body["description"]) == (400000, 10, None)
    assert body["category"] == "Hair"  # omitted fields are untouched

    assert (
        await client.delete(f"/services/{created['id']}", headers=owner.headers)
    ).status_code == 204
    after = (await client.get("/services", headers=owner.headers)).json()["items"][0]
    assert after["is_active"] is False  # kept, because past appointments will refer to it


async def test_service_names_are_unique_ignoring_case(client: AsyncClient) -> None:
    owner, _ = await _single_salon(client)
    await create_service(client, owner, "Haircut")
    response = await client.post(
        "/services",
        json={"name": "HAIRCUT", "duration_minutes": 30, "price_minor": 1000},
        headers=owner.headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "service_name_taken"

    other = await create_service(client, owner, "Blow-dry")
    rename = await client.patch(
        f"/services/{other['id']}", json={"name": "haircut"}, headers=owner.headers
    )
    assert rename.status_code == 409


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"duration_minutes": 4}, "duration_minutes"),
        ({"duration_minutes": 481}, "duration_minutes"),
        ({"buffer_minutes": -1}, "buffer_minutes"),
        ({"price_minor": -1}, "price_minor"),
        ({"currency": "rupees"}, "currency"),
        ({"name": "  "}, "name"),
    ],
)
async def test_service_validation(
    client: AsyncClient, overrides: dict[str, Any], field: str
) -> None:
    owner, _ = await _single_salon(client)
    body = {"name": "Facial", "duration_minutes": 45, "price_minor": 100000, **overrides}
    response = await client.post("/services", json=body, headers=owner.headers)
    assert response.status_code == 422
    assert field in response.json()["error"]["details"]


async def test_location_overrides_replace_price_and_duration(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Facial")
    response = await client.patch(
        f"/services/{service['id']}",
        json={
            "location_overrides": [
                {"location_id": w.downtown["id"], "price_minor": 500000, "duration_minutes": 45},
                {"location_id": w.uptown["id"], "is_offered": False},
                {"location_id": w.uptown["id"], "is_offered": False},  # duplicates collapse
            ]
        },
        headers=w.owner_a.headers,
    )
    assert response.status_code == 200
    by_location = {o["location_id"]: o for o in response.json()["location_overrides"]}
    assert by_location[w.downtown["id"]]["price_minor"] == 500000
    assert by_location[w.uptown["id"]]["is_offered"] is False

    # An empty list removes them all; a row that changes nothing is not stored.
    cleared = await client.patch(
        f"/services/{service['id']}",
        json={"location_overrides": [{"location_id": w.downtown["id"]}]},
        headers=w.owner_a.headers,
    )
    assert cleared.json()["location_overrides"] == []


async def test_overrides_for_an_unknown_or_foreign_location_are_404(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Facial")
    for location_id in (str(uuid.uuid4()), w.location_b["id"]):
        response = await client.patch(
            f"/services/{service['id']}",
            json={"location_overrides": [{"location_id": location_id, "is_offered": False}]},
            headers=w.owner_a.headers,
        )
        assert response.status_code == 404


async def test_a_manager_can_only_change_overrides_for_their_own_location(
    client: AsyncClient,
) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Facial")
    await client.patch(
        f"/services/{service['id']}",
        json={"location_overrides": [{"location_id": w.uptown["id"], "price_minor": 999}]},
        headers=w.owner_a.headers,
    )

    # The Downtown manager saves a form that carries both locations: only Downtown is applied.
    response = await client.patch(
        f"/services/{service['id']}",
        json={
            "location_overrides": [
                {"location_id": w.downtown["id"], "price_minor": 111},
                {"location_id": w.uptown["id"], "price_minor": 222},
            ]
        },
        headers=w.manager_a.headers,
    )
    assert response.status_code == 200
    prices = {o["location_id"]: o["price_minor"] for o in response.json()["location_overrides"]}
    assert prices == {w.downtown["id"]: 111, w.uptown["id"]: 999}  # Uptown untouched


# --- Staff ---


async def test_create_staff_with_services_and_default_hours(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    facial = await create_service(client, owner, "Facial")
    cut = await create_service(client, owner, "Haircut")
    member = await create_staff(
        client,
        owner,
        location_id,
        "Sana Iqbal",
        [facial["id"], cut["id"]],
        title="Senior stylist",
        color="#7928ca",
    )
    assert member["title"] == "Senior stylist"
    assert member["color"] == "#7928ca"
    assert sorted(member["service_ids"]) == sorted([facial["id"], cut["id"]])
    assert member["is_active"] is True

    hours = (await client.get(f"/staff/{member['id']}/hours", headers=owner.headers)).json()
    assert [(h["weekday"], h["start"], h["end"]) for h in hours] == [
        (d, "10:00", "19:00") for d in range(6)
    ]  # a copy of the location's default week: Monday to Saturday


async def test_staff_validation_and_unknown_references(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    bad_color = await client.post(
        "/staff",
        json={"location_id": location_id, "full_name": "A", "color": "blue"},
        headers=owner.headers,
    )
    assert bad_color.status_code == 422
    assert "color" in bad_color.json()["error"]["details"]

    unknown_service = await client.post(
        "/staff",
        json={"location_id": location_id, "full_name": "A", "service_ids": [str(uuid.uuid4())]},
        headers=owner.headers,
    )
    assert unknown_service.status_code == 404
    unknown_location = await client.post(
        "/staff",
        json={"location_id": str(uuid.uuid4()), "full_name": "A"},
        headers=owner.headers,
    )
    assert unknown_location.status_code == 404


async def test_update_staff_replaces_services_and_can_clear_the_title(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    facial = await create_service(client, owner, "Facial")
    cut = await create_service(client, owner, "Haircut")
    member = await create_staff(client, owner, location_id, "Sana", [facial["id"]], title="Stylist")

    response = await client.patch(
        f"/staff/{member['id']}",
        json={"service_ids": [cut["id"]], "title": None, "full_name": "Sana Iqbal"},
        headers=owner.headers,
    )
    body = response.json()
    assert body["service_ids"] == [cut["id"]]
    assert body["title"] is None
    assert body["full_name"] == "Sana Iqbal"


async def test_staff_list_is_scoped_to_the_callers_location(client: AsyncClient) -> None:
    w = await build_world(client)
    await create_staff(client, w.owner_a, w.downtown["id"], "Downtown Dana")
    await create_staff(client, w.owner_a, w.uptown["id"], "Uptown Uma")

    def names(response_json: dict[str, Any]) -> list[str]:
        return sorted(m["full_name"] for m in response_json["items"])

    everyone = (await client.get("/staff", headers=w.owner_a.headers)).json()
    one_location = (
        await client.get(
            "/staff", params={"location_id": w.uptown["id"]}, headers=w.owner_a.headers
        )
    ).json()
    as_manager = (await client.get("/staff", headers=w.manager_a.headers)).json()
    as_staff = (await client.get("/staff", headers=w.staff_a.headers)).json()
    assert names(everyone) == ["Downtown Dana", "Uptown Uma"]
    assert names(one_location) == ["Uptown Uma"]
    assert names(as_manager) == names(as_staff) == ["Downtown Dana"]


async def test_a_manager_works_only_inside_their_own_location(client: AsyncClient) -> None:
    w = await build_world(client)
    uptown_member = await create_staff(client, w.owner_a, w.uptown["id"], "Uptown Uma")

    refused_create = await client.post(
        "/staff",
        json={"location_id": w.uptown["id"], "full_name": "Intruder"},
        headers=w.manager_a.headers,
    )
    assert refused_create.status_code == 404
    for method, path, body in (
        ("PATCH", f"/staff/{uptown_member['id']}", {"full_name": "x"}),
        ("DELETE", f"/staff/{uptown_member['id']}", None),
        ("GET", f"/staff/{uptown_member['id']}/hours", None),
        ("PUT", f"/staff/{uptown_member['id']}/hours", []),
    ):
        response = await client.request(method, path, json=body, headers=w.manager_a.headers)
        assert response.status_code == 404, (method, path)


async def test_only_an_owner_can_move_staff_between_locations(client: AsyncClient) -> None:
    w = await build_world(client)
    member = await create_staff(client, w.owner_a, w.downtown["id"], "Dana")
    by_manager = await client.patch(
        f"/staff/{member['id']}", json={"location_id": w.uptown["id"]}, headers=w.manager_a.headers
    )
    assert by_manager.status_code == 403
    by_owner = await client.patch(
        f"/staff/{member['id']}", json={"location_id": w.uptown["id"]}, headers=w.owner_a.headers
    )
    assert by_owner.json()["location_id"] == w.uptown["id"]
    foreign = await client.patch(
        f"/staff/{member['id']}",
        json={"location_id": w.location_b["id"]},
        headers=w.owner_a.headers,
    )
    assert foreign.status_code == 404


async def test_deactivating_and_reactivating_staff(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    member = await create_staff(client, owner, location_id)
    assert (await client.delete(f"/staff/{member['id']}", headers=owner.headers)).status_code == 204
    assert (await client.delete(f"/staff/{member['id']}", headers=owner.headers)).status_code == 204
    assert (await client.get("/staff", headers=owner.headers)).json()["items"][0][
        "is_active"
    ] is False
    back = await client.patch(
        f"/staff/{member['id']}", json={"is_active": True}, headers=owner.headers
    )
    assert back.json()["is_active"] is True


async def test_linking_staff_to_a_dashboard_user(client: AsyncClient) -> None:
    w = await build_world(client)
    first = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", user_id=w.staff_a.id)
    assert first["user_id"] == w.staff_a.id
    second = await client.post(
        "/staff",
        json={"location_id": w.downtown["id"], "full_name": "Other", "user_id": w.staff_a.id},
        headers=w.owner_a.headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "user_already_linked"
    foreign = await client.post(
        "/staff",
        json={"location_id": w.downtown["id"], "full_name": "Other", "user_id": w.owner_b.id},
        headers=w.owner_a.headers,
    )
    assert foreign.status_code == 404


# --- Working hours ---


async def test_replace_working_hours_with_split_shifts(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    member = await create_staff(client, owner, location_id)
    blocks = [
        {"weekday": 2, "start": "15:00", "end": "19:00"},
        {"weekday": 2, "start": "10:00", "end": "13:00"},
        {"weekday": 0, "start": "09:30", "end": "17:00"},
    ]
    response = await client.put(f"/staff/{member['id']}/hours", json=blocks, headers=owner.headers)
    assert response.status_code == 200
    expected = [
        {"weekday": 0, "start": "09:30", "end": "17:00"},
        {"weekday": 2, "start": "10:00", "end": "13:00"},
        {"weekday": 2, "start": "15:00", "end": "19:00"},
    ]
    assert response.json() == expected
    assert (
        await client.get(f"/staff/{member['id']}/hours", headers=owner.headers)
    ).json() == expected

    cleared = await client.put(f"/staff/{member['id']}/hours", json=[], headers=owner.headers)
    assert cleared.json() == []


@pytest.mark.parametrize(
    "blocks",
    [
        [
            {"weekday": 1, "start": "10:00", "end": "12:00"},
            {"weekday": 1, "start": "11:00", "end": "14:00"},
        ],
        [{"weekday": 1, "start": "12:00", "end": "10:00"}],
        [{"weekday": 1, "start": "10:00", "end": "10:00"}],
        [{"weekday": 7, "start": "10:00", "end": "12:00"}],
        [{"weekday": 1, "start": "9am", "end": "12:00"}],
        [{"weekday": 1, "start": "24:00", "end": "25:00"}],
    ],
)
async def test_invalid_working_hours_are_rejected_and_change_nothing(
    client: AsyncClient, blocks: list[dict[str, Any]]
) -> None:
    owner, location_id = await _single_salon(client)
    member = await create_staff(client, owner, location_id)
    before = (await client.get(f"/staff/{member['id']}/hours", headers=owner.headers)).json()
    response = await client.put(f"/staff/{member['id']}/hours", json=blocks, headers=owner.headers)
    assert response.status_code == 422
    assert (
        await client.get(f"/staff/{member['id']}/hours", headers=owner.headers)
    ).json() == before


async def test_touching_blocks_are_allowed(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    member = await create_staff(client, owner, location_id)
    blocks = [
        {"weekday": 1, "start": "10:00", "end": "12:00"},
        {"weekday": 1, "start": "12:00", "end": "14:00"},
    ]
    assert (
        await client.put(f"/staff/{member['id']}/hours", json=blocks, headers=owner.headers)
    ).status_code == 200


# --- Time off ---


async def test_time_off_lifecycle(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    member = await create_staff(client, owner, location_id)
    url = f"/staff/{member['id']}/time-off"

    later = await client.post(
        url,
        json={
            "starts_at": "2030-02-10T00:00:00Z",
            "ends_at": "2030-02-12T00:00:00Z",
            "reason": "Holiday",
        },
        headers=owner.headers,
    )
    sooner = await client.post(
        url,
        json={"starts_at": "2030-01-10T05:00:00+05:00", "ends_at": "2030-01-10T09:00:00+05:00"},
        headers=owner.headers,
    )
    assert later.status_code == sooner.status_code == 201
    assert sooner.json()["reason"] is None

    listing = (await client.get(url, headers=owner.headers)).json()
    assert [t["reason"] for t in listing] == [None, "Holiday"]  # soonest first
    assert listing[0]["starts_at"].startswith("2030-01-10T00:00:00")  # stored as an instant

    assert (
        await client.delete(f"{url}/{later.json()['id']}", headers=owner.headers)
    ).status_code == 204
    assert len((await client.get(url, headers=owner.headers)).json()) == 1
    assert (
        await client.delete(f"{url}/{later.json()['id']}", headers=owner.headers)
    ).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"starts_at": "2030-01-10T10:00:00Z", "ends_at": "2030-01-10T09:00:00Z"},
        {"starts_at": "2030-01-10T10:00:00Z", "ends_at": "2030-01-10T10:00:00Z"},
        {"starts_at": "2030-01-10T10:00:00", "ends_at": "2030-01-10T12:00:00"},  # no timezone
        {"starts_at": "tomorrow", "ends_at": "later"},
    ],
)
async def test_invalid_time_off_is_rejected(client: AsyncClient, body: dict[str, str]) -> None:
    owner, location_id = await _single_salon(client)
    member = await create_staff(client, owner, location_id)
    response = await client.post(
        f"/staff/{member['id']}/time-off", json=body, headers=owner.headers
    )
    assert response.status_code == 422


# --- Location hours and closures ---


async def test_new_locations_open_monday_to_saturday(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    hours = (await client.get(f"/locations/{location_id}/hours", headers=owner.headers)).json()
    assert [h["weekday"] for h in hours] == [0, 1, 2, 3, 4, 5]
    assert {(h["start"], h["end"]) for h in hours} == {("10:00", "19:00")}

    created = (
        await client.post(
            "/locations",
            json={"name": "Second", "timezone": "Asia/Karachi"},
            headers=owner.headers,
        )
    ).json()
    second = (await client.get(f"/locations/{created['id']}/hours", headers=owner.headers)).json()
    assert len(second) == 6


async def test_replace_location_hours(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    new = [
        {"weekday": 5, "start": "12:00", "end": "22:00"},
        {"weekday": 6, "start": "12:00", "end": "18:00"},
    ]
    response = await client.put(f"/locations/{location_id}/hours", json=new, headers=owner.headers)
    assert response.json() == new
    overlapping = [
        {"weekday": 0, "start": "10:00", "end": "14:00"},
        {"weekday": 0, "start": "13:00", "end": "15:00"},
    ]
    assert (
        await client.put(f"/locations/{location_id}/hours", json=overlapping, headers=owner.headers)
    ).status_code == 422
    assert (
        await client.get(f"/locations/{location_id}/hours", headers=owner.headers)
    ).json() == new


async def test_closures(client: AsyncClient) -> None:
    owner, location_id = await _single_salon(client)
    url = f"/locations/{location_id}/closures"
    first = await client.post(
        url, json={"date": "2030-12-25", "reason": "Holiday"}, headers=owner.headers
    )
    await client.post(url, json={"date": "2030-01-01"}, headers=owner.headers)
    assert first.status_code == 201
    assert first.json()["date"] == "2030-12-25"

    duplicate = await client.post(url, json={"date": "2030-12-25"}, headers=owner.headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "closure_exists"
    assert (
        await client.post(url, json={"date": "not-a-date"}, headers=owner.headers)
    ).status_code == 422

    assert [c["date"] for c in (await client.get(url, headers=owner.headers)).json()] == [
        "2030-01-01",
        "2030-12-25",
    ]
    assert (
        await client.delete(f"{url}/{first.json()['id']}", headers=owner.headers)
    ).status_code == 204
    assert (
        await client.delete(f"{url}/{first.json()['id']}", headers=owner.headers)
    ).status_code == 404
    assert len((await client.get(url, headers=owner.headers)).json()) == 1


async def test_a_manager_cannot_change_another_locations_schedule(client: AsyncClient) -> None:
    w = await build_world(client)
    for method, path, body in (
        ("GET", f"/locations/{w.uptown['id']}/hours", None),
        ("PUT", f"/locations/{w.uptown['id']}/hours", []),
        ("GET", f"/locations/{w.uptown['id']}/closures", None),
        ("POST", f"/locations/{w.uptown['id']}/closures", {"date": "2030-01-01"}),
    ):
        response = await client.request(method, path, json=body, headers=w.manager_a.headers)
        assert response.status_code == 404, (method, path)
