import base64
import email

from aurora.sources.base import EmailMessage, Reply, build_raw, reply_subject
from aurora.sources.gmail import (
    GmailClient,
    extract_plaintext,
    header,
    parse_message,
    parse_summary,
)


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def test_header_case_insensitive():
    headers = [{"name": "From", "value": "a@b.com"}, {"name": "Subject", "value": "Hi"}]
    assert header(headers, "from") == "a@b.com"
    assert header(headers, "SUBJECT") == "Hi"
    assert header(headers, "missing") == ""


def test_reply_subject_avoids_double_re():
    assert reply_subject("Lunch?") == "Re: Lunch?"
    assert reply_subject("Re: Lunch?") == "Re: Lunch?"
    assert reply_subject("RE: Lunch?") == "RE: Lunch?"
    assert reply_subject("") == "Re:"


def test_extract_plaintext_prefers_plain():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64url("hello plain")}},
            {"mimeType": "text/html", "body": {"data": _b64url("<p>hello html</p>")}},
        ],
    }
    assert extract_plaintext(payload) == "hello plain"


def test_extract_plaintext_falls_back_to_html():
    payload = {
        "mimeType": "text/html",
        "body": {"data": _b64url("<p>hello <b>world</b></p>")},
    }
    assert "hello" in extract_plaintext(payload)
    assert "<" not in extract_plaintext(payload)


def test_parse_summary():
    msg = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "snip",
        "payload": {
            "headers": [
                {"name": "From", "value": "boss@co.com"},
                {"name": "Subject", "value": "Deadline"},
                {"name": "Date", "value": "Mon, 29 Jun 2026"},
                {"name": "Message-ID", "value": "<abc@co.com>"},
            ]
        },
    }
    s = parse_summary(msg)
    assert s.id == "m1" and s.thread_id == "t1"
    assert s.sender == "boss@co.com" and s.subject == "Deadline"
    assert s.message_id == "<abc@co.com>"


def test_build_raw_sets_threading_headers():
    reply = Reply(
        thread_id="t1",
        to="boss@co.com",
        subject="Re: Deadline",
        body="On it.",
        in_reply_to="<abc@co.com>",
        references="<root@co.com> <abc@co.com>",
    )
    raw = build_raw(reply)
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert parsed["To"] == "boss@co.com"
    assert parsed["Subject"] == "Re: Deadline"
    assert parsed["In-Reply-To"] == "<abc@co.com>"
    assert parsed["References"] == "<root@co.com> <abc@co.com>"
    assert parsed.get_payload(decode=True).decode("utf-8") == "On it."


def test_reply_to_message_builds_references_chain():
    original = EmailMessage(
        id="m1",
        thread_id="t1",
        sender="boss@co.com",
        to="me@me.com",
        subject="Deadline",
        date="",
        snippet="",
        body="When can you ship?",
        message_id="<abc@co.com>",
        references="<root@co.com>",
    )
    reply = Reply.to_message(original, "Friday.")
    assert reply.to == "boss@co.com"
    assert reply.subject == "Re: Deadline"
    assert reply.in_reply_to == "<abc@co.com>"
    assert reply.references == "<root@co.com> <abc@co.com>"
    assert reply.thread_id == "t1"


# --- GmailClient against a fake service ----------------------------------- #


class _FakeExec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeMessages:
    def __init__(self, recorder):
        self._rec = recorder

    def list(self, **kwargs):
        self._rec["list"] = kwargs
        return _FakeExec({"messages": [{"id": "m1"}]})

    def get(self, **kwargs):
        self._rec.setdefault("get", []).append(kwargs)
        return _FakeExec(
            {
                "id": kwargs["id"],
                "threadId": "t1",
                "snippet": "snip",
                "payload": {"headers": [{"name": "Subject", "value": "Hi"}]},
            }
        )

    def send(self, **kwargs):
        self._rec["send"] = kwargs
        return _FakeExec({"id": "sent1"})

    def modify(self, **kwargs):
        self._rec["modify"] = kwargs
        return _FakeExec({})


class _FakeDrafts:
    def __init__(self, recorder):
        self._rec = recorder

    def create(self, **kwargs):
        self._rec["draft"] = kwargs
        return _FakeExec({"id": "draft1"})


class _FakeUsers:
    def __init__(self, recorder):
        self._messages = _FakeMessages(recorder)
        self._drafts = _FakeDrafts(recorder)

    def messages(self):
        return self._messages

    def drafts(self):
        return self._drafts


class _FakeService:
    def __init__(self):
        self.rec = {}
        self._users = _FakeUsers(self.rec)

    def users(self):
        return self._users


def test_client_list_unread_uses_inbox_unread():
    svc = _FakeService()
    client = GmailClient(svc)
    out = client.list_unread(max_results=5)
    assert svc.rec["list"]["labelIds"] == ["INBOX", "UNREAD"]
    assert svc.rec["list"]["maxResults"] == 5
    assert len(out) == 1 and out[0].subject == "Hi"


def test_client_send_reply_passes_thread_and_raw():
    svc = _FakeService()
    client = GmailClient(svc)
    reply = Reply(thread_id="t1", to="x@y.com", subject="Re: Hi", body="hello")
    msg_id = client.send_reply(reply)
    assert msg_id == "sent1"
    assert svc.rec["send"]["body"]["threadId"] == "t1"
    assert "raw" in svc.rec["send"]["body"]


def test_client_create_draft():
    svc = _FakeService()
    client = GmailClient(svc)
    reply = Reply(thread_id="t1", to="x@y.com", subject="Re: Hi", body="hello")
    assert client.create_draft(reply) == "draft1"
    assert svc.rec["draft"]["body"]["message"]["threadId"] == "t1"


def test_client_archive_removes_inbox_label():
    svc = _FakeService()
    GmailClient(svc).archive("m1")
    assert svc.rec["modify"]["body"] == {"removeLabelIds": ["INBOX"]}


def test_parse_message_decodes_body():
    msg = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "snip",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "From", "value": "a@b.com"}],
            "body": {"data": base64.urlsafe_b64encode(b"the body").decode()},
        },
    }
    parsed = parse_message(msg)
    assert parsed.body == "the body"
    assert parsed.sender == "a@b.com"
