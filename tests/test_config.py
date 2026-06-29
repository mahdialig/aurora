import pytest

from aurora.config import Config, ConfigError


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # Start every test from a known-empty environment.
    for key in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "TELEGRAM_BOT_TOKEN",
        "AURORA_ALLOWED_USER_ID",
        "AURORA_AUTONOMY_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    # Avoid reading a developer's real .env during tests.
    monkeypatch.setattr("aurora.config.load_dotenv", lambda *a, **k: False)


def test_missing_api_key_raises(monkeypatch):
    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        Config.load(require_telegram=False)


def test_loads_minimal_without_telegram(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    config = Config.load(require_telegram=False)
    assert config.deepseek_api_key == "sk-test"
    assert config.deepseek_model == "deepseek-chat"
    assert config.autonomy_mode == "approve_all"


def test_invalid_autonomy_mode_raises(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("AURORA_AUTONOMY_MODE", "yolo")
    with pytest.raises(ConfigError, match="AURORA_AUTONOMY_MODE"):
        Config.load(require_telegram=False)


def test_non_integer_user_id_raises(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("AURORA_ALLOWED_USER_ID", "not-a-number")
    with pytest.raises(ConfigError, match="must be an integer"):
        Config.load(require_telegram=True)
