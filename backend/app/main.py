import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, bookings, business, calls, catalog, health, locations, retell, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.db.session import get_sessionmaker
from app.services import notifications


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the email sender next to the API when a sender address is configured."""
    sender = notifications.configured_sender()
    if sender is None:
        yield
        return
    stop = asyncio.Event()
    task = asyncio.create_task(
        notifications.run_sender(
            get_sessionmaker(), sender, stop, interval=get_settings().email_poll_seconds
        )
    )
    try:
        yield
    finally:
        stop.set()
        await task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Booking backend for the salon voice platform. Errors always use "
        '`{"error": {"code", "message", "details"}}`.',
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(business.router)
    app.include_router(locations.router)
    app.include_router(users.router)
    app.include_router(catalog.services_router)
    app.include_router(catalog.staff_router)
    app.include_router(catalog.schedule_router)
    app.include_router(catalog.availability_router)
    app.include_router(bookings.bookings_router)
    app.include_router(bookings.customers_router)
    app.include_router(calls.router)
    app.include_router(retell.functions_router)
    app.include_router(retell.webhooks_router)
    return app


app = create_app()
