"""The voice agent's tools, called exactly as Retell calls them.

The property under test throughout: a tool says `success: true` only when the backend really did
the thing, so the agent can never promise a booking that does not exist.
"""

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient

from tests.booking_helpers import MONDAY, SUNDAY, TUESDAY, Salon, at, book, salon, set_notice, soon
from tests.helpers import build_world, create_service, create_staff, signup
from tests.retell_helpers import CALLER, SALON_NUMBER, call_object, sign, tool

pytestmark = pytest.mark.usefixtures("retell_key")


async def bookings(client: AsyncClient, s: Salon, **params: str) -> list[dict[str, Any]]:
    response = await client.get("/bookings", params=params, headers=s.owner.headers)
    return list(response.json()["items"])


async def make_booking(
    client: AsyncClient, s: Salon, *, time: str = "10:00", day: str = MONDAY, **extra: Any
) -> dict[str, Any]:
    args = {
        "service_id": s.service["id"],
        "staff_id": s.staff["id"],
        "date": day,
        "time": time,
        "customer_name": "Ayesha Khan",
        **extra,
    }
    return await tool(client, "create_booking", args)


# --- Information ---


async def test_salon_info_has_hours_and_todays_date(client: AsyncClient) -> None:
    s = await salon(client)
    info = await tool(client, "get_salon_info")
    assert info["success"] is True
    assert info["name"] == "Main Street"
    assert info["phone"] == SALON_NUMBER
    assert any(line.startswith("Monday: 10:00 AM to 7:00 PM") for line in info["opening_hours"])
    assert not any(line.startswith("Sunday") for line in info["opening_hours"])
    assert len(info["today"]) == 10 and info["timezone"] == "Asia/Karachi"
    assert s.location_id


async def test_services_and_stylists_are_listed_with_ids_the_agent_can_pass_back(
    client: AsyncClient,
) -> None:
    s = await salon(client)
    services = (await tool(client, "list_services"))["services"]
    assert [x["name"] for x in services] == ["Haircut"]
    assert services[0]["service_id"] == s.service["id"] and services[0]["minutes"] == 60
    staff = (await tool(client, "list_staff", {"service_id": s.service["id"]}))["staff"]
    assert [x["name"] for x in staff] == ["Sana"] and staff[0]["staff_id"] == s.staff["id"]


async def test_a_service_nobody_performs_is_not_offered(client: AsyncClient) -> None:
    s = await salon(client)
    await create_service(client, s.owner, "Mystery treatment")  # no stylist does it
    names = [x["name"] for x in (await tool(client, "list_services"))["services"]]
    assert names == ["Haircut"]


# --- Checking availability ---


async def test_availability_offers_real_free_times_in_local_wording(client: AsyncClient) -> None:
    s = await salon(client)
    result = await tool(
        client, "check_availability", {"service_id": s.service["id"], "date": MONDAY}
    )
    assert result["success"] is True and result["slots_date"] == MONDAY
    slots = result["slots"]
    assert 1 <= len(slots) <= 6
    assert slots[0] == {
        "date": MONDAY,
        "time": "10:00",
        "spoken": "Monday, January 7 at 10:00 AM",
        "staff_id": s.staff["id"],
        "staff_name": "Sana",
    }
    assert all(slot["date"] == MONDAY for slot in slots)


async def test_availability_skips_to_the_next_open_day_and_says_so(client: AsyncClient) -> None:
    s = await salon(client)
    result = await tool(
        client, "check_availability", {"service_id": s.service["id"], "date": SUNDAY}
    )
    assert result["slots_date"] == "2030-01-14"  # Sunday is closed, so Monday
    assert "Nothing free on Sunday, January 13" in result["message"]


async def test_availability_can_ask_for_a_part_of_the_day(client: AsyncClient) -> None:
    s = await salon(client)
    args = {"service_id": s.service["id"], "date": MONDAY}
    evening = (await tool(client, "check_availability", {**args, "time_of_day": "evening"}))[
        "slots"
    ]
    assert evening and all(int(x["time"][:2]) >= 17 for x in evening)
    late = (await tool(client, "check_availability", {**args, "after": "16:30"}))["slots"]
    assert late and all(x["time"] >= "16:30" for x in late)


