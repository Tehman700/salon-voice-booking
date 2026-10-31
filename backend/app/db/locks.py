import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business import Business


async def lock_business(session: AsyncSession, business_id: uuid.UUID) -> None:
    """Serialise administrative changes to one business until the transaction ends.

    Rules like "keep at least one active owner/location" read other rows before changing one, so
    two concurrent requests could each pass the check and together break the rule. Taking this
    lock first (always before any row-level lock) makes them queue instead, and avoids deadlocks
    from locking rows in different orders. It is a `FOR NO KEY UPDATE` lock, so ordinary inserts
    that reference the business (new locations, invites, bookings) are not blocked.
    """
    await session.execute(
        select(Business.id).where(Business.id == business_id).with_for_update(key_share=True)
    )
