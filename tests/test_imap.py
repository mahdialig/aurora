import email
from email.message import EmailMessage as MimeMessage

from aurora.sources.base import Reply
from aurora.sources.imap import (
    ImapAccount,
    _folder_name,
    extract_body,
    imap_search_query,
    parse_message,
    parse_summary,
)


# --- helpers: build raw RFC-822 messages the way a server would hand them back --- #


def _raw(
    subject="Hi",
    sender="Boss <boss@co.com>",
    to="me@matajari.co.id",
    body="hello body",
    message_id="<abc@co.com>",
    references="",
):
    m = MimeMessage()
    m["From"] = sender
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = "Mon, 29 Jun 2026 10:00:00 +0000"
    m["Message-ID"] = message_id
    if references:
        m["References"] = references
    m.set_content(body)
    return m.as_bytes()


def _raw_multipart(plain, html):
    m = MimeMessage()
    m["Subject"] = "Multi"
    m.set_content(plain)
    m.add_alternative(html, subtype="html")
    return m.as_bytes()


def _msg(raw):
    return email.message_from_bytes(raw)


# --- pure helpers --------------------------------------------------------- #


def test_extract_body_prefers_plain():
    msg = _msg(_raw_multipart("hello plain", "<p>hello html</p>"))
    assert extract_body(msg) == "hello plain"


def test_extract_body_falls_back_to_html():
    m = MimeMessage()
    m["Subject"] = "X"
    m.set_content("<p>hello <b>world</b></p>", subtype="html")
    msg = _msg(m.as_bytes())
    out = extract_body(msg)
    assert "hello" in out and "<" not in out


def test_imap_search_query_prefixes():
    assert imap_search_query("from:boss@co.com") == ["FROM", '"boss@co.com"']
    assert imap_search_query("subject:invoice") == ["SUBJECT", '"invoice"']
    assert imap_search_query("quarterly report") == ["TEXT", '"quarterly report"']


def test_folder_name_handles_bare_and_quoted():
    # Dovecot/cPanel sends bare names; other servers quote them.
    assert _folder_name('(\\HasNoChildren \\Sent) "." INBOX.Sent') == "INBOX.Sent"
    assert _folder_name('(\\HasNoChildren \\Sent) "." "Sent Items"') == "Sent Items"


def test_parse_summary_and_message_fields():
    msg = _msg(_raw(subject="Deadline", references="<root@co.com>"))
    s = parse_summary("7", msg)
    assert s.id == "7" and s.subject == "Deadline"
    assert s.message_id == "<abc@co.com>"
    assert s.references == "<root@co.com>"
    assert s.snippet == "hello body"

    m = parse_message("7", msg)
    assert m.id == "7" and m.body == "hello body"
    assert m.sender == "Boss <boss@co.com>" and m.to == "me@matajari.co.id"
    assert m.message_id == "<abc@co.com>"


# --- ImapAccount against fake IMAP/SMTP connections ----------------------- #


class _FakeImap:
    def __init__(self, *, unseen=None, search=None, messages=None):
        self.rec = {}
        self._unseen = unseen or []
        self._search = search if search is not None else []
        self._messages = messages or {}  # uid -> raw bytes
        # Real dapurhosting/Dovecot format: bare (unquoted) folder names.
        self._folders = [
            b'(\\HasNoChildren \\UnMarked \\Sent) "." INBOX.Sent',
            b'(\\HasNoChildren \\UnMarked \\Drafts) "." INBOX.Drafts',
            b'(\\HasNoChildren \\UnMarked \\Junk) "." INBOX.spam',
            b'(\\HasNoChildren \\UnMarked \\Archive) "." INBOX.Archive',
        ]

    def select(self, folder):
        self.rec.setdefault("select", []).append(folder)
        return ("OK", [b"1"]) if folder == "INBOX" else ("NO", [b"no such"])

    def uid(self, command, *args):
        self.rec.setdefault("uid", []).append((command, args))
        cmd = command.upper()
        if cmd == "SEARCH":
            uids = self._unseen if "UNSEEN" in args else self._search
            return ("OK", [" ".join(uids).encode()])
        if cmd == "FETCH":
            data = []
            for u in args[0].split(","):
                raw = self._messages.get(u)
                if raw is None:
                    continue
                data.append((f"1 (UID {u} BODY[] {{{len(raw)}}}".encode(), raw))
                data.append(b")")
            return ("OK", data)
        return ("OK", [b""])

    def list(self, *a, **k):
        self.rec["list"] = True
        return ("OK", self._folders)

    def append(self, folder, flags, date, message):
        self.rec.setdefault("append", []).append((folder, flags, message))
        return ("OK", [b"ok"])

    def expunge(self):
        self.rec["expunge"] = True
        return ("OK", [b""])

    def logout(self):
        self.rec["logout"] = True
        return ("BYE", [b""])