async def test_availability_leaves_out_booked_times(client: AsyncClient) -> None:
    s = await salon(client)
    await book(client, s, at(MONDAY, 10))
    slots = (
        await tool(client, "check_availability", {"service_id": s.service["id"], "date": MONDAY})
    )["slots"]
    assert "10:00" not in [x["time"] for x in slots]


async def test_availability_refuses_dates_in_the_past_and_unknown_services(
    client: AsyncClient,
) -> None:
    s = await salon(client)
    past = await tool(
        client, "check_availability", {"service_id": s.service["id"], "date": "2020-01-06"}
    )
    assert past["success"] is False and past["error"] == "past_date"
    unknown = await tool(
        client,
        "check_availability",
        {"service_id": "00000000-0000-0000-0000-000000000000", "date": MONDAY},
    )
    assert unknown["success"] is False


# --- Booking ---


async def test_a_booking_is_real_and_traceable_to_the_call(client: AsyncClient) -> None:
    s = await salon(client)
    call = call_object()
    result = await tool(
        client,
        "create_booking",
        {
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "date": MONDAY,
            "time": "10:00",
            "customer_name": "Ayesha Khan",
            "notes": "First visit",
        },
        call=call,
    )
    assert result["success"] is True
    assert result["when"] == "Monday, January 7 at 10:00 AM"
    assert result["staff"] == "Sana" and result["service"] == "Haircut"
    assert result["reference_spoken"] == " ".join(result["reference"])

    [booking] = await bookings(client, s)
    assert booking["reference"] == result["reference"]
    assert booking["starts_at"] == at(MONDAY, 10)
    assert booking["source"] == "voice" and booking["call_id"] is not None
    assert booking["customer"]["phone"] == CALLER  # taken from caller ID
    assert booking["notes"] == "First visit"

    calls = (await client.get("/calls", headers=s.owner.headers)).json()["items"]
    assert [c["retell_call_id"] for c in calls] == [call["call_id"]]
    assert calls[0]["outcome"] == "booked" and calls[0]["booking_id"] == booking["id"]


async def test_the_caller_can_give_a_different_number(client: AsyncClient) -> None:
    s = await salon(client)
    result = await make_booking(client, s, phone="0300 7654321")
    assert result["success"] is True
    assert (await bookings(client, s))[0]["customer"]["phone"] == "+923007654321"


async def test_booking_without_any_phone_number_asks_for_one(client: AsyncClient) -> None:
    s = await salon(client)
    anonymous = call_object(from_=None)
    result = await tool(
        client,
        "create_booking",
        {
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "date": MONDAY,
            "time": "10:00",
            "customer_name": "Ayesha",
        },
        call=anonymous,
    )
    assert result["success"] is False and result["error"] == "need_phone"
    assert await bookings(client, s) == []


async def test_a_taken_time_is_refused_with_alternatives_and_nothing_is_booked(
    client: AsyncClient,
) -> None:
    s = await salon(client)
    await book(client, s, at(MONDAY, 10), name="Someone Else", phone="+923008888888")
    result = await make_booking(client, s, time="10:00")
    assert result["success"] is False and result["error"] == "slot_unavailable"
    assert "reference" not in result
    times = [a["time"] for a in result["alternatives"]]
    assert times and "10:00" not in times
    assert len(await bookings(client, s)) == 1  # still only the first one


async def test_a_repeated_tool_call_is_one_booking_not_two(client: AsyncClient) -> None:
    s = await salon(client)
    call = call_object()
    args = {
        "service_id": s.service["id"],
        "staff_id": s.staff["id"],
        "date": MONDAY,
        "time": "10:00",
        "customer_name": "Ayesha Khan",
    }
    first = await tool(client, "create_booking", args, call=call)
    again = await tool(client, "create_booking", args, call=call)
    assert first["success"] is True and again["success"] is True
    assert again["reference"] == first["reference"]
    assert len(await bookings(client, s)) == 1


