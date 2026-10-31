"""Create a demo business for local development: `uv run python -m app.scripts.seed`.

Idempotent, and refuses to run outside local/test so demo accounts can never reach a deployed
database. All demo accounts share one password (SEED_PASSWORD, default below).
"""

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.principal import Principal
from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models.booking import Appointment
from app.models.business import Business, LocationMode
from app.models.catalog import Service
from app.models.location import Location
from app.models.staff import Staff, StaffService, StaffWorkingHours
from app.models.user import Role, User
from app.schemas.booking import BookingCreate, CustomerIn
from app.schemas.catalog import AvailabilityRequest
from app.services.availability import find_slots
from app.services.bookings import create_booking
from app.services.scheduling import (
    DEFAULT_CLOSE,
    DEFAULT_OPEN,
    DEFAULT_OPEN_WEEKDAYS,
    add_default_hours,
)

DEFAULT_PASSWORD = "demo-password-123"  # noqa: S105  (local demo data only)
BUSINESS_SLUG = "demo-salons"

ACCOUNTS = [
    ("owner@demo.example.com", "Olivia Owner", Role.owner, None),
    ("manager@demo.example.com", "Mehr Manager", Role.manager, "downtown"),
    ("staff@demo.example.com", "Sana Stylist", Role.staff, "downtown"),
]


# (name, category, minutes, buffer, price in minor units)
SERVICES = [
    ("Women's haircut", "Hair", 45, 0, 350000),
    ("Blow-dry", "Hair", 30, 0, 150000),
    ("Colour (root touch-up)", "Hair", 90, 10, 600000),
    ("Classic facial", "Skin", 60, 0, 450000),
    ("Manicure", "Nails", 45, 0, 200000),
]
# (name, title, color, location, indexes into SERVICES)
STAFF = [
    ("Sana Iqbal", "Senior stylist", "#0070f3", "downtown", [0, 1, 2]),
    ("Mariam Shah", "Colourist", "#7928ca", "downtown", [2, 3]),
    ("Ali Raza", "Stylist", "#f5a623", "uptown", [0, 1, 4]),
    ("Nida Hassan", "Beauty therapist", "#eb367f", "uptown", [3, 4]),
]


async def _seed_catalog(session: AsyncSession, business: Business) -> bool:
    """Add services, staff and their hours if the business has none. Returns True if it did."""
    if await session.scalar(select(Service.id).where(Service.business_id == business.id)):
        return False
    locations = {
        loc.slug: loc
        for loc in await session.scalars(
            select(Location).where(Location.business_id == business.id)
        )
    }
    services = []
    for name, category, minutes, buffer, price in SERVICES:
        service = Service(
            business_id=business.id,
            name=name,
            category=category,
            duration_minutes=minutes,
            buffer_minutes=buffer,
            price_minor=price,
        )
        session.add(service)
        services.append(service)
    await session.flush()

    for name, title, color, location_slug, service_indexes in STAFF:
        location = locations.get(location_slug)
        if location is None:
            continue
        member = Staff(
            business_id=business.id,
            location_id=location.id,
            full_name=name,
            title=title,
            color=color,
        )
        session.add(member)
        await session.flush()
        for index in service_indexes:
            session.add(
                StaffService(
                    business_id=business.id, staff_id=member.id, service_id=services[index].id
                )
            )
        for weekday in DEFAULT_OPEN_WEEKDAYS:
            session.add(
                StaffWorkingHours(
                    business_id=business.id,
                    staff_id=member.id,
                    weekday=weekday,
                    start_time=DEFAULT_OPEN,
                    end_time=DEFAULT_CLOSE,
                )
            )
    return True


CUSTOMERS = [
    ("Ayesha Khan", "+923001230001"),
    ("Bilal Ahmed", "+923001230002"),
    ("Fatima Noor", "+923001230003"),
    ("Hamza Ali", "+923001230004"),
    ("Zainab Malik", "+923001230005"),
    ("Usman Tariq", "+923001230006"),
]


