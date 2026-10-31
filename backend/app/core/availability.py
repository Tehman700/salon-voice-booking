"""Which appointment times are free? Pure logic, no database.

A slot is offered when, for one staff member and one service, the whole appointment
  - falls on a day the location is open (and not closed for the day),
  - sits inside both the location's opening hours and the staff member's working hours,
  - does not overlap time off or an existing appointment (including its cleanup buffer),
  - is not in the past.

All wall-clock times (opening hours, working hours) are in the location's timezone; everything
else is timezone-aware UTC. Working through local time per day keeps daylight-saving changes right:
a local time that does not exist (spring-forward gap) is never offered.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SLOT_STEP_MINUTES = 15

Interval = tuple[datetime, datetime]  # [start, end) in aware UTC
Block = tuple[time, time]  # [start, end) in the location's local time


@dataclass(frozen=True)
class StaffSchedule:
    staff_id: uuid.UUID
    name: str
    working_hours: dict[int, list[Block]]  # weekday (0 = Monday) -> blocks
    time_off: list[Interval] = field(default_factory=list)
    # Existing appointments, each already extended by its cleanup buffer.
    busy: list[Interval] = field(default_factory=list)


@dataclass(frozen=True)
class LocationSchedule:
    timezone: ZoneInfo
    opening_hours: dict[int, list[Block]]
    closed_dates: frozenset[date] = frozenset()


@dataclass(frozen=True)
class SlotResult:
    starts_at: datetime
    ends_at: datetime  # end of the appointment itself (buffer not included)
    staff_id: uuid.UUID
    staff_name: str


def local_to_utc(day: date, at: time, tz: ZoneInfo) -> datetime | None:
    """The UTC instant for a local wall-clock time, or None if that time does not exist."""
    local = datetime.combine(day, at, tzinfo=tz)
    utc = local.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None  # skipped by a spring-forward change
    return utc


def intersect_blocks(first: Iterable[Block], second: Iterable[Block]) -> list[Block]:
    """The parts of the day covered by both lists of blocks."""
    second_list = list(second)
    result: list[Block] = []
    for a_start, a_end in first:
        for b_start, b_end in second_list:
            start, end = max(a_start, b_start), min(a_end, b_end)
            if start < end:
                result.append((start, end))
    return sorted(result)


def overlaps(start: datetime, end: datetime, intervals: Iterable[Interval]) -> bool:
    return any(start < other_end and other_start < end for other_start, other_end in intervals)


def _minutes(at: time) -> int:
    return at.hour * 60 + at.minute


def compute_slots(
    *,
    location: LocationSchedule,
    staff: Iterable[StaffSchedule],
    days: Iterable[date],
    duration_minutes: int,
    buffer_minutes: int = 0,
    now: datetime,
    step_minutes: int = SLOT_STEP_MINUTES,
) -> list[SlotResult]:
    """Every free start time for the given staff on the given days, sorted by time then name."""
    duration = timedelta(minutes=duration_minutes)
    occupied = timedelta(minutes=duration_minutes + buffer_minutes)
    staff_list = list(staff)
    slots: list[SlotResult] = []

    for day in days:
        if day in location.closed_dates:
            continue
        weekday = day.weekday()
        open_blocks = location.opening_hours.get(weekday, [])
        for member in staff_list:
            for block_start, block_end in intersect_blocks(
                open_blocks, member.working_hours.get(weekday, [])
            ):
                end_utc = local_to_utc(day, block_end, location.timezone)
                if end_utc is None:
                    continue
                # Start times sit on the clock grid (:00, :15, ...) from the block's start.
                minute = -(-_minutes(block_start) // step_minutes) * step_minutes
                while minute < _minutes(block_end):
                    start_utc = local_to_utc(
                        day, time(minute // 60, minute % 60), location.timezone
                    )
                    minute += step_minutes
                    if start_utc is None:
                        continue
                    if start_utc + duration > end_utc:
                        break
                    if start_utc < now:
                        continue
                    blocked_until = start_utc + occupied
                    if overlaps(start_utc, blocked_until, member.time_off) or overlaps(
                        start_utc, blocked_until, member.busy
                    ):
                        continue
                    slots.append(
                        SlotResult(
                            starts_at=start_utc,
                            ends_at=start_utc + duration,
                            staff_id=member.staff_id,
                            staff_name=member.name,
                        )
                    )
    slots.sort(key=lambda s: (s.starts_at, s.staff_name, str(s.staff_id)))
    return slots
