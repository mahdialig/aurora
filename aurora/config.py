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
    google_credentials_file: Path
    google_token_file: Path
    # Work mailbox (IMAP/SMTP). All optional — blank WORK_EMAIL/PASSWORD = skip.
    work_email: str
    work_password: str
    work_imap_host: str
    work_imap_port: int
    work_smtp_host: str
    work_smtp_port: int
    # Proactive notifications (M3).
    notify_enabled: bool
    notify_interval_seconds: int
    # Don't-miss-a-thing engine (M4): timezone + scheduled brief / weekly review.
    timezone: str
    brief_enabled: bool
    brief_time: str
    brief_horizon_days: int
    weekly_review_enabled: bool
    weekly_review_day: int
    weekly_review_time: str
    weekly_horizon_days: int

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
        deepseek_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

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

        # Gmail (M1). Paths only — presence is checked when Gmail is actually used,
        # so the bot still loads fine before Google credentials exist.
        google_credentials_file = Path(
            os.environ.get("GOOGLE_CREDENTIALS_FILE", str(PROJECT_ROOT / "credentials.json"))
        )
        google_token_file = Path(
            os.environ.get("GOOGLE_TOKEN_FILE", str(DATA_DIR / "token.json"))
        )

        # Work mailbox (M2). Optional — host/ports default to dapurhosting cPanel.
        work_email = os.environ.get("WORK_EMAIL", "").strip()
        work_password = os.environ.get("WORK_PASSWORD", "")
        work_imap_host = os.environ.get("WORK_IMAP_HOST", "d001.dapurhosting.com").strip()
        work_imap_port = _int_env("WORK_IMAP_PORT", 993)
        work_smtp_host = os.environ.get("WORK_SMTP_HOST", "d001.dapurhosting.com").strip()
        work_smtp_port = _int_env("WORK_SMTP_PORT", 465)

        # Proactive notifications (M3). On by default; checks every 10 min.
        notify_enabled = _bool_env("AURORA_NOTIFY_ENABLED", True)
        notify_interval_seconds = _int_env("AURORA_NOTIFY_INTERVAL_SECONDS", 600)

        # Don't-miss-a-thing engine (M4). All optional, sensible defaults (Jakarta).
        timezone = os.environ.get("AURORA_TIMEZONE", "Asia/Jakarta").strip() or "Asia/Jakarta"
        brief_enabled = _bool_env("AURORA_BRIEF_ENABLED", True)
        brief_time = os.environ.get("AURORA_BRIEF_TIME", "07:00").strip() or "07:00"
        brief_horizon_days = _int_env("AURORA_BRIEF_HORIZON_DAYS", 7)
        weekly_review_enabled = _bool_env("AURORA_WEEKLY_REVIEW_ENABLED", True)
        weekly_review_day = _int_env("AURORA_WEEKLY_REVIEW_DAY", 0)  # 0=Monday
        weekly_review_time = os.environ.get("AURORA_WEEKLY_REVIEW_TIME", "07:30").strip() or "07:30"
        weekly_horizon_days = _int_env("AURORA_WEEKLY_HORIZON_DAYS", 14)
        if not 0 <= weekly_review_day <= 6:
            raise ConfigError("AURORA_WEEKLY_REVIEW_DAY must be 0 (Mon) through 6 (Sun).")

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        return cls(
            deepseek_api_key=deepseek_api_key,
            deepseek_base_url=deepseek_base_url,
            deepseek_model=deepseek_model,
            telegram_bot_token=telegram_bot_token,
            allowed_user_id=allowed_user_id,
            autonomy_mode=autonomy_mode,
            data_dir=DATA_DIR,
            google_credentials_file=google_credentials_file,
            google_token_file=google_token_file,
            work_email=work_email,
            work_password=work_password,
            work_imap_host=work_imap_host,
            work_imap_port=work_imap_port,
            work_smtp_host=work_smtp_host,
            work_smtp_port=work_smtp_port,
            notify_enabled=notify_enabled,
            notify_interval_seconds=notify_interval_seconds,
            timezone=timezone,
            brief_enabled=brief_enabled,
            brief_time=brief_time,
            brief_horizon_days=brief_horizon_days,
            weekly_review_enabled=weekly_review_enabled,
            weekly_review_day=weekly_review_day,
            weekly_review_time=weekly_review_time,
            weekly_horizon_days=weekly_horizon_days,
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


def _int_env(name: str, default: int) -> int:
    """Read an optional integer env var, falling back to ``default`` if unset/blank."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer (got {raw!r}).") from exc


def _bool_env(name: str, default: bool) -> bool:
    """Read an optional boolean env var ('1'/'true'/'yes'/'on' = True)."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")
