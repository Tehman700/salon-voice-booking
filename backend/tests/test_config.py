import pytest

from app.core.config import Settings


def test_cors_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://app.example.com ,")
    assert Settings().cors_origins == ["http://localhost:3000", "https://app.example.com"]


def test_rejects_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod-ish")
    with pytest.raises(ValueError):
        Settings()


# --- Auth settings ---


def test_jwt_secret_is_required_in_staging_and_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    for environment in ("staging", "production"):
        monkeypatch.setenv("ENVIRONMENT", environment)
        with pytest.raises(ValueError, match="JWT_SECRET is required"):
            Settings(_env_file=None)


def test_short_jwt_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "too-short")
    with pytest.raises(ValueError, match="at least 32"):
        Settings(_env_file=None)


def test_local_and_test_fall_back_to_a_dev_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    for environment in ("local", "test"):
        monkeypatch.setenv("ENVIRONMENT", environment)
        settings = Settings(_env_file=None)
        assert settings.jwt_secret is not None
        assert len(settings.jwt_secret.get_secret_value()) >= 32


def test_a_configured_secret_is_used_and_never_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "s3cret-" + "x" * 40
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", secret)
    settings = Settings(_env_file=None)
    assert settings.jwt_secret is not None
    assert settings.jwt_secret.get_secret_value() == secret
    assert secret not in repr(settings)


def test_cookie_and_invite_defaults_depend_on_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.delenv("EXPOSE_INVITE_TOKENS", raising=False)
    expectations = {
        "local": (False, True),
        "test": (False, True),
        "staging": (True, False),
        "production": (True, False),
    }
    for environment, (secure, exposed) in expectations.items():
        monkeypatch.setenv("ENVIRONMENT", environment)
        settings = Settings(_env_file=None)
        assert settings.refresh_cookie_secure is secure, environment
        assert settings.invite_tokens_exposed is exposed, environment


def test_cookie_and_invite_defaults_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("EXPOSE_INVITE_TOKENS", "true")
    settings = Settings(_env_file=None)
    assert settings.refresh_cookie_secure is False
    assert settings.invite_tokens_exposed is True


def test_auth_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ACCESS_TOKEN_TTL_SECONDS", "REFRESH_TOKEN_TTL_DAYS", "REFRESH_COOKIE_PATH"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.access_token_ttl_seconds == 15 * 60
    assert settings.refresh_token_ttl_days == 30
    # The browser reaches the API through the Next.js proxy, so the cookie is scoped to /api/auth.
    assert settings.refresh_cookie_path == "/api/auth"
