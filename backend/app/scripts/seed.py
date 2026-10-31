"""Create a demo business for local development: `uv run python -m app.scripts.seed`.

Idempotent, and refuses to run outside local/test so demo accounts can never reach a deployed
database. All demo accounts share one password (SEED_PASSWORD, default below).
"""

import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models.business import Business, LocationMode
from app.models.location import Location
from app.models.user import Role, User

DEFAULT_PASSWORD = "demo-password-123"  # noqa: S105  (local demo data only)
BUSINESS_SLUG = "demo-salons"

ACCOUNTS = [
    ("owner@demo.example.com", "Olivia Owner", Role.owner, None),
    ("manager@demo.example.com", "Mehr Manager", Role.manager, "downtown"),
    ("staff@demo.example.com", "Sana Stylist", Role.staff, "downtown"),
]


async def seed(session: AsyncSession, password: str = DEFAULT_PASSWORD) -> bool:
    """Create the demo data. Returns False if it already exists."""
    if await session.scalar(select(Business.id).where(Business.slug == BUSINESS_SLUG)):
        return False

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
    await session.commit()
    return True


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
        print("Demo business already exists; nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
