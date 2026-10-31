"""Request-scoped dependencies: database session, caller identity, role checks."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotAuthenticatedError
from app.core.principal import Principal
from app.core.security import TokenExpiredError, TokenInvalidError, decode_access_token
from app.db.session import get_session
from app.models.user import Role, User
from app.services.auth import ClientMeta

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login or /auth/signup")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: SessionDep,
) -> User:
    """Any authenticated, active user (including platform admins)."""
    if credentials is None:
        raise NotAuthenticatedError
    try:
        claims = decode_access_token(credentials.credentials)
    except TokenExpiredError:
        raise NotAuthenticatedError("Your session has expired.", code="token_expired") from None
    except TokenInvalidError:
        raise NotAuthenticatedError from None
    # The database, not the token, decides: a deactivated or re-roled user is affected at once.
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise NotAuthenticatedError
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_principal(user: CurrentUser) -> Principal:
    """An authenticated user acting inside one business. Platform admins have none."""
    if user.business_id is None:
        raise ForbiddenError("This endpoint is for business users.")
    return Principal(
        user_id=user.id, business_id=user.business_id, role=user.role, location_id=user.location_id
    )


def require_roles(*roles: Role) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if principal.role not in roles:
            raise ForbiddenError
        return principal

    return dependency


AnyPrincipal = Annotated[Principal, Depends(get_principal)]
OwnerPrincipal = Annotated[Principal, Depends(require_roles(Role.owner))]
ManagerPrincipal = Annotated[Principal, Depends(require_roles(Role.owner, Role.manager))]


def get_client_meta(request: Request) -> ClientMeta:
    return ClientMeta(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


ClientMetaDep = Annotated[ClientMeta, Depends(get_client_meta)]
