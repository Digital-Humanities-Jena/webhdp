from app.config import Settings


def test_settings_accepts_comma_separated_cors_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8080, http://127.0.0.1:5173")

    settings = Settings()

    assert settings.cors_origins == ["http://localhost:8080", "http://127.0.0.1:5173"]


def test_settings_accepts_json_list_cors_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:8080", "http://127.0.0.1:5173"]')

    settings = Settings()

    assert settings.cors_origins == ["http://localhost:8080", "http://127.0.0.1:5173"]
