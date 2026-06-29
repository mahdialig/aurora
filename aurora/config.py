"""Central configuration and secrets loading.

Everything secret or environment-specific lives here and is read from the
environment (a local ``.env`` during development, real env vars on the VPS).
Nothing is hardcoded. Importing modules ask for a :class:`Config` rather than
reading ``os.environ`` directly, so there is a single, testable surface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional during dev; load_dotenv is a no-op if the package is absent
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a convenience, not required
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False


# Project root = the directory containing this package's parent (the repo root).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Autonomy presets recognised across Aurora. Defined here so the surface, the
# policy engine, and config validation all agree on the allowed values.
AUTONOMY_MODES = ("approve_all", "digest", "auto_low_risk", "autonomous")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration.

    Construct via :meth:`load`, which reads the environment and validates it.
    """

    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    telegram_bot_token: str
    allowed_user_id: int
    autonomy_mode: str
    data_dir: Path

    @classmethod
    def load(cls, *, require_telegram: bool = True) -> "Config":
        """Read and validate configuration from the environment.

        Loads a ``.env`` file if present (development convenience), then pulls
        the required values. Raises :class:`ConfigError` with an actionable
        message when something needed is missing.

        ``require_telegram`` lets non-bot entrypoints (jobs, tests) load the
        config without a bot token present.
        """
        load_dotenv(PROJECT_ROOT / ".env")

        deepseek_api_key = _require("DEEPSEEK_API_KEY")
        deepseek_base_url = os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).rstrip("/")
        deepseek_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        telegram_bot_token = (
            _require("TELEGRAM_BOT_TOKEN") if require_telegram else os.environ.get("TELEGRAM_BOT_TOKEN", "")
        )
        allowed_user_id = _require_int("AURORA_ALLOWED_USER_ID") if require_telegram else 0

        autonomy_mode = os.environ.get("AURORA_AUTONOMY_MODE", "approve_all")
        if autonomy_mode not in AUTONOMY_MODES:
            raise ConfigError(
                f"AURORA_AUTONOMY_MODE={autonomy_mode!r} is invalid; "
                f"expected one of {', '.join(AUTONOMY_MODES)}."
            )

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        return cls(
            deepseek_api_key=deepseek_api_key,
            deepseek_base_url=deepseek_base_url,
            deepseek_model=deepseek_model,
            telegram_bot_token=telegram_bot_token,
            allowed_user_id=allowed_user_id,
            autonomy_mode=autonomy_mode,
            data_dir=DATA_DIR,
        )


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and fill it in (see README)."
        )
    return value


def _require_int(name: str) -> int:
    raw = _require(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer (got {raw!r}).") from exc