async def test_two_callers_racing_for_one_slot_get_one_booking(client: AsyncClient) -> None:
    s = await salon(client)
    args = {
        "service_id": s.service["id"],
        "staff_id": s.staff["id"],
        "date": MONDAY,
        "time": "10:00",
    }
    results = await asyncio.gather(
        *(
            tool(
                client,
                "create_booking",
                {**args, "customer_name": f"Caller {i}"},
                call=call_object(from_=f"+92300555010{i}"),
            )
            for i in range(4)
        )
    )
    assert sum(r["success"] for r in results) == 1
    assert all(r["error"] == "slot_unavailable" for r in results if not r["success"])
    assert len(await bookings(client, s)) == 1


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"time": "25:00"}, "invalid_time"),
        ({"time": "10:75"}, "invalid_time"),
        ({"date": "2020-01-06"}, "slot_unavailable"),  # in the past: not bookable
        ({"time": "07:00"}, "slot_unavailable"),  # before opening
        ({"date": SUNDAY}, "slot_unavailable"),  # closed
    ],
)
async def test_impossible_times_are_refused_and_nothing_is_booked(
    client: AsyncClient, changes: dict[str, str], error: str
) -> None:
    s = await salon(client)
    result = await make_booking(client, s, **changes)
    assert result["success"] is False and result["error"] == error
    assert await bookings(client, s) == []


async def test_missing_arguments_are_reported_by_name(client: AsyncClient) -> None:
    await salon(client)
    result = await tool(client, "create_booking", {"time": "10:00"})
    assert result["success"] is False and result["error"] == "invalid_arguments"
    for field in ("service_id", "staff_id", "date", "customer_name"):
        assert field in result["message"]


async def test_a_stylist_who_does_not_do_the_service_is_refused(client: AsyncClient) -> None:
    s = await salon(client)
    colour = await create_service(client, s.owner, "Colour", duration_minutes=90)
    result = await tool(
        client,
        "create_booking",
        {
            "service_id": colour["id"],
            "staff_id": s.staff["id"],
            "date": MONDAY,
            "time": "10:00",
            "customer_name": "Ayesha",
        },
    )
    assert result["success"] is False
    assert await bookings(client, s) == []


# --- Finding, moving and cancelling ---


async def test_a_caller_finds_their_own_bookings_by_caller_id(client: AsyncClient) -> None:
    s = await salon(client)
    made = await make_booking(client, s)
    found = await tool(client, "find_my_bookings")
    assert [b["reference"] for b in found["bookings"]] == [made["reference"]]
    assert found["bookings"][0]["when"] == "Monday, January 7 at 10:00 AM"
    stranger = await tool(client, "find_my_bookings", call=call_object(from_="+923009990000"))
    assert stranger["success"] is True and stranger["bookings"] == []


async def test_asking_about_someone_elses_number_needs_their_name(client: AsyncClient) -> None:
    s = await salon(client)
    await make_booking(client, s)
    elsewhere = call_object(from_="+923009990000")
    no_name = await tool(client, "find_my_bookings", {"phone": CALLER}, call=elsewhere)
    wrong = await tool(
        client, "find_my_bookings", {"phone": CALLER, "customer_name": "Zed"}, call=elsewhere
    )
    right = await tool(
        client, "find_my_bookings", {"phone": CALLER, "customer_name": "ayesha"}, call=elsewhere
    )
    assert no_name["bookings"] == [] and wrong["bookings"] == []
    assert len(right["bookings"]) == 1