async def _seed_bookings(session: AsyncSession, business: Business) -> bool:
    """Book a few real, valid appointments over the next two weeks so the calendar isn't empty.

    Goes through the same booking service as the app, so every demo booking obeys the real rules.
    """
    if await session.scalar(select(Appointment.id).where(Appointment.business_id == business.id)):
        return False
    owner = await session.scalar(
        select(User).where(User.business_id == business.id, User.role == Role.owner)
    )
    if owner is None:
        return False
    principal = Principal(
        user_id=owner.id, business_id=business.id, role=Role.owner, location_id=None
    )
    today = datetime.now(UTC).date()
    staff_members = list(
        await session.scalars(
            select(Staff).where(Staff.business_id == business.id).order_by(Staff.full_name)
        )
    )
    made = 0
    for index, member in enumerate(staff_members):
        link = await session.scalar(
            select(StaffService).where(StaffService.staff_id == member.id).limit(1)
        )
        if link is None:
            continue
        slots = await find_slots(
            session,
            principal,
            AvailabilityRequest(
                location_id=member.location_id,
                service_id=link.service_id,
                staff_id=member.id,
                date_from=today + timedelta(days=1),
                date_to=today + timedelta(days=7),
            ),
        )
        # Spread out: every 9th slot, a few per stylist.
        for offset, slot in enumerate(slots[::9][:4]):
            name, phone = CUSTOMERS[(index + offset) % len(CUSTOMERS)]
            await create_booking(
                session,
                principal,
                BookingCreate(
                    location_id=member.location_id,
                    service_id=link.service_id,
                    staff_id=member.id,
                    starts_at=slot.starts_at,
                    customer=CustomerIn(full_name=name, phone=phone),
                ),
                idempotency_key=f"seed-{member.id}-{offset}",
            )
            made += 1
    return made > 0


async def seed(session: AsyncSession, password: str = DEFAULT_PASSWORD) -> bool:
    """Create the demo data, or top up what is missing. Returns False if nothing was needed."""
    business = await session.scalar(select(Business).where(Business.slug == BUSINESS_SLUG))
    created = business is None
    if business is None:
        business = Business(
            name="Demo Salons",
            slug=BUSINESS_SLUG,
            location_mode=LocationMode.multiple,
            default_timezone="Asia/Karachi",
        )
        session.add(business)
        await session.flush()

        locations = {
            "downtown": Location(
                business_id=business.id,
                name="Downtown",
                slug="downtown",
                timezone="Asia/Karachi",
                phone="+923001110001",
                city="Karachi",
                country="PK",
            ),
            "uptown": Location(
                business_id=business.id,
                name="Uptown",
                slug="uptown",
                timezone="Asia/Karachi",
                phone="+923001110002",
                city="Lahore",
                country="PK",
            ),
        }
        session.add_all(locations.values())
        await session.flush()
        for location in locations.values():
            add_default_hours(session, business.id, location.id)

        password_hash = hash_password(password)
        for email, full_name, role, location_slug in ACCOUNTS:
            session.add(
                User(
                    business_id=business.id,
                    location_id=locations[location_slug].id if location_slug else None,
                    email=email,
                    password_hash=password_hash,
                    full_name=full_name,
                    role=role,
                )
            )
    added_catalog = await _seed_catalog(session, business)
    await session.commit()
    added_bookings = await _seed_bookings(session, business)
    await session.commit()
    return created or added_catalog or added_bookings


async def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    settings = get_settings()
    password = os.environ.get("SEED_PASSWORD")
    if not settings.is_dev_like:
        # A deployed database is public-facing: never fall back to the well-known demo password.
        if "--allow-remote" not in args:
            print(
                f"Refusing to seed demo data in the '{settings.environment}' environment "
                "(pass --allow-remote and set SEED_PASSWORD to do it on purpose)."
            )
            return 1
        if not password or len(password) < 10:
            print("--allow-remote needs SEED_PASSWORD set to at least 10 characters.")
            return 1
    password = password or DEFAULT_PASSWORD
    async with get_sessionmaker()() as session:
        created = await seed(session, password)
    if created:
        print("Created the demo business. Sign in with any of:")
        for email, _, role, _ in ACCOUNTS:
            print(f"  {role.value:<8} {email}  /  {password}")
    else:
        print("Demo data already complete; nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
