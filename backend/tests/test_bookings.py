"""Creating bookings, and above all: a time can never be sold twice."""

import asyncio
import uuid
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Appointment, AppointmentEvent, AppointmentStatus, BookingSource
from tests.booking_helpers import MONDAY, SUNDAY, TUESDAY, at, book, free_times, key, salon
from tests.helpers import build_world, create_service, create_staff

# --- The happy path ---


async def test_create_a_booking(client: AsyncClient) -> None:
    s = await salon(client)
    response = await book(client, s, at(MONDAY, 10), notes="Bring a photo")
    assert response.status_code == 201, response.text
    b = response.json()
    assert len(b["reference"]) == 5 and b["reference"].isalnum() and b["reference"].isupper()
    assert (b["status"], b["source"], b["notes"]) == ("booked", "dashboard", "Bring a photo")
    assert b["starts_at"] == at(MONDAY, 10)
    assert b["ends_at"] == at(MONDAY, 11)  # a 60-minute service
    assert (b["price_minor"], b["currency"]) == (350000, "PKR")
    assert b["customer"]["full_name"] == "Ayesha Khan" and b["customer"]["phone"] == "+923001234567"
    assert b["call_id"] is None and b["cancelled_at"] is None and b["created_at"]

    fetched = (await client.get(f"/bookings/{b['id']}", headers=s.owner.headers)).json()
    assert fetched == b
    listed = (await client.get("/bookings", headers=s.owner.headers)).json()["items"]
    assert [x["id"] for x in listed] == [b["id"]]


async def test_a_booked_time_is_no_longer_offered(client: AsyncClient) -> None:
    s = await salon(client)
    before = await free_times(client, s)
    assert at(MONDAY, 10) in before
    await book(client, s, at(MONDAY, 10))
    after = await free_times(client, s)
    assert after[0] == at(MONDAY, 11)  # 10:00-11:00 is taken; the next start is 11:00 sharp
    assert at(MONDAY, 10, 30) not in after and at(MONDAY, 9, 30) not in after


async def test_the_cleanup_buffer_is_blocked_too(client: AsyncClient) -> None:
    s = await salon(client, buffer_minutes=15)
    await book(client, s, at(MONDAY, 10))
    assert (await free_times(client, s))[0] == at(MONDAY, 11, 15)
    # 11:00 would collide with the 15-minute cleanup after the first appointment.
    assert (
        await book(client, s, at(MONDAY, 11), name="Other", phone="+923009999999")
    ).status_code == 409
    assert (
        await book(client, s, at(MONDAY, 11, 15), name="Other", phone="+923009999999")
    ).status_code == 201


async def test_different_stylists_can_take_the_same_time(client: AsyncClient) -> None:
    s = await salon(client)
    ali = await create_staff(client, s.owner, s.location_id, "Ali", [s.service["id"]])
    first = await book(client, s, at(MONDAY, 10))
    second = await book(
        client, s, at(MONDAY, 10), staff_id=ali["id"], name="B", phone="+923002222222"
    )
    assert first.status_code == second.status_code == 201


# --- Double booking ---


async def test_the_same_time_cannot_be_booked_twice(client: AsyncClient) -> None:
    s = await salon(client)
    assert (await book(client, s, at(MONDAY, 10))).status_code == 201
    second = await book(client, s, at(MONDAY, 10), name="Someone Else", phone="+923007777777")
    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "slot_unavailable"
    alternatives = error["details"]["alternatives"]
    assert 1 <= len(alternatives) <= 5
    free = set(await free_times(client, s))
    assert all(a["starts_at"] in free for a in alternatives)  # every alternative really is free
    assert all(a["staff_name"] == "Sana" for a in alternatives)
    assert all(a["starts_at"] != at(MONDAY, 10) for a in alternatives)
    # Only one appointment exists.
    assert len((await client.get("/bookings", headers=s.owner.headers)).json()["items"]) == 1


@pytest.mark.parametrize(
    ("hour", "minute", "ok"),
    [(10, 0, False), (10, 30, False), (10, 45, False), (11, 0, True), (11, 15, True)],
)
async def test_times_overlapping_an_appointment_are_refused_and_later_ones_allowed(
    client: AsyncClient, hour: int, minute: int, ok: bool
) -> None:
    s = await salon(client)
    await book(client, s, at(MONDAY, 10))  # occupies 10:00-11:00
    response = await book(client, s, at(MONDAY, hour, minute), name="N", phone="+923003333333")
    assert response.status_code == (201 if ok else 409), (hour, minute, response.text)


