"""Work mail source over IMAP/SMTP (e.g. a cPanel/Dovecot host like dapurhosting).

The provider-agnostic sibling of :mod:`aurora.sources.gmail`: same dataclasses,
same :class:`MailAccount` interface, different transport. Reads/searches over IMAP,
saves drafts via IMAP ``APPEND``, sends via SMTP (and files a copy in Sent).

Design notes:
- ``imaplib``/``smtplib`` are stdlib, imported at module top (no heavy optional deps).
- Connections are opened **per operation**: IMAP servers drop idle connections, and the
  bot is long-lived, so caching one connection would mostly hand back stale sockets.
- :class:`ImapAccount` takes connection **factories** (zero-arg callables returning a
  connected, authenticated client) so tests can inject fakes. Use
  :meth:`ImapAccount.from_config` for the real thing.
- Fetches always use ``BODY.PEEK[]`` so reading mail for the user never marks it \\Seen.
"""

from __future__ import annotations

import email
import imaplib
import re
import smtplib
from email.message import Message
from email.utils import formataddr

from aurora.sources.base import (
    EmailMessage,
    EmailSummary,
    MailAccount,
    Reply,
    build_mime,
    strip_html,
)

_SNIPPET_CHARS = 120


class ImapError(RuntimeError):
    """Raised when the work mailbox isn't configured or can't be reached."""


# --------------------------------------------------------------------------- #
# Pure helpers (no network) — unit-tested directly
# --------------------------------------------------------------------------- #


def extract_body(msg: Message) -> str:
    """Return the best plaintext body of an ``email.message.Message``.

    Prefers ``text/plain``; falls back to a crude strip of ``text/html``.
    """
    plain = _find_body(msg, "text/plain")
    if plain:
        return plain
    html = _find_body(msg, "text/html")
    return strip_html(html) if html else ""


def _find_body(msg: Message, mime_type: str) -> str:
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() != mime_type:
            continue
        if (part.get_content_disposition() or "") == "attachment":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace").strip()
    return ""


def _snippet(body: str) -> str:
    flat = re.sub(r"\s+", " ", body).strip()
    return flat[:_SNIPPET_CHARS]


def parse_summary(uid: str, msg: Message) -> EmailSummary:
    """Build a lightweight summary from a fetched message."""
    return EmailSummary(
        id=str(uid),
        thread_id=(msg.get("Message-ID", "") or "").strip(),
        sender=msg.get("From", ""),
        subject=msg.get("Subject", ""),
        date=msg.get("Date", ""),
        snippet=_snippet(extract_body(msg)),
        message_id=(msg.get("Message-ID", "") or "").strip(),
        references=(msg.get("References", "") or "").strip(),
    )


def parse_message(uid: str, msg: Message) -> EmailMessage:
    """Build a full message (with decoded body) from a fetched message."""
    body = extract_body(msg)
    return EmailMessage(
        id=str(uid),
        thread_id=(msg.get("Message-ID", "") or "").strip(),
        sender=msg.get("From", ""),
        to=msg.get("To", ""),
        subject=msg.get("Subject", ""),
        date=msg.get("Date", ""),
        snippet=_snippet(body),
        body=body,
        message_id=(msg.get("Message-ID", "") or "").strip(),
        references=(msg.get("References", "") or "").strip(),
    )


def imap_search_query(query: str) -> list[str]:
    """Translate the tool's query into IMAP SEARCH criteria.

    Supports ``from:x`` and ``subject:x`` prefixes (matching the tool's hint to
    search by sender/subject); anything else becomes a full-text ``TEXT`` search.
    Values are quoted so multi-word queries don't break the IMAP command.
    """
    q = (query or "").strip()
    low = q.lower()
    if low.startswith("from:"):
        return ["FROM", _quote(q[5:].strip())]
    if low.startswith("subject:"):
        return ["SUBJECT", _quote(q[8:].strip())]
    return ["TEXT", _quote(q)]


def _quote(value: str) -> str:
    return '"%s"' % value.replace('"', "")


