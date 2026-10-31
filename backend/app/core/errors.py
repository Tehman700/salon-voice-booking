"""One error shape for the whole API, as agreed in docs/api-contract.md.

{"error": {"code": "slot_unavailable", "message": "...", "details": {...}}}
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Base class for errors that map to a specific HTTP response."""

    status_code = 500
    code = "internal_error"
    message = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Authentication is required."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to do that."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "That conflicts with the current state."


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The request is not valid."


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries for the standard error shape."""
    descriptions = {
        400: "Bad request",
        401: "Missing, invalid or expired credentials",
        403: "Authenticated but not allowed",
        404: "Not found, or belongs to another business",
        409: "Conflict with current state",
        422: "Validation error",
    }
    return {s: {"model": ErrorResponse, "description": descriptions[s]} for s in statuses}


def _error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields: dict[str, list[str]] = {}
    for error in exc.errors():
        # loc is ("body" | "query" | "path", field, ...): drop the source, keep the field path.
        path = ".".join(str(part) for part in error["loc"][1:]) or "request"
        fields.setdefault(path, []).append(str(error["msg"]))
    return _error_response(
        422, "validation_error", "The request is not valid.", jsonable_encoder(fields)
    )


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    codes = {
        401: "not_authenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
    }
    code = codes.get(exc.status_code, "http_error")
    return _error_response(exc.status_code, code, str(exc.detail))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