async def test_an_appointment_may_end_exactly_when_the_next_one_starts(client: AsyncClient) -> None:
    s = await salon(client)
    await book(client, s, at(MONDAY, 11))  # occupies 11:00-12:00
    assert (
        await book(client, s, at(MONDAY, 10, 15), name="N", phone="+923003333333")
    ).status_code == 409
    assert (
        await book(client, s, at(MONDAY, 10), name="N", phone="+923003333333")
    ).status_code == 201


async def test_many_simultaneous_requests_for_one_time_book_it_exactly_once(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    results = await asyncio.gather(
        *(
            book(client, s, at(MONDAY, 10), name=f"Person {i}", phone=f"+92300000000{i}")
            for i in range(8)
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 7, codes
    assert all(
        r.json()["error"]["code"] == "slot_unavailable" for r in results if r.status_code == 409
    )
    assert await db.scalar(select(func.count()).select_from(Appointment)) == 1


async def test_simultaneous_requests_for_overlapping_times_never_overlap(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    starts = [
        at(MONDAY, 10),
        at(MONDAY, 10, 15),
        at(MONDAY, 10, 30),
        at(MONDAY, 10, 45),
        at(MONDAY, 11),
    ]
    results = await asyncio.gather(
        *(book(client, s, t, name=f"P{i}", phone=f"+92301000000{i}") for i, t in enumerate(starts))
    )
    booked = sorted(
        (await db.execute(select(Appointment.starts_at, Appointment.blocked_until))).all()
    )
    assert any(r.status_code == 201 for r in results)
    for (_, earlier_end), (later_start, _) in pairwise(booked):
        assert earlier_end <= later_start  # whatever won, nothing overlaps


async def test_simultaneous_requests_for_different_times_all_succeed(client: AsyncClient) -> None:
    s = await salon(client)
    starts = [at(MONDAY, h) for h in (10, 11, 12, 13, 14, 15)]
    results = await asyncio.gather(
        *(book(client, s, t, name=f"P{i}", phone=f"+92302000000{i}") for i, t in enumerate(starts))
    )
    assert [r.status_code for r in results] == [201] * 6


async def test_a_cancelled_time_can_be_booked_again(client: AsyncClient) -> None:
    s = await salon(client)
    first = (await book(client, s, at(MONDAY, 10))).json()
    assert (
        await book(client, s, at(MONDAY, 10), name="X", phone="+923004444444")
    ).status_code == 409
    cancelled = await client.delete(
        f"/bookings/{first['id']}", params={"force": "true"}, headers=s.owner.headers
    )
    assert cancelled.status_code == 200
    again = await book(client, s, at(MONDAY, 10), name="X", phone="+923004444444")
    assert again.status_code == 201


# --- The database enforces it on its own ---


async def test_the_database_itself_refuses_overlapping_appointments(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    booking = (await book(client, s, at(MONDAY, 10))).json()
    original = await db.get(Appointment, uuid.UUID(booking["id"]))
    assert original is not None
    # Copy what we need now: after a rejected insert the loaded objects are expired.
    shared = {
        "business_id": original.business_id,
        "location_id": original.location_id,
        "service_id": original.service_id,
        "staff_id": original.staff_id,
        "customer_id": original.customer_id,
    }
    ten = original.starts_at

    def clone(start: datetime, minutes: int, **changes: Any) -> Appointment:
        end = start + timedelta(minutes=minutes)
        values: dict[str, Any] = {
            **shared,
            "reference": uuid.uuid4().hex[:5].upper(),
            "starts_at": start,
            "ends_at": end,
            "blocked_until": end,
            "status": AppointmentStatus.booked,
            "source": BookingSource.dashboard,
            "price_minor": 1,
            "currency": "PKR",
        }
        values.update(changes)
        return Appointment(**values)

    db.add(clone(ten + timedelta(minutes=30), 60))  # overlaps 10:00-11:00
    with pytest.raises(IntegrityError, match="ex_appointments_staff_no_overlap"):
        await db.commit()
    await db.rollback()

    db.add(clone(ten + timedelta(minutes=60), 60))  # starts exactly when the first one ends: fine
    await db.commit()

    db.add(clone(ten, 60, status=AppointmentStatus.cancelled))  # cancelled ones don't count
    await db.commit()

    db.add(clone(ten - timedelta(hours=5), 30, staff_id=uuid.uuid4()))  # unknown staff: foreign key
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_the_cleanup_buffer_counts_in_the_database_rule(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client, buffer_minutes=30)
    booking = (await book(client, s, at(MONDAY, 10))).json()
    row = await db.get(Appointment, uuid.UUID(booking["id"]))
    assert row is not None
    assert row.blocked_until - row.ends_at == timedelta(minutes=30)


# --- Retrying safely ---


async def test_repeating_a_request_with_the_same_key_returns_the_same_booking(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    k = key()
    first = await book(client, s, at(MONDAY, 10), idem=k)
    again = await book(client, s, at(MONDAY, 10), idem=k)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json() == first.json()
    assert await db.scalar(select(func.count()).select_from(Appointment)) == 1


async def test_a_key_reused_for_a_different_request_is_refused(client: AsyncClient) -> None:
    s = await salon(client)
    k = key()
    await book(client, s, at(MONDAY, 10), idem=k)
    different_time = await book(client, s, at(MONDAY, 12), idem=k)
    different_person = await book(client, s, at(MONDAY, 10), idem=k, phone="+923005555555")
    for response in (different_time, different_person):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "idempotency_key_reused"


async def test_simultaneous_identical_requests_make_one_booking(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    k = key()
    results = await asyncio.gather(*(book(client, s, at(MONDAY, 10), idem=k) for _ in range(6)))
    assert sorted(r.status_code for r in results).count(201) == 1
    assert {r.status_code for r in results} <= {200, 201}
    assert len({r.json()["id"] for r in results}) == 1
    assert await db.scalar(select(func.count()).select_from(Appointment)) == 1


async def test_a_retry_still_works_after_the_slot_changed(client: AsyncClient) -> None:
    """A client that never saw the first response can retry, even though the time is now taken."""
    s = await salon(client)
    k = key()
    first = await book(client, s, at(MONDAY, 10), idem=k)
    # Meanwhile the stylist is deactivated; a retry must still return the original booking.
    await client.delete(f"/staff/{s.staff['id']}", headers=s.owner.headers)
    again = await book(client, s, at(MONDAY, 10), idem=k)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]


async def test_the_idempotency_key_is_required(client: AsyncClient) -> None:
    s = await salon(client)
    response = await client.post(
        "/bookings",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "starts_at": at(MONDAY, 10),
            "customer": {"full_name": "A", "phone": "+923001234567"},
        },
        headers=s.owner.headers,
    )
    assert response.status_code == 422


# --- Times that can't be booked ---


@pytest.mark.parametrize(
    "start",
    [
        "2020-01-06T05:00:00Z",  # in the past
        at(SUNDAY, 10),  # the salon is closed
        at(MONDAY, 8),  # before opening
        at(MONDAY, 18, 30),  # would run past closing
        at(MONDAY, 10, 7),  # not on the 15-minute grid
    ],
)
async def test_unbookable_times_are_refused_with_alternatives(
    client: AsyncClient, start: str
) -> None:
    s = await salon(client)
    response = await book(client, s, start)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_unavailable"
    assert "alternatives" in response.json()["error"]["details"]


async def test_a_closure_and_time_off_block_booking(client: AsyncClient) -> None:
    s = await salon(client)
    await client.post(
        f"/locations/{s.location_id}/closures", json={"date": TUESDAY}, headers=s.owner.headers
    )
    assert (await book(client, s, at(TUESDAY, 10))).status_code == 409
    await client.post(
        f"/staff/{s.staff['id']}/time-off",
        json={"starts_at": at(MONDAY, 10), "ends_at": at(MONDAY, 12)},
        headers=s.owner.headers,
    )
    assert (await book(client, s, at(MONDAY, 10))).status_code == 409
    assert (await book(client, s, at(MONDAY, 12))).status_code == 201


async def test_a_per_location_duration_override_sets_the_appointment_length(
    client: AsyncClient,
) -> None:
    s = await salon(client)
    await client.patch(
        f"/services/{s.service['id']}",
        json={
            "location_overrides": [
                {"location_id": s.location_id, "duration_minutes": 30, "price_minor": 999}
            ]
        },
        headers=s.owner.headers,
    )
    b = (await book(client, s, at(MONDAY, 10))).json()
    assert b["ends_at"] == at(MONDAY, 10, 30)
    assert b["price_minor"] == 999


# --- Invalid requests ---


async def test_validation_errors(client: AsyncClient) -> None:
    s = await salon(client)
    naive = await book(client, s, "2030-01-07T10:00:00")
    bad_phone = await book(client, s, at(MONDAY, 10), phone="abc")
    short_phone = await book(client, s, at(MONDAY, 10), phone="12345678901234567890123")
    bad_email = await client.post(
        "/bookings",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "starts_at": at(MONDAY, 10),
            "customer": {"full_name": "A", "phone": "+923001234567", "email": "nope"},
        },
        headers={**s.owner.headers, "Idempotency-Key": key()},
    )
    assert (
        naive.status_code
        == bad_phone.status_code
        == short_phone.status_code
        == bad_email.status_code
        == 422
    )
    assert "customer.phone" in bad_phone.json()["error"]["details"]


async def test_the_stylist_must_be_able_to_do_the_service_at_that_location(
    client: AsyncClient,
) -> None:
    s = await salon(client)
    other = await create_service(client, s.owner, "Manicure")
    nails_only = await create_staff(client, s.owner, s.location_id, "Nails", [other["id"]])
    no_service = await book(client, s, at(MONDAY, 10), staff_id=nails_only["id"])
    assert no_service.status_code == 422 and "staff_id" in no_service.json()["error"]["details"]

    await client.delete(f"/staff/{s.staff['id']}", headers=s.owner.headers)
    inactive = await book(client, s, at(MONDAY, 10))
    assert inactive.status_code == 422

    await client.delete(f"/services/{s.service['id']}", headers=s.owner.headers)
    gone = await book(client, s, at(MONDAY, 10), staff_id=nails_only["id"])
    assert gone.status_code == 422 and "service_id" in gone.json()["error"]["details"]


async def test_a_service_switched_off_at_the_location_cannot_be_booked(client: AsyncClient) -> None:
    s = await salon(client)
    await client.patch(
        f"/services/{s.service['id']}",
        json={"location_overrides": [{"location_id": s.location_id, "is_offered": False}]},
        headers=s.owner.headers,
    )
    assert (await book(client, s, at(MONDAY, 10))).status_code == 422


# --- Customers are recognised by phone number ---


async def test_the_same_phone_in_any_format_is_one_customer(client: AsyncClient) -> None:
    s = await salon(client)
    first = (
        await book(client, s, at(MONDAY, 10), phone="+92 300 1234567", name="Ayesha Khan")
    ).json()
    second = (
        await book(client, s, at(MONDAY, 11), phone="0300-1234567", name="Ayesha K.", email=None)
    ).json()
    third = (await book(client, s, at(MONDAY, 12), phone="0092 300 1234567", name="Someone")).json()
    assert first["customer"]["id"] == second["customer"]["id"] == third["customer"]["id"]
    assert first["customer"]["phone"] == "+923001234567"
    assert second["customer"]["full_name"] == "Ayesha Khan"  # the existing record is kept
    customers = (await client.get("/customers", headers=s.owner.headers)).json()["items"]
    assert len(customers) == 1 and customers[0]["booking_count"] == 3


async def test_a_missing_email_is_filled_in_once_and_never_overwritten(client: AsyncClient) -> None:
    s = await salon(client)

    async def with_email(hour: int, email: str) -> dict[str, Any]:
        response = await client.post(
            "/bookings",
            json={
                "location_id": s.location_id,
                "service_id": s.service["id"],
                "staff_id": s.staff["id"],
                "starts_at": at(MONDAY, hour),
                "customer": {"full_name": "Ayesha", "phone": "+923001234567", "email": email},
            },
            headers={**s.owner.headers, "Idempotency-Key": key()},
        )
        return dict(response.json()["customer"])

    assert (await with_email(10, "first@example.com"))["email"] == "first@example.com"
    assert (await with_email(11, "second@example.com"))["email"] == "first@example.com"


# --- Other businesses and locations ---


async def test_other_businesses_ids_are_404(client: AsyncClient) -> None:
    w = await build_world(client)
    service = await create_service(client, w.owner_a, "Haircut")
    member = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    response = await client.post(
        "/bookings",
        json={
            "location_id": w.downtown["id"],
            "service_id": service["id"],
            "staff_id": member["id"],
            "starts_at": at(MONDAY, 10),
            "customer": {"full_name": "X", "phone": "+923001234567"},
        },
        headers={**w.owner_b.headers, "Idempotency-Key": key()},
    )
    assert response.status_code == 404


async def test_the_audit_trail_records_who_did_what(client: AsyncClient, db: AsyncSession) -> None:
    s = await salon(client)
    b = (await book(client, s, at(MONDAY, 10))).json()
    await client.patch(
        f"/bookings/{b['id']}", json={"starts_at": at(MONDAY, 12)}, headers=s.owner.headers
    )
    await client.delete(f"/bookings/{b['id']}", params={"force": "true"}, headers=s.owner.headers)
    events = (
        await db.execute(
            select(AppointmentEvent.event_type, AppointmentEvent.actor_user_id).order_by(
                AppointmentEvent.created_at
            )
        )
    ).all()
    assert [e[0] for e in events] == ["created", "rescheduled", "cancelled"]
    assert {str(e[1]) for e in events} == {s.owner.id}
