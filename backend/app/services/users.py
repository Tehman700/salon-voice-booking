"""Team members and invitations."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.principal import Principal
from app.core.security import generate_opaque_token, hash_opaque_token
from app.db.locks import lock_business
from app.models.invite import Invite
from app.models.user import Role, User
from app.repositories.tenant import LocationRepository, UserRepository
from app.schemas.user import InviteRequest, UserUpdate
from app.services.auth import EmailTakenError, revoke_all_sessions


class LastOwnerError(ConflictError):
    code = "last_owner"
    message = "A business must keep at least one active owner."


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(details={field: [message]})


async def list_users(
    session: AsyncSession, principal: Principal, *, limit: int, cursor: str | None
) -> tuple[list[User], str | None]:
    stmt = UserRepository(session, principal).select().order_by(User.created_at, User.id)
    if cursor:
        after_created_at, after_id = decode_cursor(cursor)
        stmt = stmt.where(tuple_(User.created_at, User.id) > tuple_(after_created_at, after_id))
    rows = list(await session.scalars(stmt.limit(limit + 1)))
    if len(rows) > limit:
        rows = rows[:limit]
        return rows, encode_cursor(rows[-1].created_at, rows[-1].id)
    return rows, None


async def update_user(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, body: UserUpdate
) -> User:
    await lock_business(session, principal.business_id)
    target = await UserRepository(session, principal).get(user_id, for_update=True)
    if target is None:
        raise NotFoundError
    fields = body.model_fields_set

    new_role = body.role if body.role is not None else target.role
    new_active = body.is_active if body.is_active is not None else target.is_active
    if "location_id" in fields:
        new_location = body.location_id
    elif new_role == Role.owner:
        new_location = None  # promoting to owner drops the location tie
    else:
        new_location = target.location_id

    if new_role == Role.owner:
        if new_location is not None:
            raise _invalid("location_id", "Owners are not tied to a single location")
    else:
        if new_location is None:
            raise _invalid("location_id", "A location is required for this role")
        if await LocationRepository(session, principal).get(new_location) is None:
            raise NotFoundError

    stops_being_active_owner = (
        target.role == Role.owner
        and target.is_active
        and (new_role != Role.owner or not new_active)
    )
    if stops_being_active_owner:
        # Safe to read without row locks: we hold the business lock (see lock_business).
        active_owner_ids = list(
            await session.scalars(
                select(User.id).where(
                    User.business_id == principal.business_id,
                    User.role == Role.owner,
                    User.is_active.is_(True),
                )
            )
        )
        if len(active_owner_ids) <= 1:
            raise LastOwnerError

    was_active = target.is_active
    target.role = new_role
    target.location_id = new_location
    target.is_active = new_active
    if was_active and not new_active:
        await revoke_all_sessions(session, target.id)
    await session.commit()
    return target


async def create_invite(
    session: AsyncSession, principal: Principal, body: InviteRequest
) -> tuple[Invite, str]:
    role = body.role
    location_id = body.location_id
    if principal.role == Role.manager:
        if role != Role.staff:
            raise ForbiddenError("Managers can only invite staff.")
        location_id = location_id or principal.location_id
    elif not principal.is_owner:
        raise ForbiddenError

    if role == Role.owner:
        if location_id is not None:
            raise _invalid("location_id", "Owners are not tied to a single location")
    else:
        if location_id is None:
            raise _invalid("location_id", "A location is required for this role")
        # Scoped lookup: another business's (or, for managers, another branch's) location is 404.
        if await LocationRepository(session, principal).get(location_id) is None:
            raise NotFoundError

    if (await session.scalar(select(User.id).where(User.email == body.email))) is not None:
        raise EmailTakenError

    now = datetime.now(UTC)
    # A fresh invitation supersedes any earlier pending one for the same address.
    await session.execute(
        update(Invite)
        .where(
            Invite.business_id == principal.business_id,
            Invite.email == body.email,
            Invite.accepted_at.is_(None),
            Invite.expires_at > now,
        )
        .values(expires_at=now)
    )
    raw_token = generate_opaque_token()
    invite = Invite(
        business_id=principal.business_id,
        location_id=location_id,
        email=body.email,
        role=role,
        token_hash=hash_opaque_token(raw_token),
        expires_at=now + timedelta(days=get_settings().invite_ttl_days),
        invited_by=principal.user_id,
    )
    session.add(invite)
    await session.commit()
    return invite, raw_token