async def test_reschedule_moves_the_booking_and_frees_the_old_time(client: AsyncClient) -> None:
    s = await salon(client)
    made = await make_booking(client, s)
    args = {
        "reference": made["reference"],
        "customer_name": "Ayesha",
        "date": TUESDAY,
        "time": "14:00",
    }
    moved = await tool(client, "reschedule_booking", args)
    assert moved["success"] is True and moved["when"] == "Tuesday, January 8 at 2:00 PM"
    [booking] = await bookings(client, s)
    assert booking["starts_at"] == at(TUESDAY, 14) and booking["reference"] == made["reference"]
    assert booking["source"] == "voice"  # created by phone; the change is in the audit trail
    free = await tool(client, "check_availability", {"service_id": s.service["id"], "date": MONDAY})
    assert "10:00" in [x["time"] for x in free["slots"]]


async def test_reference_is_forgiving_about_spacing_and_case(client: AsyncClient) -> None:
    s = await salon(client)
    made = await make_booking(client, s)
    spoken = " ".join(made["reference"].lower())
    result = await tool(
        client,
        "reschedule_booking",
        {"reference": spoken, "customer_name": "Ayesha Khan", "date": TUESDAY, "time": "11:00"},
    )
    assert result["success"] is True


async def test_reschedule_to_a_taken_time_changes_nothing(client: AsyncClient) -> None:
    s = await salon(client)
    made = await make_booking(client, s)
    await book(client, s, at(TUESDAY, 14), name="Someone Else", phone="+923008888888")
    result = await tool(
        client,
        "reschedule_booking",
        {
            "reference": made["reference"],
            "customer_name": "Ayesha",
            "date": TUESDAY,
            "time": "14:00",
        },
    )
    assert result["success"] is False and result["error"] == "slot_unavailable"
    assert result["alternatives"]
    mine = next(b for b in await bookings(client, s) if b["reference"] == made["reference"])
    assert mine["starts_at"] == at(MONDAY, 10)


async def test_cancel_frees_the_time(client: AsyncClient) -> None:
    s = await salon(client)
    made = await make_booking(client, s)
    result = await tool(
        client,
        "cancel_booking",
        {"reference": made["reference"], "customer_name": "Ayesha Khan", "reason": "Plans changed"},
    )
    assert result["success"] is True and "Cancelled" in result["message"]
    [booking] = await bookings(client, s)
    assert booking["status"] == "cancelled" and booking["cancellation_reason"] == "Plans changed"
    free = await tool(client, "check_availability", {"service_id": s.service["id"], "date": MONDAY})
    assert "10:00" in [x["time"] for x in free["slots"]]
    again = await tool(
        client, "cancel_booking", {"reference": made["reference"], "customer_name": "Ayesha"}
    )
    assert again["success"] is False  # nothing left to cancel; the agent must not say it worked


@pytest.mark.parametrize("who", ["wrong name", "wrong phone", "wrong reference"])
async def test_only_the_booking_owner_can_change_it(client: AsyncClient, who: str) -> None:
    s = await salon(client)
    made = await make_booking(client, s)
    args = {"reference": made["reference"], "customer_name": "Ayesha"}
    call = call_object()
    if who == "wrong name":
        args["customer_name"] = "Zed Zulu"
    elif who == "wrong phone":
        call = call_object(from_="+923009990000")
    else:
        args["reference"] = "ZZZZZ"
    for name, extra in (
        ("cancel_booking", {}),
        ("reschedule_booking", {"date": TUESDAY, "time": "11:00"}),
    ):
        result = await tool(client, name, {**args, **extra}, call=call)
        assert result["success"] is False and result["error"] == "not_found"
    [booking] = await bookings(client, s)
    assert booking["status"] == "booked" and booking["starts_at"] == at(MONDAY, 10)


async def test_close_to_the_appointment_the_agent_cannot_change_it(client: AsyncClient) -> None:
    """The notice period binds the agent; only a human manager can override it."""
    s = await salon(client)
    start = await soon(client, s)
    created = await book(client, s, start, phone=CALLER)
    await set_notice(client, s, 43200)  # 30 days: everything is now "too close"
    reference = created.json()["reference"]
    local_date = start[:10]

    cancelled = await tool(
        client, "cancel_booking", {"reference": reference, "customer_name": "Ayesha"}
    )
    moved = await tool(
        client,
        "reschedule_booking",
        {"reference": reference, "customer_name": "Ayesha", "date": local_date, "time": "10:00"},
    )
    for result in (cancelled, moved):
        assert result["success"] is False and result["error"] == "too_late_to_change"
        assert SALON_NUMBER in result["message"]  # tells the caller who to ring
    assert (await bookings(client, s))[0]["status"] == "booked"


