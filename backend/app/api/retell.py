"""Endpoints Retell calls: the agent's tools and its call events. Not for browsers or the dashboard.

Both are authenticated by Retell's request signature, not by a user token.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from app.api.deps import SessionDep
from app.core.errors import ValidationFailedError, error_responses
from app.core.retell import verify_retell_request
from app.services import call_events, voice

BodyDep = Annotated[bytes, Depends(verify_retell_request)]

functions_router = APIRouter(
    prefix="/retell/functions",
    tags=["voice"],
    responses=error_responses(401, 422) | {503: {"description": "Voice not configured"}},
)
webhooks_router = APIRouter(prefix="/webhooks", tags=["voice"], responses=error_responses(401, 422))


@functions_router.post(
    "/{tool_name}",
    summary="Run one of the voice agent's tools",
    description=(
        "Called by Retell with `{name, args, call}`. Always answers 200 with "
        "`{success, message, ...}`: `success` is true only if the backend really did it."
    ),
)
async def run_function(tool_name: str, body: BodyDep, session: SessionDep) -> dict[str, Any]:
    try:
        request = voice.FunctionRequest.model_validate_json(body)
    except ValidationError as error:
        raise ValidationFailedError(details={"body": [str(error.errors()[0]["msg"])]}) from None
    return await voice.run_tool(session, tool_name, request)


@webhooks_router.post("/retell", summary="Retell call events (started, ended, analysed)")
async def retell_webhook(body: BodyDep, session: SessionDep) -> dict[str, str]:
    try:
        event = call_events.WebhookEvent.model_validate_json(body)
    except ValidationError as error:
        raise ValidationFailedError(details={"body": [str(error.errors()[0]["msg"])]}) from None
    return {"status": await call_events.apply_event(session, event)}
