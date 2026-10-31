from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, business, health, locations, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Booking backend for the salon voice platform. Errors always use "
        '`{"error": {"code", "message", "details"}}`.',
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
    return app


app = create_app()