# --- Routing and isolation ---


async def test_an_unknown_number_or_tool_is_refused_politely(client: AsyncClient) -> None:
    await salon(client)
    lost = await tool(client, "get_salon_info", call=call_object(to="+14155550123"))
    assert lost["success"] is False and lost["error"] == "unknown_salon"
    nothing = await tool(client, "get_salon_info", call=call_object(to=None))
    assert nothing["error"] == "unknown_salon"
    unknown = await tool(client, "launch_missiles")
    assert unknown["success"] is False and unknown["error"] == "unknown_tool"


async def test_the_dialled_number_may_be_written_any_way(client: AsyncClient) -> None:
    await salon(client)
    info = await tool(client, "get_salon_info", call=call_object(to="0092 300 1234567"))
    assert info["success"] is True


async def test_a_location_can_be_pinned_with_a_dynamic_variable(client: AsyncClient) -> None:
    s = await salon(client)
    pinned = call_object(
        to="+10000000000", retell_llm_dynamic_variables={"location_id": s.location_id}
    )
    assert (await tool(client, "get_salon_info", call=pinned))["success"] is True
    bad = call_object(to=None, retell_llm_dynamic_variables={"location_id": "not-a-uuid"})
    assert (await tool(client, "get_salon_info", call=bad))["error"] == "unknown_salon"


async def test_a_location_can_be_pinned_in_the_tool_url(client: AsyncClient) -> None:
    """One agent per location: no phone number or dynamic variable needed (Retell web tests)."""
    s = await salon(client)
    nothing_else = call_object(to=None, from_=None)  # exactly what a browser test call looks like
    assert (await tool(client, "get_salon_info", call=nothing_else))["error"] == "unknown_salon"
    pinned = await tool(client, "get_salon_info", call=nothing_else, location_id=s.location_id)
    assert pinned["success"] is True and pinned["name"] == "Main Street"
    # The URL wins over a dynamic variable and over the dialled number.
    other = await signup(client, business_name="Other", email="other@example.com")
    conflicting = call_object(retell_llm_dynamic_variables={"location_id": other.location_ids[0]})
    winner = await tool(client, "get_salon_info", call=conflicting, location_id=s.location_id)
    assert winner["success"] is True
    bad = await client.post(
        "/retell/functions/get_salon_info?location_id=nope",
        content=b"{}",
        headers={"x-retell-signature": sign(b"{}")},
    )
    assert bad.status_code == 422
    gone = await tool(
        client,
        "get_salon_info",
        call=nothing_else,
        location_id="00000000-0000-0000-0000-000000000000",
    )
    assert gone["error"] == "unknown_salon"


async def test_each_line_reaches_only_its_own_salon(client: AsyncClient) -> None:
    w = await build_world(client)
    for number, location in (("+922100000001", w.downtown), ("+922100000002", w.uptown)):
        await client.patch(
            f"/locations/{location['id']}", json={"phone": number}, headers=w.owner_a.headers
        )
    downtown = await tool(client, "get_salon_info", call=call_object(to="+922100000001"))
    uptown = await tool(client, "get_salon_info", call=call_object(to="+922100000002"))
    assert (downtown["name"], uptown["name"]) == ("Downtown", "Uptown")
    # Business B's phone is the same as the old shared test number, which A no longer uses.
    beta = await tool(client, "get_salon_info", call=call_object(to=SALON_NUMBER))
    assert beta["name"] == "Main Street"


async def test_two_salons_sharing_a_number_route_nowhere(client: AsyncClient) -> None:
    await build_world(client)  # all four locations share the default test number
    result = await tool(client, "get_salon_info", call=call_object(to=SALON_NUMBER))
    assert result["success"] is False and result["error"] == "unknown_salon"


