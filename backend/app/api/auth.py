from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.api.deps import ClientMetaDep, CurrentUser, SessionDep
from app.core.config import get_settings
from app.core.errors import error_responses
from app.schemas.auth import AcceptInviteRequest, AuthResponse, LoginRequest, Me, SignupRequest
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )


async def _respond(
    session: SessionDep, issued: auth_service.IssuedSession, response: Response
) -> AuthResponse:
    _set_refresh_cookie(response, issued.refresh_token)
    return AuthResponse(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        user=await auth_service.build_me(session, issued.user),
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    summary="Create a business, its location(s) and the owner account",
    responses=error_responses(409, 422),
)
async def signup(
    body: SignupRequest, response: Response, session: SessionDep, meta: ClientMetaDep
) -> AuthResponse:
    return await _respond(session, await auth_service.signup(session, body, meta), response)


@router.post(
    "/login",
    summary="Sign in with email and password",
    responses=error_responses(401, 422),
)
async def login(
    body: LoginRequest, response: Response, session: SessionDep, meta: ClientMetaDep
) -> AuthResponse:
    return await _respond(session, await auth_service.login(session, body, meta), response)


@router.post(
    "/refresh",
    summary="Exchange the refresh cookie for a new access token (rotates the cookie)",
    responses=error_responses(401),
)
async def refresh(
    response: Response,
    session: SessionDep,
    meta: ClientMetaDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> AuthResponse:
    issued = await auth_service.refresh(session, refresh_token, meta)
    return await _respond(session, issued, response)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End this session and clear the refresh cookie",
)
async def logout(
    response: Response,
    session: SessionDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    await auth_service.logout(session, refresh_token)
    _clear_refresh_cookie(response)


@router.get("/me", summary="The signed-in user", responses=error_responses(401))
async def me(user: CurrentUser, session: SessionDep) -> Me:
    return await auth_service.build_me(session, user)


@router.post(
    "/accept-invite",
    summary="Create an account from an invitation and sign in",
    responses=error_responses(400, 409, 422),
)
async def accept_invite(
    body: AcceptInviteRequest, response: Response, session: SessionDep, meta: ClientMetaDep
) -> AuthResponse:
    return await _respond(session, await auth_service.accept_invite(session, body, meta), response)
