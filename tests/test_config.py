from app.config import get_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.base_url == "http://localhost:8000"
    assert settings.db_path == "dev-links.db"
    get_settings.cache_clear()


def test_env_override_and_trailing_slash(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://s.example.com/")
    monkeypatch.setenv("DB_PATH", "/tmp/links.db")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.base_url == "https://s.example.com"
    assert settings.db_path == "/tmp/links.db"
    get_settings.cache_clear()
