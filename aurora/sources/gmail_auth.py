"""One-time Gmail OAuth — run on a machine with a browser.

    python -m aurora.sources.gmail_auth

Opens a browser for consent using ``credentials.json`` and writes the resulting
token to ``data/token.json`` (auto-refreshed thereafter). Re-run anytime the
login expires. Both files are gitignored.
"""

from __future__ import annotations

from aurora.config import Config
from aurora.sources.gmail import SCOPES


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    config = Config.load(require_telegram=False)

    if not config.google_credentials_file.exists():
        raise SystemExit(
            f"Missing {config.google_credentials_file}. Download an OAuth 'Desktop app' "
            "client from Google Cloud Console and save it there (see the M1 setup steps)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.google_credentials_file), SCOPES
    )
    creds = flow.run_local_server(port=0)

    config.google_token_file.parent.mkdir(parents=True, exist_ok=True)
    config.google_token_file.write_text(creds.to_json(), encoding="utf-8")
    print(f"[OK] Gmail authorized. Token saved to {config.google_token_file}")


if __name__ == "__main__":
    main()
