import pytest
from httpx import AsyncClient

from tests.helpers import build_world, create_location, location_payload, signup

# --- Business ---


async def test_get_business(client: AsyncClient) -> None:
    owner = await signup(client, business_name="Glow Salon")
    body = (await client.get("/business", headers=owner.headers)).json()
    assert body["name"] == "Glow Salon"
    assert body["slug"] == "glow-salon"
    assert body["location_mode"] == "single"
    assert body["cancellation_window_minutes"] == 120


async def test_owner_updates_business_partially(client: AsyncClient) -> None:
    owner = await signup(client)
    response = await client.patch(
        "/business",
        json={"name": "Glow & Co", "cancellation_window_minutes": 240},
        headers=owner.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Glow & Co"
    assert body["cancellation_window_minutes"] == 240
    assert body["default_timezone"] == "Asia/Karachi"  # untouched
    assert body["slug"] == "glow-salon"  # the slug never changes on rename


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"cancellation_window_minutes": -1}, "cancellation_window_minutes"),
        ({"cancellation_window_minutes": 60 * 24 * 31}, "cancellation_window_minutes"),
        ({"default_timezone": "Nowhere/City"}, "default_timezone"),
        ({"name": ""}, "name"),
    ],
)
async def test_business_update_validation(
    client: AsyncClient, payload: dict[str, object], field: str
) -> None:
    owner = await signup(client)
    response = await client.patch("/business", json=payload, headers=owner.headers)
    assert response.status_code == 422
    assert field in response.json()["error"]["details"]


async def test_zero_minute_cancellation_window_is_allowed(client: AsyncClient) -> None:
    owner = await signup(client)
    response = await client.patch(
        "/business", json={"cancellation_window_minutes": 0}, headers=owner.headers
    )
    assert response.status_code == 200
    assert response.json()["cancellation_window_minutes"] == 0


# --- Listing and visibility ---


async def test_locations_visible_per_role(client: AsyncClient) -> None:
    w = await build_world(client)

    def names(response_json: dict[str, list[dict[str, str]]]) -> list[str]:
        return sorted(item["name"] for item in response_json["items"])

    owner_view = (await client.get("/locations", headers=w.owner_a.headers)).json()
    manager_view = (await client.get("/locations", headers=w.manager_a.headers)).json()
    staff_view = (await client.get("/locations", headers=w.staff_a.headers)).json()
    other_owner_view = (await client.get("/locations", headers=w.owner_b.headers)).json()

    assert names(owner_view) == ["Downtown", "Uptown"]
    assert names(manager_view) == ["Downtown"]
    assert names(staff_view) == ["Downtown"]
    assert names(other_owner_view) == ["Main Street"]
    assert owner_view["next_cursor"] is None


# --- Creating locations ---


async def test_adding_a_second_location_makes_the_business_multi_location(
    client: AsyncClient,
) -> None:
    owner = await signup(client)
    assert (await client.get("/business", headers=owner.headers)).json()[
        "location_mode"
    ] == "single"

    created = await create_location(client, owner, "Uptown")
    assert created["name"] == "Uptown"
    assert created["slug"] == "uptown"
    assert created["is_active"] is True
    assert created["cancellation_window_minutes"] is None
    assert created["effective_cancellation_window_minutes"] == 120

    assert (await client.get("/business", headers=owner.headers)).json()[
        "location_mode"
    ] == "multiple"
    me = (await client.get("/auth/me", headers=owner.headers)).json()
    assert len(me["location_ids"]) == 2
    assert me["business"]["location_mode"] == "multiple"


async def test_duplicate_location_names_get_distinct_slugs(client: AsyncClient) -> None:
    owner = await signup(client)
    first = await create_location(client, owner, "Main Street")
    second = await create_location(client, owner, "Main Street")
    assert {first["slug"], second["slug"]} == {"main-street-2", "main-street-3"}


async def test_create_location_validation(client: AsyncClient) -> None:
    owner = await signup(client)
    response = await client.post(
        "/locations", json={"name": "X", "timezone": "Nope/Zone"}, headers=owner.headers
    )
    assert response.status_code == 422
    assert "timezone" in response.json()["error"]["details"]


# --- Reading and updating one location ---


async def test_get_location(client: AsyncClient) -> None:
    w = await build_world(client)
    for session in (w.owner_a, w.manager_a):
        response = await client.get(f"/locations/{w.downtown['id']}", headers=session.headers)
        assert response.status_code == 200
        assert response.json()["name"] == "Downtown"


