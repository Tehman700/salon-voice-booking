from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: str
    database: str | None = None


@router.get("/health")
async def liveness() -> HealthStatus:
    """Process is up. Used by the load balancer; never touches the database."""
    return HealthStatus(status="ok")


@router.get("/health/ready")
async def readiness(
    response: Response, session: Annotated[AsyncSession, Depends(get_session)]
) -> HealthStatus:
    """Process can serve traffic: the database is reachable."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable", database="unreachable")
    return HealthStatus(status="ok", database="ok")
