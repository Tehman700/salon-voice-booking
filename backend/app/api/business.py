from fastapi import APIRouter

from app.api.deps import AnyPrincipal, OwnerPrincipal, SessionDep
from app.core.errors import error_responses
from app.schemas.business import BusinessOut, BusinessUpdate
from app.services import tenancy

router = APIRouter(prefix="/business", tags=["business"], responses=error_responses(401, 403))


@router.get("", summary="The current business")
async def get_business(principal: AnyPrincipal, session: SessionDep) -> BusinessOut:
    return BusinessOut.model_validate(await tenancy.get_business(session, principal))


@router.patch(
    "",
    summary="Update the business (owner)",
    responses=error_responses(422),
)
async def update_business(
    body: BusinessUpdate, principal: OwnerPrincipal, session: SessionDep
) -> BusinessOut:
    return BusinessOut.model_validate(await tenancy.update_business(session, principal, body))
