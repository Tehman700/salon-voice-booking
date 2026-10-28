import pytest

from app.core.config import Settings


def test_cors_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://app.example.com ,")
    assert Settings().cors_origins == ["http://localhost:3000", "https://app.example.com"]


def test_rejects_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod-ish")
    with pytest.raises(ValueError):
        Settings()
