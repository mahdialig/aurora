"""Gmail source — read the inbox and (on approval) draft/send replies.

A thin wrapper over the Gmail REST API. The single OAuth scope ``gmail.modify``
covers read, drafts, send, and label/archive — but not permanent delete.

Design notes:
- Google libraries are imported lazily (inside the functions that need them) so
  the pure helpers and dataclasses below stay importable and unit-testable
  without credentials or a network.
- :class:`GmailClient` takes an already-built ``service`` object, so tests can
  inject a fake. Use :meth:`GmailClient.from_config` for the real thing.
"""

from __future__ import annotations

import base64
from pathlib import Path

from aurora.sources.base import (
    EmailMessage,
    EmailSummary,
    MailAccount,
    Reply,
    build_raw,
    strip_html,
)

# OAuth scope: read + modify (archive/label) + drafts + send. No permanent delete.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_METADATA_HEADERS = ["From", "To", "Subject", "Date", "Message-ID", "References"]


class GmailAuthError(RuntimeError):
    """Raised when Gmail credentials are missing or no longer valid."""


# --------------------------------------------------------------------------- #
# Pure helpers (no network) — unit-tested directly
# --------------------------------------------------------------------------- #


def header(headers: list[dict], name: str) -> str:
    """Case-insensitive lookup in a Gmail payload ``headers`` list."""
    name_l = name.lower()
    for h in headers or []:
        if h.get("name", "").lower() == name_l:
            return h.get("value", "")
    return ""


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def extract_plaintext(payload: dict) -> str:
    """Walk a Gmail message payload and return the best plaintext body.

    Prefers ``text/plain``; falls back to a crude strip of ``text/html``.
    """
    plain = _find_part(payload, "text/plain")
    if plain:
        return plain
    html = _find_part(payload, "text/html")
    return strip_html(html) if html else ""


def _find_part(payload: dict, mime_type: str) -> str:
    if not payload:
        return ""
    if payload.get("mimeType") == mime_type:
        data = payload.get("body", {}).get("data")
        if data:
            return _b64url_decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        found = _find_part(part, mime_type)
        if found:
            return found
    return ""


def parse_summary(message: dict) -> EmailSummary:
    """Build an EmailSummary from a metadata-format messages.get response."""
    headers = message.get("payload", {}).get("headers", [])
    return EmailSummary(
        id=message.get("id", ""),
        thread_id=message.get("threadId", ""),
        sender=header(headers, "From"),
        subject=header(headers, "Subject"),
        date=header(headers, "Date"),
        snippet=message.get("snippet", ""),
        message_id=header(headers, "Message-ID"),
        references=header(headers, "References"),
    )


def parse_message(message: dict) -> EmailMessage:
    """Build a full EmailMessage (with decoded body) from a full messages.get response."""
    payload = message.get("payload", {})
    headers = payload.get("headers", [])
    return EmailMessage(
        id=message.get("id", ""),
        thread_id=message.get("threadId", ""),
        sender=header(headers, "From"),
        to=header(headers, "To"),
        subject=header(headers, "Subject"),
        date=header(headers, "Date"),
        snippet=message.get("snippet", ""),
        body=extract_plaintext(payload),
        message_id=header(headers, "Message-ID"),
        references=header(headers, "References"),
    )


# --------------------------------------------------------------------------- #
# Credentials (lazy google imports)
# --------------------------------------------------------------------------- #


def load_credentials(credentials_file: Path, token_file: Path):
    """Load saved OAuth credentials, refreshing if needed.

    Raises :class:`GmailAuthError` (with a fix hint) if there's no usable token.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not token_file.exists():
        raise GmailAuthError(
            f"No Gmail token at {token_file}. Run: python -m aurora.sources.gmail_auth"
        )

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        # A refresh can still fail if the refresh token itself expired or was
        # revoked (e.g. a "Testing"-mode OAuth app caps it at ~7 days). Convert
        # Google's RefreshError into our GmailAuthError so callers treat it as
        # "needs re-auth" (skip the account, alert) rather than crashing.
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise GmailAuthError(
                "Gmail login expired and couldn't refresh. "
                "Re-run: python -m aurora.sources.gmail_auth"
            ) from exc
        token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds
    raise GmailAuthError(
        "Gmail login has expired. Re-run: python -m aurora.sources.gmail_auth"
    )


def build_service(credentials_file: Path, token_file: Path):
    """Build an authenticated Gmail API service object."""
    from googleapiclient.discovery import build

    creds = load_credentials(credentials_file, token_file)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


class GmailClient(MailAccount):
    """Read the inbox and draft/send replies. Wraps a Gmail API ``service``."""

    def __init__(self, service, label: str = "personal", address: str = "") -> None:
        self._svc = service
        self.label = label
        self.address = address

    @classmethod
    def from_config(cls, config, label: str = "personal") -> "GmailClient":
        service = build_service(config.google_credentials_file, config.google_token_file)
        return cls(service, label=label)

    def _summaries(self, message_refs: list[dict]) -> list[EmailSummary]:
        out: list[EmailSummary] = []
        for ref in message_refs or []:
            msg = (
                self._svc.users()
                .messages()
                .get(
                    userId="me",
                    id=ref["id"],
                    format="metadata",
                    metadataHeaders=_METADATA_HEADERS,
                )
                .execute()
            )
            out.append(parse_summary(msg))
        return out

    def list_unread(self, max_results: int = 20) -> list[EmailSummary]:
        """Recent unread INBOX messages, newest first."""
        resp = (
            self._svc.users()
            .messages()
            .list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results)
            .execute()
        )
        return self._summaries(resp.get("messages", []))

    def search(self, query: str, max_results: int = 20) -> list[EmailSummary]:
        """Search the mailbox using Gmail's query syntax (e.g. 'from:boss newer_than:7d').

        Includes Spam and Trash — when the user is hunting for a specific message,
        "did I get it?" should cover the places things hide.
        """
        resp = (
            self._svc.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results, includeSpamTrash=True)
            .execute()
        )
        return self._summaries(resp.get("messages", []))

    def get_message(self, msg_id: str) -> EmailMessage:
        msg = (
            self._svc.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        return parse_message(msg)

    def create_draft(self, reply: Reply) -> str:
        """Save ``reply`` as a draft. Threaded if ``thread_id`` is set, else a new draft."""
        message: dict = {"raw": build_raw(reply)}
        if reply.thread_id:  # omit for a fresh (non-reply) email — Gmail rejects an empty threadId
            message["threadId"] = reply.thread_id
        resp = self._svc.users().drafts().create(userId="me", body={"message": message}).execute()
        return resp.get("id", "")

    def send_reply(self, reply: Reply) -> str:
        """Send ``reply`` (real email!). Threaded if ``thread_id`` is set, else a new message."""
        body: dict = {"raw": build_raw(reply)}
        if reply.thread_id:  # omit for a fresh (non-reply) email
            body["threadId"] = reply.thread_id
        resp = self._svc.users().messages().send(userId="me", body=body).execute()
        return resp.get("id", "")

    def archive(self, msg_id: str) -> None:
        """Remove the message from the inbox (Gmail 'archive')."""
        self._svc.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()
