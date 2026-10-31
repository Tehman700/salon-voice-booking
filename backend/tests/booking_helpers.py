"""Shared helpers for the booking tests."""

import uuid
from typing import Any

from httpx import AsyncClient, Response

from tests.helpers import Session, create_service, create_staff, signup

MONDAY = "2030-01-07"  # Monday, safely in the future. Karachi is UTC+5, so 10:00 local = 05:00Z
TUESDAY = "2030-01-08"
SUNDAY = "2030-01-13"  # closed by default


def at(day: str, hour: int, minute: int = 0) -> str:
    """A Karachi wall-clock time as a UTC instant, e.g. at(MONDAY, 10) -> 2030-01-07T05:00:00Z."""
    return f"{day}T{hour - 5:02d}:{minute:02d}:00Z"


def key() -> str:
    return f"key-{uuid.uuid4()}"


class Salon:
    def __init__(
        self, owner: Session, location_id: str, service: dict[str, Any], staff: dict[str, Any]
    ):
        self.owner, self.location_id, self.service, self.staff = owner, location_id, service, staff


async def salon(client: AsyncClient, **service_overrides: Any) -> Salon:
    """One salon, open Mon-Sat 10-19, a 60-minute haircut and one stylist (Sana)."""
    owner = await signup(client)
    location_id = owner.location_ids[0]
    service = await create_service(
        client, owner, "Haircut", duration_minutes=60, **service_overrides
    )
    staff = await create_staff(client, owner, location_id, "Sana", [service["id"]])
    return Salon(owner, location_id, service, staff)


async def book(
    client: AsyncClient,
    s: Salon,
    start: str,
    *,
    who: Session | None = None,
    name: str = "Ayesha Khan",
    phone: str = "+923001234567",
    idem: str | None = None,
    staff_id: str | None = None,
    **extra: Any,
) -> Response:
    return await client.post(
        "/bookings",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "staff_id": staff_id or s.staff["id"],
            "starts_at": start,
            "customer": {"full_name": name, "phone": phone},
            **extra,
        },
        headers={**(who or s.owner).headers, "Idempotency-Key": idem or key()},
    )


async def free_times(client: AsyncClient, s: Salon, day: str = MONDAY) -> list[str]:
    response = await client.post(
        "/availability",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "date_from": day,
            "date_to": day,
        },
        headers=s.owner.headers,
    )
    return [slot["starts_at"] for slot in response.json()["slots"]]
