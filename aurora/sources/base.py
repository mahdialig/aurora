"""Shared mail types and the provider-agnostic MailAccount interface.

Both the Gmail (API) and IMAP/SMTP connectors implement :class:`MailAccount` and
exchange the same dataclasses, so Aurora's tools and agent loop work against any
mailbox without caring which provider backs it.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.mime.text import MIMEText


@dataclass(frozen=True)
class EmailSummary:
    """Lightweight inbox-list item."""

    id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    message_id: str = ""  # RFC822 Message-ID header, for threading replies
    references: str = ""


@dataclass(frozen=True)
class EmailMessage:
    """A full message with a decoded plaintext body."""

    id: str
    thread_id: str
    sender: str
    to: str
    subject: str
    date: str
    snippet: str
    body: str
    message_id: str = ""
    references: str = ""


@dataclass(frozen=True)
class Reply:
    """A reply Aurora intends to send or save as a draft."""

    thread_id: str
    to: str
    subject: str
    body: str
    in_reply_to: str = ""
    references: str = ""

    @classmethod
    def to_message(cls, original: EmailMessage, body: str) -> "Reply":
        """Build a threaded reply to ``original`` with the given body."""
        refs = " ".join(p for p in (original.references, original.message_id) if p).strip()
        return cls(
            thread_id=original.thread_id,
            to=original.sender,
            subject=reply_subject(original.subject),
            body=body,
            in_reply_to=original.message_id,
            references=refs,
        )


def reply_subject(subject: str) -> str:
    """Prefix 'Re: ' unless the subject already starts with it."""
    subject = (subject or "").strip()
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}" if subject else "Re:"


def build_mime(reply: Reply) -> MIMEText:
    """Build an RFC-822 MIMEText with threading headers (no From — set by sender)."""
    mime = MIMEText(reply.body, "plain", "utf-8")
    mime["To"] = reply.to
    mime["Subject"] = reply.subject
    if reply.in_reply_to:
        mime["In-Reply-To"] = reply.in_reply_to
    if reply.references:
        mime["References"] = reply.references
    return mime


def build_raw(reply: Reply) -> str:
    """Base64url-encoded RFC-822 message (Gmail API ``raw`` field)."""
    return base64.urlsafe_b64encode(build_mime(reply).as_bytes()).decode("utf-8")


class MailAccount(ABC):
    """One mailbox Aurora can read and act on. ``label`` is e.g. 'personal'/'work'."""

    label: str = "mail"
    address: str = ""

    @abstractmethod
    def list_unread(self, max_results: int = 20) -> list[EmailSummary]: ...

    @abstractmethod
    def search(self, query: str, max_results: int = 20) -> list[EmailSummary]: ...

    @abstractmethod
    def get_message(self, msg_id: str) -> EmailMessage: ...

    @abstractmethod
    def create_draft(self, reply: Reply) -> str: ...

    @abstractmethod
    def send_reply(self, reply: Reply) -> str: ...

    @abstractmethod
    def archive(self, msg_id: str) -> None: ...
