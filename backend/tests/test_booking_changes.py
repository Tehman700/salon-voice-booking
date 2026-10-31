"""Rescheduling, cancelling, the notice window, listing, who can see what, and customers."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Appointment, AppointmentStatus
from tests.booking_helpers import MONDAY, TUESDAY, Salon, at, book, free_times, key, salon
from tests.helpers import Session, build_world, create_service, create_staff


async def make(client: AsyncClient, s: Salon, hour: int, **kw: Any) -> dict[str, Any]:
    response = await book(client, s, at(MONDAY, hour), **kw)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def soon(client: AsyncClient, s: Salon) -> str:
    """The first genuinely free start time in the coming days (real clock, so it is 'soon')."""
    today = datetime.now(UTC).date()
    response = await client.post(
        "/availability",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "date_from": (today + timedelta(days=1)).isoformat(),
            "date_to": (today + timedelta(days=10)).isoformat(),
        },
        headers=s.owner.headers,
    )
    return str(response.json()["slots"][0]["starts_at"])


async def set_notice(client: AsyncClient, s: Salon, minutes: int) -> None:
    response = await client.patch(
        "/business", json={"cancellation_window_minutes": minutes}, headers=s.owner.headers
    )
    assert response.status_code == 200


# --- Rescheduling ---


async def test_reschedule_to_a_free_time_frees_the_old_one(client: AsyncClient) -> None:
    s = await salon(client)
    b = await make(client, s, 10)
    moved = await client.patch(
        f"/bookings/{b['id']}", json={"starts_at": at(MONDAY, 14)}, headers=s.owner.headers
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["starts_at"] == at(MONDAY, 14) and moved.json()["ends_at"] == at(MONDAY, 15)
    assert moved.json()["reference"] == b["reference"]  # same booking, new time
    free = await free_times(client, s)
    assert at(MONDAY, 10) in free and at(MONDAY, 14) not in free
    # Someone else can now take the old time.
    assert (
        await book(client, s, at(MONDAY, 10), name="N", phone="+923008888888")
    ).status_code == 201


async def test_a_booking_can_shift_within_its_own_time(client: AsyncClient) -> None:
    s = await salon(client)
    b = await make(client, s, 10)
    moved = await client.patch(
        f"/bookings/{b['id']}", json={"starts_at": at(MONDAY, 10, 30)}, headers=s.owner.headers
    )
    assert moved.status_code == 200  # it overlaps its own old slot, which must not count against it


async def test_reschedule_to_a_taken_time_is_refused_and_changes_nothing(
    client: AsyncClient,
) -> None:
    s = await salon(client)
    mine = await make(client, s, 10)
    await make(client, s, 12, name="Other", phone="+923009999999")
    response = await client.patch(
        f"/bookings/{mine['id']}", json={"starts_at": at(MONDAY, 12, 30)}, headers=s.owner.headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_unavailable"
    assert response.json()["error"]["details"]["alternatives"]
    unchanged = (await client.get(f"/bookings/{mine['id']}", headers=s.owner.headers)).json()
    assert unchanged["starts_at"] == at(MONDAY, 10)


async def test_reschedule_to_another_stylist(client: AsyncClient) -> None:
    s = await salon(client)
    ali = await create_staff(client, s.owner, s.location_id, "Ali", [s.service["id"]])
    b = await make(client, s, 10)
    moved = await client.patch(
        f"/bookings/{b['id']}", json={"staff_id": ali["id"]}, headers=s.owner.headers
    )
    assert moved.status_code == 200 and moved.json()["staff_id"] == ali["id"]
    assert moved.json()["starts_at"] == at(MONDAY, 10)
    # The original stylist is free again at 10:00.
    assert (
        await book(client, s, at(MONDAY, 10), name="N", phone="+923008888888")
    ).status_code == 201


async def test_edit_notes_without_touching_the_time(client: AsyncClient) -> None:
    s = await salon(client)
    b = await make(client, s, 10, notes="old")
    edited = await client.patch(
        f"/bookings/{b['id']}", json={"notes": "new"}, headers=s.owner.headers
    )
    assert edited.json()["notes"] == "new" and edited.json()["starts_at"] == at(MONDAY, 10)
    cleared = await client.patch(
        f"/bookings/{b['id']}", json={"notes": None}, headers=s.owner.headers
    )
    assert cleared.json()["notes"] is None


async def test_validation_of_reschedule_requests(client: AsyncClient) -> None:
    s = await salon(client)
    b = await make(client, s, 10)
    naive = await client.patch(
        f"/bookings/{b['id']}", json={"starts_at": "2030-01-07T12:00:00"}, headers=s.owner.headers
    )
    bad_status = await client.patch(
        f"/bookings/{b['id']}", json={"status": "cancelled"}, headers=s.owner.headers
    )
    other_staff = await client.patch(
        f"/bookings/{b['id']}", json={"staff_id": s.location_id}, headers=s.owner.headers
    )
    assert naive.status_code == bad_status.status_code == 422
    assert other_staff.status_code == 404  # not a staff member of this business


# --- Cancelling ---


async def test_cancel_frees_the_time_and_records_why(client: AsyncClient, db: AsyncSession) -> None:
    s = await salon(client)
    b = await make(client, s, 10)
    cancelled = await client.delete(
        f"/bookings/{b['id']}", params={"reason": "Customer called"}, headers=s.owner.headers
    )
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled" and body["cancellation_reason"] == "Customer called"
    assert body["cancelled_at"] is not None
    assert at(MONDAY, 10) in await free_times(client, s)
    row = await db.get(Appointment, __import__("uuid").UUID(b["id"]))
    assert row is not None  # kept for the record, never deleted


async def test_a_cancelled_or_finished_booking_cannot_be_changed(client: AsyncClient) -> None:
    s = await salon(client)
    cancelled = await make(client, s, 10)
    await client.delete(f"/bookings/{cancelled['id']}", headers=s.owner.headers)
    finished = await make(client, s, 12, name="N", phone="+923008888888")
    await client.patch(
        f"/bookings/{finished['id']}", json={"status": "completed"}, headers=s.owner.headers
    )

    for booking in (cancelled, finished):
        for method, body in (
            ("DELETE", None),
            ("PATCH", {"starts_at": at(MONDAY, 16)}),
            ("PATCH", {"status": "no_show"}),
        ):
            response = await client.request(
                method, f"/bookings/{booking['id']}", json=body, headers=s.owner.headers
            )
            assert response.status_code == 409, (booking["status"], method, body)
            assert response.json()["error"]["code"] == "booking_not_active"


async def test_a_manager_records_how_the_visit_went(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Cut")
    member = await create_staff(
        client, w.owner_a, w.downtown["id"], "Dana", [service["id"]], user_id=w.staff_a.id
    )
    s = Salon(w.owner_a, w.downtown["id"], service, member)
    b = await make(client, s, 10)
    done = await client.patch(
        f"/bookings/{b['id']}", json={"status": "no_show"}, headers=w.manager_a.headers
    )
    assert done.status_code == 200 and done.json()["status"] == "no_show"
    other = await make(client, s, 12, name="N", phone="+923008888888")
    refused = await client.patch(
        f"/bookings/{other['id']}", json={"status": "completed"}, headers=w.staff_a.headers
    )
    assert refused.status_code == 403


# --- The notice window ---


async def test_changes_far_ahead_are_free_but_close_ones_need_a_manager(
    client: AsyncClient,
) -> None:
    s = await salon(client)
    start = await soon(client, s)  # at least a day away
    created = await client.post(
        "/bookings",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "starts_at": start,
            "customer": {"full_name": "Ayesha", "phone": "+923001234567"},
        },
        headers={**s.owner.headers, "Idempotency-Key": key()},
    )
    booking = created.json()

    await set_notice(client, s, 43200)  # 30 days' notice: this booking is now "too close"
    blocked_cancel = await client.delete(f"/bookings/{booking['id']}", headers=s.owner.headers)
    blocked_move = await client.patch(
        f"/bookings/{booking['id']}",
        json={"notes": "x", "staff_id": s.staff["id"]},
        headers=s.owner.headers,
    )
    for response in (blocked_cancel, blocked_move):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cancellation_window_passed"
        assert response.json()["error"]["details"]["window_minutes"] == 43200

    forced = await client.delete(
        f"/bookings/{booking['id']}", params={"force": "true"}, headers=s.owner.headers
    )
    assert forced.status_code == 200 and forced.json()["status"] == "cancelled"

    await set_notice(client, s, 120)  # the normal two hours: plenty of notice
    again = await client.post(
        "/bookings",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "starts_at": start,
            "customer": {"full_name": "Ayesha", "phone": "+923001234567"},
        },
        headers={**s.owner.headers, "Idempotency-Key": key()},
    )
    assert (
        await client.delete(f"/bookings/{again.json()['id']}", headers=s.owner.headers)
    ).status_code == 200


async def test_the_notice_period_can_differ_per_location(client: AsyncClient) -> None:
    s = await salon(client)
    start = await soon(client, s)
    await set_notice(client, s, 43200)
    await client.patch(
        f"/locations/{s.location_id}",
        json={"cancellation_window_minutes": 0},
        headers=s.owner.headers,
    )
    created = await client.post(
        "/bookings",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "starts_at": start,
            "customer": {"full_name": "A", "phone": "+923001234567"},
        },
        headers={**s.owner.headers, "Idempotency-Key": key()},
    )
    # The location's own "no notice needed" beats the business's 30 days.
    assert (
        await client.delete(f"/bookings/{created.json()['id']}", headers=s.owner.headers)
    ).status_code == 200


async def test_only_a_manager_may_override_the_notice_period(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Cut")
    member = await create_staff(
        client, w.owner_a, w.downtown["id"], "Dana", [service["id"]], user_id=w.staff_a.id
    )
    s = Salon(w.owner_a, w.downtown["id"], service, member)
    start = await soon(client, s)
    await set_notice(client, s, 43200)
    created = (
        await client.post(
            "/bookings",
            json={
                "location_id": s.location_id,
                "service_id": service["id"],
                "staff_id": member["id"],
                "starts_at": start,
                "customer": {"full_name": "A", "phone": "+923001234567"},
            },
            headers={**w.owner_a.headers, "Idempotency-Key": key()},
        )
    ).json()
    url = f"/bookings/{created['id']}"
    plain = await client.delete(url, headers=w.staff_a.headers)
    assert (
        plain.status_code == 409 and plain.json()["error"]["code"] == "cancellation_window_passed"
    )
    assert (
        await client.delete(url, params={"force": "true"}, headers=w.staff_a.headers)
    ).status_code == 403
    by_manager = await client.delete(url, params={"force": "true"}, headers=w.manager_a.headers)
    assert by_manager.status_code == 200  # the Downtown manager may


# --- Listing and filters ---


async def seed_three(client: AsyncClient, s: Salon) -> list[dict[str, Any]]:
    ali = await create_staff(client, s.owner, s.location_id, "Ali", [s.service["id"]])
    return [
        await make(client, s, 10, name="Ayesha Khan", phone="+923001111111"),
        await make(client, s, 12, name="Bilal Ahmed", phone="+923002222222"),
        (
            await book(
                client,
                s,
                at(TUESDAY, 11),
                name="Chand Bibi",
                phone="+923003333333",
                staff_id=ali["id"],
            )
        ).json(),
    ]


async def ids(client: AsyncClient, s: Salon, **params: str) -> list[str]:
    response = await client.get("/bookings", params=params, headers=s.owner.headers)
    assert response.status_code == 200, response.text
    return [b["customer"]["full_name"] for b in response.json()["items"]]


async def test_list_is_soonest_first_and_filterable(client: AsyncClient) -> None:
    s = await salon(client)
    _, second, third = await seed_three(client, s)
    assert await ids(client, s) == ["Ayesha Khan", "Bilal Ahmed", "Chand Bibi"]
    assert await ids(client, s, staff_id=third["staff_id"]) == ["Chand Bibi"]
    assert await ids(client, s, location_id=s.location_id) == [
        "Ayesha Khan",
        "Bilal Ahmed",
        "Chand Bibi",
    ]
    assert await ids(client, s, source="voice") == []
    assert await ids(client, s, source="dashboard") == ["Ayesha Khan", "Bilal Ahmed", "Chand Bibi"]
    await client.delete(
        f"/bookings/{second['id']}", params={"force": "true"}, headers=s.owner.headers
    )
    assert await ids(client, s, status="cancelled") == ["Bilal Ahmed"]
    assert await ids(client, s, status="booked") == ["Ayesha Khan", "Chand Bibi"]


async def test_date_filters_use_the_salons_timezone(client: AsyncClient) -> None:
    s = await salon(client)
    await seed_three(client, s)
    # 10:00 and 12:00 on Monday (05:00Z and 07:00Z) are Monday in Karachi; Tuesday's is Tuesday.
    assert await ids(client, s, **{"from": MONDAY, "to": MONDAY}) == ["Ayesha Khan", "Bilal Ahmed"]
    assert await ids(client, s, **{"from": TUESDAY}) == ["Chand Bibi"]
    assert await ids(client, s, **{"to": "2030-01-06"}) == []
    assert await ids(client, s, **{"from": at(MONDAY, 11), "to": at(MONDAY, 12)}) == ["Bilal Ahmed"]
    naive = await client.get(
        "/bookings", params={"from": "2030-01-07T10:00:00"}, headers=s.owner.headers
    )
    assert naive.status_code == 422  # a timestamp without a timezone is ambiguous


async def test_a_late_night_booking_belongs_to_its_local_day(client: AsyncClient) -> None:
    """00:30 in Karachi is 19:30Z the previous day: a UTC-based filter would get this wrong."""
    s = await salon(client)
    await client.put(
        f"/locations/{s.location_id}/hours",
        json=[{"weekday": 1, "start": "00:00", "end": "23:00"}],
        headers=s.owner.headers,
    )
    await client.put(
        f"/staff/{s.staff['id']}/hours",
        json=[{"weekday": 1, "start": "00:00", "end": "23:00"}],
        headers=s.owner.headers,
    )
    late = await book(client, s, "2030-01-07T19:30:00Z")  # = Tuesday 2030-01-08 00:30 Karachi
    assert late.status_code == 201, late.text
    assert await ids(client, s, **{"from": TUESDAY, "to": TUESDAY}) == ["Ayesha Khan"]
    assert await ids(client, s, **{"from": MONDAY, "to": MONDAY}) == []


async def test_search_by_name_phone_and_reference(client: AsyncClient) -> None:
    s = await salon(client)
    first, *_ = await seed_three(client, s)
    assert await ids(client, s, q="bilal") == ["Bilal Ahmed"]
    assert await ids(client, s, q="0300 3333") == ["Chand Bibi"]
    assert await ids(client, s, q="+923002222222") == ["Bilal Ahmed"]
    assert await ids(client, s, q=first["reference"].lower()) == ["Ayesha Khan"]
    assert await ids(client, s, q="nobody") == []
    assert await ids(client, s, q="%") == []  # wildcards are plain characters


async def test_pagination_visits_every_booking_once(client: AsyncClient) -> None:
    s = await salon(client)
    await seed_three(client, s)
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/bookings", params=params, headers=s.owner.headers)).json()
        seen += [b["customer"]["full_name"] for b in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == ["Ayesha Khan", "Bilal Ahmed", "Chand Bibi"] and pages == 2
    assert (
        await client.get("/bookings", params={"limit": 501}, headers=s.owner.headers)
    ).status_code == 422
    assert (
        await client.get("/bookings", params={"cursor": "junk"}, headers=s.owner.headers)
    ).status_code == 422


@pytest.mark.parametrize(
    "params", [{"from": "tomorrow"}, {"to": "2030-13-45"}, {"status": "weird"}, {"source": "fax"}]
)
async def test_bad_filters_are_validation_errors(
    client: AsyncClient, params: dict[str, str]
) -> None:
    s = await salon(client)
    assert (
        await client.get("/bookings", params=params, headers=s.owner.headers)
    ).status_code == 422


# --- Who can see and change what ---


async def test_managers_and_staff_only_see_their_own_bookings(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Cut")
    dana = await create_staff(
        client, w.owner_a, w.downtown["id"], "Dana", [service["id"]], user_id=w.staff_a.id
    )
    eli = await create_staff(client, w.owner_a, w.downtown["id"], "Eli", [service["id"]])
    uma = await create_staff(client, w.owner_a, w.uptown["id"], "Uma", [service["id"]])

    def booking(
        location: dict[str, Any], member: dict[str, Any], hour: int, name: str, phone: str
    ) -> Any:
        return client.post(
            "/bookings",
            json={
                "location_id": location["id"],
                "service_id": service["id"],
                "staff_id": member["id"],
                "starts_at": at(MONDAY, hour),
                "customer": {"full_name": name, "phone": phone},
            },
            headers={**w.owner_a.headers, "Idempotency-Key": key()},
        )

    d = (await booking(w.downtown, dana, 10, "For Dana", "+923001000001")).json()
    e = (await booking(w.downtown, eli, 10, "For Eli", "+923001000002")).json()
    u = (await booking(w.uptown, uma, 10, "For Uma", "+923001000003")).json()

    async def names(who: Session) -> list[str]:
        return [
            b["customer"]["full_name"]
            for b in (await client.get("/bookings", headers=who.headers)).json()["items"]
        ]

    assert sorted(await names(w.owner_a)) == ["For Dana", "For Eli", "For Uma"]
    assert sorted(await names(w.manager_a)) == ["For Dana", "For Eli"]  # their location only
    assert await names(w.manager_a_uptown) == ["For Uma"]
    assert await names(w.staff_a) == ["For Dana"]  # only their own appointments

    assert (await client.get(f"/bookings/{e['id']}", headers=w.staff_a.headers)).status_code == 404
    assert (
        await client.get(f"/bookings/{u['id']}", headers=w.manager_a.headers)
    ).status_code == 404
    assert (
        await client.patch(f"/bookings/{u['id']}", json={"notes": "x"}, headers=w.manager_a.headers)
    ).status_code == 404
    assert (
        await client.delete(f"/bookings/{u['id']}", headers=w.manager_a.headers)
    ).status_code == 404
    assert (await client.get(f"/bookings/{d['id']}", headers=w.staff_a.headers)).status_code == 200


async def test_staff_not_linked_to_a_stylist_see_nothing(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Cut")
    member = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    s = Salon(w.owner_a, w.downtown["id"], service, member)
    await make(client, s, 10)
    assert (await client.get("/bookings", headers=w.staff_a.headers)).json()["items"] == []


async def test_front_desk_staff_can_book_and_a_manager_can_not_book_elsewhere(
    client: AsyncClient,
) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Cut")
    dana = await create_staff(
        client, w.owner_a, w.downtown["id"], "Dana", [service["id"]], user_id=w.staff_a.id
    )
    uma = await create_staff(client, w.owner_a, w.uptown["id"], "Uma", [service["id"]])
    own = await client.post(
        "/bookings",
        json={
            "location_id": w.downtown["id"],
            "service_id": service["id"],
            "staff_id": dana["id"],
            "starts_at": at(MONDAY, 10),
            "customer": {"full_name": "Walk-in", "phone": "+923001234567"},
        },
        headers={**w.staff_a.headers, "Idempotency-Key": key()},
    )
    assert own.status_code == 201
    elsewhere = await client.post(
        "/bookings",
        json={
            "location_id": w.uptown["id"],
            "service_id": service["id"],
            "staff_id": uma["id"],
            "starts_at": at(MONDAY, 10),
            "customer": {"full_name": "X", "phone": "+923001234568"},
        },
        headers={**w.manager_a.headers, "Idempotency-Key": key()},
    )
    assert elsewhere.status_code == 404


async def test_another_business_cannot_see_or_change_a_booking(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Cut")
    member = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    b = await make(client, Salon(w.owner_a, w.downtown["id"], service, member), 10)
    for method, body in (("GET", None), ("PATCH", {"notes": "x"}), ("DELETE", None)):
        response = await client.request(
            method, f"/bookings/{b['id']}", json=body, headers=w.owner_b.headers
        )
        assert response.status_code == 404, method
    assert (await client.get("/bookings", headers=w.owner_b.headers)).json()["items"] == []
    assert (await client.get(f"/bookings/{b['id']}", headers=w.owner_a.headers)).json()[
        "status"
    ] == "booked"


# --- Customers ---


async def test_customers_list_search_and_history(client: AsyncClient) -> None:
    s = await salon(client)
    first, _, _ = await seed_three(client, s)
    await make(
        client, s, 14, name="Ayesha Khan", phone="0300 1111111"
    )  # a second visit, same number
    listing = (await client.get("/customers", headers=s.owner.headers)).json()
    by_name = {c["full_name"]: c for c in listing["items"]}
    assert set(by_name) == {"Ayesha Khan", "Bilal Ahmed", "Chand Bibi"}
    assert (
        by_name["Ayesha Khan"]["booking_count"] == 2
        and by_name["Bilal Ahmed"]["booking_count"] == 1
    )
    assert by_name["Ayesha Khan"]["last_visit_at"] is None  # nothing completed yet

    found = (await client.get("/customers", params={"q": "bilal"}, headers=s.owner.headers)).json()[
        "items"
    ]
    assert [c["full_name"] for c in found] == ["Bilal Ahmed"]
    by_phone = (
        await client.get("/customers", params={"q": "300 3333"}, headers=s.owner.headers)
    ).json()["items"]
    assert [c["full_name"] for c in by_phone] == ["Chand Bibi"]

    await client.patch(
        f"/bookings/{first['id']}", json={"status": "completed"}, headers=s.owner.headers
    )
    detail = (
        await client.get(f"/customers/{by_name['Ayesha Khan']['id']}", headers=s.owner.headers)
    ).json()
    assert len(detail["bookings"]) == 2
    assert detail["bookings"][0]["starts_at"] > detail["bookings"][1]["starts_at"]  # newest first
    assert detail["last_visit_at"] == first["starts_at"]


async def test_customers_are_visible_only_where_they_booked_and_only_to_managers(
    client: AsyncClient,
) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Cut")
    dana = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    uma = await create_staff(client, w.owner_a, w.uptown["id"], "Uma", [service["id"]])
    await make(
        client,
        Salon(w.owner_a, w.downtown["id"], service, dana),
        10,
        name="Downtown Dora",
        phone="+923001000001",
    )
    up = await make(
        client,
        Salon(w.owner_a, w.uptown["id"], service, uma),
        10,
        name="Uptown Ume",
        phone="+923001000002",
    )

    def names(response: Any) -> list[str]:
        return sorted(c["full_name"] for c in response.json()["items"])

    assert names(await client.get("/customers", headers=w.owner_a.headers)) == [
        "Downtown Dora",
        "Uptown Ume",
    ]
    assert names(await client.get("/customers", headers=w.manager_a.headers)) == ["Downtown Dora"]
    assert (await client.get("/customers", headers=w.staff_a.headers)).status_code == 403
    assert (await client.get("/customers", headers=w.owner_b.headers)).json()["items"] == []
    assert (
        await client.get(f"/customers/{up['customer']['id']}", headers=w.manager_a.headers)
    ).status_code == 404
    assert (
        await client.get(f"/customers/{up['customer']['id']}", headers=w.owner_b.headers)
    ).status_code == 404
    assert (
        await client.get(f"/customers/{up['customer']['id']}", headers=w.staff_a.headers)
    ).status_code == 403
    assert (
        await client.get(f"/customers/{up['customer']['id']}", headers=w.owner_a.headers)
    ).status_code == 200


async def test_status_enum_is_what_the_database_stores(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    b = await make(client, s, 10)
    await client.delete(f"/bookings/{b['id']}", params={"force": "true"}, headers=s.owner.headers)
    assert (await db.scalars(select(Appointment.status))).all() == [AppointmentStatus.cancelled]