class _FakeSmtp:
    def __init__(self):
        self.rec = {}

    def send_message(self, msg):
        self.rec["sent"] = msg

    def quit(self):
        self.rec["quit"] = True


def _account(imap, smtp=None):
    smtp = smtp or _FakeSmtp()
    return ImapAccount(lambda: imap, lambda: smtp, address="me@matajari.co.id", from_name="Mahdi")


def test_list_unread_searches_unseen_newest_first():
    imap = _FakeImap(
        unseen=["1", "2"],
        messages={"1": _raw(subject="Older"), "2": _raw(subject="Newer")},
    )
    out = _account(imap).list_unread(max_results=5)
    # SEARCH was issued for UNSEEN over INBOX.
    assert ("SEARCH", (None, "UNSEEN")) in imap.rec["uid"]
    assert imap.rec["select"][0] == "INBOX"
    # Highest UID (2) comes first.
    assert [s.subject for s in out] == ["Newer", "Older"]
    assert imap.rec["logout"] is True


def test_get_message_fetches_body():
    imap = _FakeImap(messages={"9": _raw(subject="Deal", body="the deal body")})
    m = _account(imap).get_message("9")
    assert m.subject == "Deal" and m.body == "the deal body"


def test_search_translates_query():
    imap = _FakeImap(search=["3"], messages={"3": _raw(subject="Found")})
    out = _account(imap).search("from:boss@co.com", max_results=5)
    flat = [a for _, args in imap.rec["uid"] for a in args]
    assert "FROM" in flat
    assert [s.subject for s in out] == ["Found"]


def test_create_draft_appends_with_draft_flag():
    imap = _FakeImap()
    reply = Reply(
        thread_id="<abc@co.com>",
        to="boss@co.com",
        subject="Re: Deal",
        body="On it.",
        in_reply_to="<abc@co.com>",
        references="<root@co.com> <abc@co.com>",
    )
    folder = _account(imap).create_draft(reply)
    assert folder == "INBOX.Drafts"
    appended_folder, flags, raw = imap.rec["append"][0]
    assert appended_folder == "INBOX.Drafts" and flags == "(\\Draft)"
    parsed = email.message_from_bytes(raw)
    assert parsed["From"].endswith("<me@matajari.co.id>")
    assert parsed["To"] == "boss@co.com"
    assert parsed["In-Reply-To"] == "<abc@co.com>"
    assert parsed["References"] == "<root@co.com> <abc@co.com>"


def test_send_reply_sends_and_files_sent_copy():
    imap = _FakeImap()
    smtp = _FakeSmtp()
    reply = Reply(thread_id="<abc@co.com>", to="boss@co.com", subject="Re: Deal", body="Yes.")
    _account(imap, smtp).send_reply(reply)
    # SMTP actually sent the message...
    assert smtp.rec["sent"]["To"] == "boss@co.com"
    assert smtp.rec["sent"]["From"].endswith("<me@matajari.co.id>")
    assert smtp.rec["quit"] is True
    # ...and a copy was filed in Sent.
    appended_folder, _, _ = imap.rec["append"][0]
    assert appended_folder == "INBOX.Sent"


def test_archive_moves_to_archive_folder():
    imap = _FakeImap()
    _account(imap).archive("4")
    copies = [c for c in imap.rec["uid"] if c[0] == "COPY"]
    assert copies and copies[0][1][1] == "INBOX.Archive"
    assert imap.rec["expunge"] is True
