"""The availability engine is pure logic, so these tests need no database."""

import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.core.availability import (
    LocationSchedule,
    StaffSchedule,
    compute_slots,
    intersect_blocks,
    local_to_utc,
)

KARACHI = ZoneInfo("Asia/Karachi")  # UTC+5, no daylight saving
NEW_YORK = ZoneInfo("America/New_York")
MONDAY = date(2026, 11, 2)
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


def location(
    hours: dict[int, list[tuple[time, time]]], tz: ZoneInfo = KARACHI, **kw: object
) -> LocationSchedule:
    return LocationSchedule(timezone=tz, opening_hours=hours, **kw)  # type: ignore[arg-type]


def stylist(
    name: str = "Sana", hours: dict[int, list[tuple[time, time]]] | None = None, **kw: object
) -> StaffSchedule:
    return StaffSchedule(
        staff_id=uuid.uuid4(),
        name=name,
        working_hours=hours if hours is not None else {0: [(time(10), time(12))]},
        **kw,  # type: ignore[arg-type]
    )


def starts(slots: list, tz: ZoneInfo = KARACHI) -> list[str]:  # type: ignore[type-arg]
    return [s.starts_at.astimezone(tz).strftime("%H:%M") for s in slots]


OPEN_10_12 = {0: [(time(10), time(12))]}


def slots_for(**kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "location": location(OPEN_10_12),
        "staff": [stylist()],
        "days": [MONDAY],
        "duration_minutes": 60,
        "now": LONG_AGO,
    }
    args.update(kw)
    return compute_slots(**args)  # type: ignore[arg-type]


def test_offers_every_fifteen_minutes_while_the_service_still_fits() -> None:
    assert starts(slots_for()) == ["10:00", "10:15", "10:30", "10:45", "11:00"]


def test_slot_end_is_start_plus_duration() -> None:
    first = slots_for()[0]
    assert (first.ends_at - first.starts_at).total_seconds() == 3600


def test_times_are_utc_instants_of_the_local_clock() -> None:
    first = slots_for()[0]
    assert first.starts_at == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)  # 10:00 in Karachi


def test_a_longer_service_has_fewer_start_times() -> None:
    assert starts(slots_for(duration_minutes=90)) == ["10:00", "10:15", "10:30"]
    assert slots_for(duration_minutes=150) == []


def test_buffer_blocks_neighbours_but_may_run_past_closing() -> None:
    busy = [
        (datetime(2026, 11, 2, 6, 0, tzinfo=UTC), datetime(2026, 11, 2, 6, 30, tzinfo=UTC))
    ]  # 11:00-11:30
    without_buffer = starts(slots_for(staff=[stylist(busy=busy)], duration_minutes=30))
    with_buffer = starts(
        slots_for(staff=[stylist(busy=busy)], duration_minutes=30, buffer_minutes=15)
    )
    assert "10:30" in without_buffer  # ends exactly when the busy block starts
    assert "10:30" not in with_buffer  # its 15-minute cleanup would run into it
    assert "11:30" in with_buffer  # the last slot may need cleanup after closing time


def test_existing_appointments_remove_overlapping_times_only() -> None:
    busy = [
        (datetime(2026, 11, 2, 5, 30, tzinfo=UTC), datetime(2026, 11, 2, 6, 30, tzinfo=UTC))
    ]  # 10:30-11:30
    assert starts(slots_for(staff=[stylist(busy=busy)], duration_minutes=30)) == ["10:00", "11:30"]


def test_time_off_removes_times() -> None:
    off = [
        (datetime(2026, 11, 2, 5, 0, tzinfo=UTC), datetime(2026, 11, 2, 6, 0, tzinfo=UTC))
    ]  # 10:00-11:00
    assert starts(slots_for(staff=[stylist(time_off=off)], duration_minutes=30)) == [
        "11:00",
        "11:15",
        "11:30",
    ]


def test_a_closed_date_has_no_times() -> None:
    assert slots_for(location=location(OPEN_10_12, closed_dates=frozenset({MONDAY}))) == []


def test_a_weekday_without_hours_has_no_times() -> None:
    assert slots_for(days=[date(2026, 11, 3)]) == []  # Tuesday: nothing defined
    assert (
        slots_for(staff=[stylist(hours={1: [(time(10), time(12))]})]) == []
    )  # staff off on Monday