async def test_manager_cannot_see_a_sibling_location(client: AsyncClient) -> None:
    w = await build_world(client)
    response = await client.get(f"/locations/{w.uptown['id']}", headers=w.manager_a.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_manager_updates_their_own_location(client: AsyncClient) -> None:
    w = await build_world(client)
    response = await client.patch(
        f"/locations/{w.downtown['id']}",
        json={"name": "Downtown Flagship", "phone": "+923111111111", "city": "Karachi"},
        headers=w.manager_a.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["phone"], body["city"]) == (
        "Downtown Flagship",
        "+923111111111",
        "Karachi",
    )
    assert body["slug"] == "downtown"  # slugs are stable

    sibling = await client.patch(
        f"/locations/{w.uptown['id']}", json={"name": "Hijacked"}, headers=w.manager_a.headers
    )
    assert sibling.status_code == 404


async def test_location_patch_can_clear_nullable_fields_and_ignores_omitted_ones(
    client: AsyncClient,
) -> None:
    owner = await signup(client)
    location_id = owner.location_ids[0]
    response = await client.patch(
        f"/locations/{location_id}", json={"phone": None, "city": "Lahore"}, headers=owner.headers
    )
    body = response.json()
    assert body["phone"] is None  # explicit null clears it
    assert body["city"] == "Lahore"
    assert body["country"] == "PK"  # omitted -> untouched
    assert body["name"] == "Main Street"


# --- Cancellation policy ---


async def test_location_cancellation_window_override_and_inheritance(client: AsyncClient) -> None:
    owner = await signup(client)
    location_id = owner.location_ids[0]

    set_override = await client.patch(
        f"/locations/{location_id}", json={"cancellation_window_minutes": 30}, headers=owner.headers
    )
    assert set_override.json()["cancellation_window_minutes"] == 30
    assert set_override.json()["effective_cancellation_window_minutes"] == 30

    await client.patch(
        "/business", json={"cancellation_window_minutes": 360}, headers=owner.headers
    )
    still_overridden = (await client.get(f"/locations/{location_id}", headers=owner.headers)).json()
    assert still_overridden["effective_cancellation_window_minutes"] == 30

    inherit = await client.patch(
        f"/locations/{location_id}",
        json={"cancellation_window_minutes": None},
        headers=owner.headers,
    )
    assert inherit.json()["cancellation_window_minutes"] is None
    assert inherit.json()["effective_cancellation_window_minutes"] == 360  # business default


# --- Deactivating ---


async def test_owner_deactivates_and_reactivates_a_location(client: AsyncClient) -> None:
    owner = await signup(client)
    extra = await create_location(client, owner, "Uptown")

    assert (
        await client.delete(f"/locations/{extra['id']}", headers=owner.headers)
    ).status_code == 204
    listed = (await client.get("/locations", headers=owner.headers)).json()["items"]
    assert {loc["name"]: loc["is_active"] for loc in listed} == {
        "Main Street": True,
        "Uptown": False,
    }
    # Deleting again is a no-op, not an error.
    assert (
        await client.delete(f"/locations/{extra['id']}", headers=owner.headers)
    ).status_code == 204

    reactivated = await client.patch(
        f"/locations/{extra['id']}", json={"is_active": True}, headers=owner.headers
    )
    assert reactivated.json()["is_active"] is True


async def test_the_last_active_location_cannot_be_deactivated(client: AsyncClient) -> None:
    owner = await signup(client)
    only = owner.location_ids[0]

    via_delete = await client.delete(f"/locations/{only}", headers=owner.headers)
    assert via_delete.status_code == 409
    assert via_delete.json()["error"]["code"] == "last_active_location"

    via_patch = await client.patch(
        f"/locations/{only}", json={"is_active": False}, headers=owner.headers
    )
    assert via_patch.status_code == 409
    assert via_patch.json()["error"]["code"] == "last_active_location"

    extra = await create_location(client, owner, "Uptown")
    await client.delete(f"/locations/{extra['id']}", headers=owner.headers)  # now only 1 active
    assert (await client.delete(f"/locations/{only}", headers=owner.headers)).status_code == 409


async def test_concurrent_deactivations_cannot_remove_every_location(client: AsyncClient) -> None:
    import asyncio

    owner = await signup(client)
    extra = await create_location(client, owner, "Uptown")
    results = await asyncio.gather(
        client.delete(f"/locations/{owner.location_ids[0]}", headers=owner.headers),
        client.delete(f"/locations/{extra['id']}", headers=owner.headers),
    )
    assert sorted(r.status_code for r in results) == [204, 409]
    listed = (await client.get("/locations", headers=owner.headers)).json()["items"]
    assert sum(loc["is_active"] for loc in listed) == 1


async def test_manager_cannot_change_active_state(client: AsyncClient) -> None:
    w = await build_world(client)
    response = await client.patch(
        f"/locations/{w.downtown['id']}", json={"is_active": False}, headers=w.manager_a.headers
    )
    assert response.status_code == 403


async def test_location_payload_matches_contract_fields(client: AsyncClient) -> None:
    owner = await signup(client)
    body = (await client.get(f"/locations/{owner.location_ids[0]}", headers=owner.headers)).json()
    assert set(body) == {
        "id",
        "name",
        "slug",
        "timezone",
        "phone",
        "address_line1",
        "city",
        "country",
        "is_active",
        "cancellation_window_minutes",
        "effective_cancellation_window_minutes",
    }
    assert body["timezone"] == location_payload()["timezone"]


async def test_location_timezone_can_be_changed_but_must_be_valid(client: AsyncClient) -> None:
    owner = await signup(client)
    url = f"/locations/{owner.location_ids[0]}"

    changed = await client.patch(url, json={"timezone": "Europe/London"}, headers=owner.headers)
    assert changed.status_code == 200
    assert changed.json()["timezone"] == "Europe/London"

    invalid = await client.patch(url, json={"timezone": "Mars/Base"}, headers=owner.headers)
    assert invalid.status_code == 422
    assert (await client.get(url, headers=owner.headers)).json()["timezone"] == "Europe/London"