async def test_a_call_cannot_touch_another_businesses_data(client: AsyncClient) -> None:
    w = await build_world(client)
    await client.patch(
        f"/locations/{w.downtown['id']}", json={"phone": "+922100000001"}, headers=w.owner_a.headers
    )
    await client.patch(
        f"/locations/{w.uptown['id']}", json={"phone": "+922100000002"}, headers=w.owner_a.headers
    )
    a_service = await create_service(client, w.owner_a, "Cut")
    a_staff = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [a_service["id"]])
    b_service = await create_service(client, w.owner_b, "Cut", duration_minutes=60)
    b_staff = await create_staff(client, w.owner_b, w.location_b["id"], "Bea", [b_service["id"]])
    b_salon = Salon(w.owner_b, w.location_b["id"], b_service, b_staff)
    b_booking = (await book(client, b_salon, at(MONDAY, 10))).json()

    into_a = call_object(to="+922100000001")
    # Business B's service and stylist ids are invisible from salon A's line.
    forged = await tool(
        client,
        "create_booking",
        {
            "service_id": b_service["id"],
            "staff_id": b_staff["id"],
            "date": MONDAY,
            "time": "12:00",
            "customer_name": "Mallory",
        },
        call=into_a,
    )
    assert forged["success"] is False
    # Even with the right reference, name and phone, B's booking is not reachable from A.
    owner_phone = b_booking["customer"]["phone"]
    stolen = await tool(
        client,
        "cancel_booking",
        {"reference": b_booking["reference"], "customer_name": "Ayesha Khan"},
        call=call_object(to="+922100000001", from_=owner_phone),
    )
    assert stolen["success"] is False and stolen["error"] == "not_found"
    seen = await tool(
        client, "find_my_bookings", call=call_object(to="+922100000001", from_=owner_phone)
    )
    assert seen["bookings"] == []
    still = (await client.get("/bookings", headers=w.owner_b.headers)).json()["items"]
    assert [b["status"] for b in still] == ["booked"]
    assert a_staff["id"]


async def test_a_line_only_sees_its_own_locations_bookings(client: AsyncClient) -> None:
    """Two locations of one business: a caller to Uptown cannot cancel their Downtown booking."""
    w = await build_world(client)
    for number, location in (("+922100000001", w.downtown), ("+922100000002", w.uptown)):
        await client.patch(
            f"/locations/{location['id']}", json={"phone": number}, headers=w.owner_a.headers
        )
    service = await create_service(client, w.owner_a, "Cut", duration_minutes=60)
    dana = await create_staff(client, w.owner_a, w.downtown["id"], "Dana", [service["id"]])
    made = await tool(
        client,
        "create_booking",
        {
            "service_id": service["id"],
            "staff_id": dana["id"],
            "date": MONDAY,
            "time": "10:00",
            "customer_name": "Ayesha Khan",
        },
        call=call_object(to="+922100000001"),
    )
    assert made["success"] is True
    from_uptown = call_object(to="+922100000002")
    result = await tool(
        client,
        "cancel_booking",
        {"reference": made["reference"], "customer_name": "Ayesha Khan"},
        call=from_uptown,
    )
    assert result["success"] is False and result["error"] == "not_found"


async def test_the_same_call_id_cannot_be_replayed_at_another_location(client: AsyncClient) -> None:
    owner = await signup(client, business_name="One", email="one@example.com")
    other = await signup(client, business_name="Two", email="two@example.com")
    for session, number in ((owner, "+922100000001"), (other, "+922100000002")):
        await client.patch(
            f"/locations/{session.location_ids[0]}",
            json={"phone": number},
            headers=session.headers,
        )
    shared_id = "call_shared_id"
    first = await tool(client, "get_salon_info", call=call_object(shared_id, to="+922100000001"))
    second = await tool(client, "get_salon_info", call=call_object(shared_id, to="+922100000002"))
    assert first["success"] is True
    assert second["success"] is False and second["error"] == "call_mismatch"