def test_only_the_overlap_of_location_and_staff_hours_counts() -> None:
    assert starts(
        slots_for(
            location=location({0: [(time(9), time(11))]}),
            staff=[stylist(hours={0: [(time(10), time(13))]})],
            duration_minutes=30,
        )
    ) == ["10:00", "10:15", "10:30"]


def test_split_shifts_are_respected() -> None:
    shifts = {0: [(time(10), time(11)), (time(15), time(16))]}
    assert starts(
        slots_for(
            location=location({0: [(time(9), time(18))]}),
            staff=[stylist(hours=shifts)],
            duration_minutes=60,
        )
    ) == ["10:00", "15:00"]


def test_times_in_the_past_are_not_offered() -> None:
    now = datetime(2026, 11, 2, 5, 20, tzinfo=UTC)  # 10:20 Karachi
    assert starts(slots_for(now=now)) == ["10:30", "10:45", "11:00"]


def test_several_staff_sorted_by_time_then_name() -> None:
    result = slots_for(staff=[stylist("Zara"), stylist("Ali")], duration_minutes=105)
    assert [(s.staff_name, t) for s, t in zip(result, starts(result), strict=True)] == [
        ("Ali", "10:00"),
        ("Zara", "10:00"),
        ("Ali", "10:15"),
        ("Zara", "10:15"),
    ]


def test_several_days() -> None:
    hours = {0: [(time(10), time(11))], 1: [(time(10), time(11))]}
    result = compute_slots(
        location=location(hours),
        staff=[stylist(hours=hours)],
        days=[MONDAY, date(2026, 11, 3)],
        duration_minutes=60,
        now=LONG_AGO,
    )
    assert [s.starts_at.date() for s in result] == [MONDAY, date(2026, 11, 3)]


def test_blocks_not_on_the_grid_start_at_the_next_grid_time() -> None:
    assert starts(
        slots_for(
            location=location({0: [(time(10, 5), time(11))]}),
            staff=[stylist(hours={0: [(time(10, 5), time(11))]})],
            duration_minutes=30,
        )
    ) == ["10:15", "10:30"]


def test_intersect_blocks() -> None:
    assert intersect_blocks(
        [(time(9), time(12))], [(time(10), time(11)), (time(11, 30), time(14))]
    ) == [
        (time(10), time(11)),
        (time(11, 30), time(12)),
    ]
    assert intersect_blocks([(time(9), time(10))], [(time(10), time(11))]) == []


# --- Daylight saving ---


def test_a_local_time_skipped_by_spring_forward_does_not_exist() -> None:
    assert local_to_utc(date(2026, 3, 8), time(2, 30), NEW_YORK) is None
    assert local_to_utc(date(2026, 3, 8), time(3, 30), NEW_YORK) == datetime(
        2026, 3, 8, 7, 30, tzinfo=UTC
    )


def test_spring_forward_day_never_offers_the_missing_hour() -> None:
    sunday = date(2026, 3, 8)  # New York clocks jump from 02:00 to 03:00
    hours = {6: [(time(1), time(4))]}
    result = compute_slots(
        location=location(hours, NEW_YORK),
        staff=[stylist(hours=hours)],
        days=[sunday],
        duration_minutes=30,
        now=LONG_AGO,
    )
    local = starts(result, NEW_YORK)
    assert not any(t.startswith("02") for t in local)
    assert {"01:00", "01:45", "03:00", "03:30"} <= set(local)
    assert len({s.starts_at for s in result}) == len(result)  # no duplicates


def test_fall_back_day_offers_each_instant_once() -> None:
    sunday = date(2026, 11, 1)  # 01:00-02:00 happens twice in New York
    hours = {6: [(time(0), time(3))]}
    result = compute_slots(
        location=location(hours, NEW_YORK),
        staff=[stylist(hours=hours)],
        days=[sunday],
        duration_minutes=30,
        now=LONG_AGO,
    )
    instants = [s.starts_at for s in result]
    assert len(instants) == len(set(instants))
    assert instants == sorted(instants)


def test_winter_and_summer_offsets_differ_for_the_same_wall_clock() -> None:
    hours = {0: [(time(9), time(10))]}
    winter, summer = date(2026, 1, 12), date(2026, 7, 13)  # both Mondays
    for day, utc_hour in ((winter, 14), (summer, 13)):
        first = compute_slots(
            location=location(hours, NEW_YORK),
            staff=[stylist(hours=hours)],
            days=[day],
            duration_minutes=30,
            now=LONG_AGO,
        )[0]
        assert first.starts_at.hour == utc_hour
