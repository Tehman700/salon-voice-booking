from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Only ever used when ENVIRONMENT is local or test. Long enough to satisfy HS256 key-length checks.
_DEV_JWT_SECRET = "dev-only-jwt-secret-do-not-use-in-deployed-environments"  # noqa: S105
_MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (and `.env` locally)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Salon Voice Booking API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/db
    database_url: str = "postgresql+asyncpg://salon:salon@127.0.0.1:5544/salon"
    database_echo: bool = False

    # Comma-separated in the environment: CORS_ORIGINS=http://localhost:3000,https://app.example.com
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # --- Auth ---
    # Required (>= 32 chars) in staging/production; local and test fall back to a dev secret.
    jwt_secret: SecretStr | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_days: int = 30
    invite_ttl_days: int = 7
    # Browsers reach the API through the Next.js proxy at /api/*, so the refresh cookie is scoped
    # to the path the browser sees. Direct API clients (tests, curl) use /auth/* and ignore it.
    refresh_cookie_path: str = "/api/auth"
    # None -> Secure cookie everywhere except local/test (plain http).
    cookie_secure: bool | None = None
    # None -> invite tokens are returned in API responses only in local/test, until M7 emails them.
    expose_invite_tokens: bool | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _resolve_jwt_secret(self) -> Self:
        if self.jwt_secret is None:
            if self.environment in ("staging", "production"):
                raise ValueError("JWT_SECRET is required in staging and production")
            self.jwt_secret = SecretStr(_DEV_JWT_SECRET)
        elif len(self.jwt_secret.get_secret_value()) < _MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {_MIN_JWT_SECRET_LENGTH} characters")
        return self

    @property
    def is_dev_like(self) -> bool:
        return self.environment in ("local", "test")

    @property
    def refresh_cookie_secure(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else not self.is_dev_like

    @property
    def invite_tokens_exposed(self) -> bool:
        if self.expose_invite_tokens is not None:
            return self.expose_invite_tokens
        return self.is_dev_like


@lru_cache
def get_settings() -> Settings:
    return Settings()
