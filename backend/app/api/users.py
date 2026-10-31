import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import ManagerPrincipal, OwnerPrincipal, SessionDep
from app.core.config import get_settings
from app.core.errors import error_responses
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.schemas.common import Page
from app.schemas.user import InviteOut, InviteRequest, UserOut, UserUpdate
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"], responses=error_responses(401, 403))


@router.get(
    "",
    summary="Team members (owner: whole business; manager: their location)",
    responses=error_responses(422),
)
async def list_users(
    principal: ManagerPrincipal,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> Page[UserOut]:
    users, next_cursor = await users_service.list_users(
        session, principal, limit=limit, cursor=cursor
    )
    return Page(items=[UserOut.model_validate(u) for u in users], next_cursor=next_cursor)


@router.post(
    "/invite",
    status_code=status.HTTP_201_CREATED,
    summary="Invite a team member",
    description="Owners can invite any role; managers can invite staff to their own location. "
    "The invitation token is returned only while emails aren't wired up (local/test).",
    responses=error_responses(404, 409, 422),
)
async def invite_user(
    body: InviteRequest, principal: ManagerPrincipal, session: SessionDep
) -> InviteOut:
    invite, raw_token = await users_service.create_invite(session, principal, body)
    return InviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        location_id=invite.location_id,
        expires_at=invite.expires_at,
        token=raw_token if get_settings().invite_tokens_exposed else None,
    )


@router.patch(
    "/{user_id}",
    summary="Change a team member's role, location or active state (owner)",
    responses=error_responses(404, 409, 422),
)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, principal: OwnerPrincipal, session: SessionDep
) -> UserOut:
    return UserOut.model_validate(
        await users_service.update_user(session, principal, user_id, body)
    )