def _uids_from_search(data: list) -> list[str]:
    """Parse an IMAP SEARCH response payload into a list of UID strings."""
    out: list[str] = []
    for chunk in data or []:
        if not chunk:
            continue
        text = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
        out.extend(text.split())
    return out


def _newest_first(uids: list[str], max_results: int) -> list[str]:
    """Highest UID == most recently arrived; cap to ``max_results``."""
    ordered = sorted(uids, key=lambda u: int(u) if u.isdigit() else 0, reverse=True)
    return ordered[:max_results]


def parse_fetch(data: list) -> list[tuple[str, Message]]:
    """Parse an IMAP ``FETCH ... BODY.PEEK[]`` response into (uid, Message) pairs."""
    out: list[tuple[str, Message]] = []
    for item in data or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        envelope, raw = item[0], item[1]
        env_text = envelope.decode() if isinstance(envelope, bytes) else str(envelope)
        m = re.search(r"UID (\d+)", env_text)
        uid = m.group(1) if m else ""
        msg = email.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode())
        out.append((uid, msg))
    return out


def resolve_special_folder(imap, flag: str, fallback: str) -> str:
    """Find the mailbox carrying an IMAP special-use ``flag`` (e.g. '\\Sent').

    Falls back to ``fallback`` (and to ``INBOX.<fallback>`` is left to the server)
    when the server doesn't advertise the flag.
    """
    try:
        typ, data = imap.list()
    except Exception:  # noqa: BLE001 - LIST is best-effort
        return fallback
    if typ != "OK":
        return fallback
    flag_l = flag.lower().encode()
    for line in data or []:
        raw = line if isinstance(line, bytes) else str(line).encode()
        if flag_l not in raw.lower():
            continue
        name = _folder_name(raw.decode(errors="replace"))
        if name:
            return name
    return fallback


def _folder_name(list_line: str) -> str:
    """Extract the mailbox name from a single IMAP LIST response line.

    The name is the token after the ``(flags) "delim"`` prefix. Servers differ on
    whether they quote it — Dovecot/cPanel sends it bare (``... "." INBOX.Sent``),
    others quote it (``... "." "Sent Items"``). Handle both.
    """
    after = list_line.split(")", 1)[-1].strip()  # drop the "(flags)" prefix
    m = re.search(r'"([^"]*)"\s*$', after)  # quoted name (may contain spaces)
    if m:
        return m.group(1)
    parts = after.split()
    return parts[-1] if parts else ""


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


