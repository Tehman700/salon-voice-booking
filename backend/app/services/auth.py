"""Sign-up, login, refresh-token rotation, logout and invite acceptance.

Write operations commit themselves: callers get back either a fully persisted result or an error
with nothing half-written.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, NotAuthenticatedError
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.core.slug import randomized_slug, slugify, unique_slug
from app.models.business import Business
from app.models.invite import Invite
from app.models.location import Location
from app.models.refresh_token import RefreshToken
from app.models.user import Role, User
from app.schemas.auth import AcceptInviteRequest, LoginRequest, Me, MeBusiness, SignupRequest

logger = logging.getLogger(__name__)

_MAX_SIGNUP_ATTEMPTS = 5


class EmailTakenError(ConflictError):
    code = "email_taken"
    message = "An account with that email already exists."


class InvalidCredentialsError(NotAuthenticatedError):
    code = "invalid_credentials"
    message = "Invalid email or password."


class InvalidInviteError(AppError):
    status_code = 400
    code = "invalid_invite"
    message = "This invitation is invalid or has expired."


@dataclass(frozen=True)
class ClientMeta:
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class IssuedSession:
    user: User
    access_token: str
    refresh_token: str  # raw value, to be set as a cookie; only its hash is stored
    expires_in: int
    refresh_record: RefreshToken


def _now() -> datetime:
    return datetime.now(UTC)


async def _issue_session(
    session: AsyncSession, user: User, meta: ClientMeta, *, family_id: uuid.UUID | None = None
) -> IssuedSession:
    settings = get_settings()
    raw = generate_opaque_token()
    record = RefreshToken(
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_opaque_token(raw),
        expires_at=_now() + timedelta(days=settings.refresh_token_ttl_days),
        user_agent=(meta.user_agent or "")[:255] or None,
        ip_address=meta.ip_address,
    )
    session.add(record)
    await session.flush()
    return IssuedSession(
        user=user,
        access_token=create_access_token(user.id, user.business_id, user.role.value),
        refresh_token=raw,
        expires_in=settings.access_token_ttl_seconds,
        refresh_record=record,
    )


async def _email_exists(session: AsyncSession, email: str) -> bool:
    return (await session.scalar(select(User.id).where(User.email == email))) is not None


async def build_me(session: AsyncSession, user: User) -> Me:
    business: MeBusiness | None = None
    location_ids: list[uuid.UUID] = []
    if user.business_id is not None:
        found = await session.get(Business, user.business_id)
        if found is not None:
            business = MeBusiness(id=found.id, name=found.name, location_mode=found.location_mode)
        if user.role == Role.owner:
            location_ids = list(
                await session.scalars(
                    select(Location.id)
                    .where(Location.business_id == user.business_id)
                    .order_by(Location.created_at, Location.name)
                )
            )
        elif user.location_id is not None:
            location_ids = [user.location_id]
    return Me(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        business=business,
        location_ids=location_ids,
    )


# --- Sign-up ---


async def signup(session: AsyncSession, request: SignupRequest, meta: ClientMeta) -> IssuedSession:
    if await _email_exists(session, request.email):
        raise EmailTakenError
    password_hash = hash_password(request.password)

    for attempt in range(_MAX_SIGNUP_ATTEMPTS):
        try:
            business_slug = await _free_business_slug(
                session, request.business_name, retry=attempt > 0
            )
            business = Business(
                name=request.business_name,
                slug=business_slug,
                location_mode=request.location_mode,
                default_timezone=request.locations[0].timezone,
            )
            session.add(business)
            await session.flush()

            taken: set[str] = set()
            for item in request.locations:
                slug = unique_slug(slugify(item.name), taken)
                taken.add(slug)
                session.add(Location(business_id=business.id, slug=slug, **item.model_dump()))

            owner = User(
                business_id=business.id,
                email=request.email,
                password_hash=password_hash,
                full_name=request.owner_full_name,
                role=Role.owner,
                last_login_at=_now(),
            )
            session.add(owner)
            await session.flush()
            issued = await _issue_session(session, owner, meta)
            await session.commit()
            return issued
        except IntegrityError:
            # Either someone registered this email between our check and the insert, or the
            # business slug was taken concurrently. Tell them apart, then retry the latter.
            await session.rollback()
            if await _email_exists(session, request.email):
                raise EmailTakenError from None
    raise ConflictError("Could not create the account; please try again.", code="signup_conflict")


async def _free_business_slug(session: AsyncSession, name: str, *, retry: bool) -> str:
    base = slugify(name)
    if retry:  # we lost a race on the previous slug; sequential numbers would collide again
        return randomized_slug(base)
    existing = set(
        await session.scalars(select(Business.slug).where(Business.slug.like(f"{base}%")))
    )
    return unique_slug(base, existing)


# --- Login / refresh / logout ---


async def login(session: AsyncSession, request: LoginRequest, meta: ClientMeta) -> IssuedSession:
    user = await session.scalar(select(User).where(User.email == request.email))
    if user is None:
        verify_dummy_password(request.password)
        raise InvalidCredentialsError
    valid, upgraded_hash = verify_password(request.password, user.password_hash)
    # Inactive users get the same answer as a wrong password: no account enumeration.
    if not valid or not user.is_active:
        raise InvalidCredentialsError
    if upgraded_hash:
        user.password_hash = upgraded_hash
    user.last_login_at = _now()
    issued = await _issue_session(session, user, meta)
    await session.commit()
    return issued


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Sign a user out everywhere (used when an account is deactivated)."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def refresh(session: AsyncSession, raw_token: str | None, meta: ClientMeta) -> IssuedSession:
    if not raw_token:
        raise NotAuthenticatedError
    now = _now()
    # Row lock: two concurrent refreshes with the same token are serialised, so the second one
    # sees it already rotated (and is treated as reuse) instead of both succeeding.
    record = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_opaque_token(raw_token))
        .with_for_update()
    )
    if record is None:
        raise NotAuthenticatedError

    if record.revoked_at is not None:
        # A rotated or revoked token came back: assume it was stolen and end the whole session.
        logger.warning("refresh token reuse detected; revoking family %s", record.family_id)
        await _revoke_family(session, record.family_id, now)
        await session.commit()
        raise NotAuthenticatedError("Your session has ended. Please sign in again.")
    if record.expires_at <= now:
        raise NotAuthenticatedError("Your session has expired.", code="token_expired")

    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        await _revoke_family(session, record.family_id, now)
        await session.commit()
        raise NotAuthenticatedError

    issued = await _issue_session(session, user, meta, family_id=record.family_id)
    record.revoked_at = now
    record.replaced_by_id = issued.refresh_record.id
    await session.commit()
    return issued


async def logout(session: AsyncSession, raw_token: str | None) -> None:
    """Revoke the session this refresh token belongs to. Always succeeds (idempotent)."""
    if not raw_token:
        return
    record = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_opaque_token(raw_token))
    )
    if record is not None:
        await _revoke_family(session, record.family_id, _now())
        await session.commit()


# --- Invites ---


async def accept_invite(
    session: AsyncSession, request: AcceptInviteRequest, meta: ClientMeta
) -> IssuedSession:
    now = _now()
    invite = await session.scalar(
        select(Invite)
        .where(Invite.token_hash == hash_opaque_token(request.token))
        .with_for_update()
    )
    if invite is None or invite.accepted_at is not None or invite.expires_at <= now:
        raise InvalidInviteError
    if await _email_exists(session, invite.email):
        raise EmailTakenError

    user = User(
        business_id=invite.business_id,
        location_id=invite.location_id,
        email=invite.email,
        password_hash=hash_password(request.password),
        full_name=request.full_name,
        role=invite.role,
        last_login_at=now,
    )
    session.add(user)
    invite.accepted_at = now
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise EmailTakenError from None
    issued = await _issue_session(session, user, meta)
    await session.commit()
    return issued
