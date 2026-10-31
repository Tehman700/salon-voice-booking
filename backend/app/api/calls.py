"""The call log, for the dashboard (owners and managers)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ManagerPrincipal, SessionDep
from app.core.errors import error_responses
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.models.call import CallOutcome
from app.schemas.call import CallOut, CallStats
from app.schemas.common import Page
from app.services import calls as calls_service

router = APIRouter(prefix="/calls", tags=["calls"], responses=error_responses(401, 403, 404))


@router.get("", summary="Phone calls, newest first (owner: all; manager: their location)")
async def list_calls(
    principal: ManagerPrincipal,
    session: SessionDep,
    location_id: uuid.UUID | None = None,
    outcome: CallOutcome | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> Page[CallOut]:
    items, next_cursor = await calls_service.list_calls(
        session,
        principal,
        location_id=location_id,
        outcome=outcome,
        from_=from_,
        to=to,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=items, next_cursor=next_cursor)


# Declared before /{call_id} so "stats" is not read as an id.
@router.get("/stats", summary="Call counts by outcome and by day")
async def call_stats(
    principal: ManagerPrincipal,
    session: SessionDep,
    location_id: uuid.UUID | None = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> CallStats:
    return await calls_service.call_stats(
        session, principal, location_id=location_id, from_=from_, to=to
    )


@router.get("/{call_id}", summary="One call, with its transcript")
async def get_call(call_id: uuid.UUID, principal: ManagerPrincipal, session: SessionDep) -> CallOut:
    return await calls_service.get_call(session, principal, call_id)