class ImapAccount(MailAccount):
    """Read and act on a mailbox over IMAP/SMTP. Wraps connection factories."""

    def __init__(
        self,
        imap_factory,
        smtp_factory,
        address: str,
        label: str = "work",
        from_name: str = "",
    ) -> None:
        self._imap_factory = imap_factory
        self._smtp_factory = smtp_factory
        self.address = address
        self.label = label
        self.from_name = from_name

    @classmethod
    def from_config(cls, config, label: str = "work") -> "ImapAccount":
        email_addr = getattr(config, "work_email", "")
        password = getattr(config, "work_password", "")
        if not email_addr or not password:
            raise ImapError(
                "Work mailbox not configured. Set WORK_EMAIL and WORK_PASSWORD in .env."
            )
        imap_host = config.work_imap_host
        imap_port = config.work_imap_port
        smtp_host = config.work_smtp_host
        smtp_port = config.work_smtp_port

        def imap_factory():
            conn = imaplib.IMAP4_SSL(imap_host, imap_port)
            conn.login(email_addr, password)
            return conn

        def smtp_factory():
            conn = smtplib.SMTP_SSL(smtp_host, smtp_port)
            conn.login(email_addr, password)
            return conn

        return cls(imap_factory, smtp_factory, address=email_addr, label=label)

    # -- connection plumbing ------------------------------------------------- #

    def _with_imap(self, fn):
        """Run ``fn(imap)`` against a fresh connection, always logging out after."""
        imap = self._imap_factory()
        try:
            return fn(imap)
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001 - logout failures are not actionable
                pass

    def _fetch(self, imap, uids: list[str]) -> list[tuple[str, Message]]:
        if not uids:
            return []
        typ, data = imap.uid("FETCH", ",".join(uids), "(BODY.PEEK[])")
        if typ != "OK":
            return []
        pairs = parse_fetch(data)
        order = {u: i for i, u in enumerate(uids)}
        pairs.sort(key=lambda p: order.get(p[0], len(order)))
        return pairs

    # -- MailAccount interface ---------------------------------------------- #

    def list_unread(self, max_results: int = 20) -> list[EmailSummary]:
        def run(imap):
            imap.select("INBOX")
            typ, data = imap.uid("SEARCH", None, "UNSEEN")
            if typ != "OK":
                return []
            uids = _newest_first(_uids_from_search(data), max_results)
            return [parse_summary(uid, msg) for uid, msg in self._fetch(imap, uids)]

        return self._with_imap(run)

    def search(self, query: str, max_results: int = 20) -> list[EmailSummary]:
        criteria = imap_search_query(query)

        def run(imap):
            out: list[EmailSummary] = []
            seen: set[str] = set()
            # INBOX first, then Junk (best-effort) — mirrors Gmail covering spam.
            junk = resolve_special_folder(imap, "\\Junk", "INBOX.spam")
            for folder in ("INBOX", junk):
                typ, _ = imap.select(folder)
                if typ != "OK":
                    continue
                typ, data = imap.uid("SEARCH", None, *criteria)
                if typ != "OK":
                    continue
                uids = _newest_first(_uids_from_search(data), max_results)
                for uid, msg in self._fetch(imap, uids):
                    key = f"{folder}:{uid}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(parse_summary(uid, msg))
            return out[:max_results]

        return self._with_imap(run)

    def get_message(self, msg_id: str) -> EmailMessage:
        def run(imap):
            imap.select("INBOX")
            pairs = self._fetch(imap, [str(msg_id)])
            if not pairs:
                raise ImapError(f"Message {msg_id} not found in INBOX.")
            uid, msg = pairs[0]
            return parse_message(uid, msg)

        return self._with_imap(run)

    def create_draft(self, reply: Reply) -> str:
        mime = self._build(reply)

        def run(imap):
            folder = resolve_special_folder(imap, "\\Drafts", "INBOX.Drafts")
            imap.append(folder, "(\\Draft)", None, mime.as_bytes())
            return folder

        return self._with_imap(run)

    def send_reply(self, reply: Reply) -> str:
        mime = self._build(reply)
        smtp = self._smtp_factory()
        try:
            smtp.send_message(mime)
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                pass
        # File a copy in Sent so it shows up in webmail like a normal sent mail.
        try:
            self._with_imap(
                lambda imap: imap.append(
                    resolve_special_folder(imap, "\\Sent", "INBOX.Sent"),
                    "(\\Seen)",
                    None,
                    mime.as_bytes(),
                )
            )
        except Exception:  # noqa: BLE001 - the send already succeeded; Sent copy is best-effort
            pass
        return mime.get("Message-ID", "") or ""

    def archive(self, msg_id: str) -> None:
        """Best-effort 'archive' (no Gmail equivalent over IMAP; unused by tools today).

        Moves the message to the Archive special folder if one exists, else just
        marks it \\Seen. Deliberately conservative since nothing calls this yet.
        """

        def run(imap):
            imap.select("INBOX")
            archive = resolve_special_folder(imap, "\\Archive", "")
            if archive:
                imap.uid("COPY", str(msg_id), archive)
                imap.uid("STORE", str(msg_id), "+FLAGS", "(\\Deleted)")
                imap.expunge()
            else:
                imap.uid("STORE", str(msg_id), "+FLAGS", "(\\Seen)")

        self._with_imap(run)

    # -- helpers ------------------------------------------------------------- #

    def _build(self, reply: Reply):
        mime = build_mime(reply)
        mime["From"] = formataddr((self.from_name, self.address)) if self.from_name else self.address
        return mime
