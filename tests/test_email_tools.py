import json

from aurora.sources.base import EmailMessage, EmailSummary, MailAccount
from aurora.sources.registry import MailAccounts
from aurora.tools.email_tools import build_email_tools


class FakeAccount(MailAccount):
    def __init__(self, label="personal"):
        self.label = label

    def list_unread(self, max_results=20):
        return [EmailSummary("m1", "t1", "Bob <bob@x.com>", "Hi", "today", "yo")]

    def search(self, query, max_results=20):
        return [EmailSummary("m2", "t2", "Ann <ann@x.com>", query, "today", "found")]

    def get_message(self, msg_id):
        return EmailMessage("m1", "t1", "Bob <bob@x.com>", "me@x.com", "Hi", "today", "yo", "hello body")

    def create_draft(self, reply):
        return "d1"

    def send_reply(self, reply):
        return "s1"

    def archive(self, msg_id):
        pass


def _tools(accounts):
    return {t.name: t for t in build_email_tools(accounts)}


def test_list_unread_returns_summaries():
    tools = _tools(MailAccounts({"personal": FakeAccount()}))
    data = json.loads(tools["list_unread"].handler({"account": "personal"}))
    assert data[0]["from"].startswith("Bob")
    assert data[0]["account"] == "personal"


def test_search_uses_query():
    tools = _tools(MailAccounts({"personal": FakeAccount()}))
    data = json.loads(tools["search_mail"].handler({"query": "invoice", "account": "personal"}))
    assert data[0]["subject"] == "invoice"


def test_read_email_returns_body():
    tools = _tools(MailAccounts({"personal": FakeAccount()}))
    data = json.loads(tools["read_email"].handler({"account": "personal", "id": "m1"}))
    assert data["body"] == "hello body"


def test_read_email_unknown_account_errors():
    tools = _tools(MailAccounts({"personal": FakeAccount()}))
    data = json.loads(tools["read_email"].handler({"account": "work", "id": "m1"}))
    assert "error" in data


def test_list_unread_no_account_connected():
    tools = _tools(MailAccounts({}))
    data = json.loads(tools["list_unread"].handler({"account": "all"}))
    assert "error" in data


def test_all_selector_spans_accounts():
    tools = _tools(MailAccounts({"personal": FakeAccount("personal"), "work": FakeAccount("work")}))
    data = json.loads(tools["list_unread"].handler({"account": "all"}))
    assert {row["account"] for row in data} == {"personal", "work"}


def test_reply_tool_is_action_without_handler():
    tools = _tools(MailAccounts({"personal": FakeAccount()}))
    assert "reply_to_email" in tools
    assert tools["reply_to_email"].is_action is True
    assert tools["reply_to_email"].handler is None


def test_resend_last_draft_is_action():
    tools = _tools(MailAccounts({"personal": FakeAccount()}))
    assert "resend_last_draft" in tools
    assert tools["resend_last_draft"].is_action is True
    assert tools["resend_last_draft"].handler is None


def test_compose_email_is_action():
    tools = _tools(MailAccounts({"personal": FakeAccount()}))
    assert "compose_email" in tools
    assert tools["compose_email"].is_action is True
    assert tools["compose_email"].handler is None
    params = tools["compose_email"].schema["function"]["parameters"]
    assert set(params["required"]) == {"account", "to", "subject", "body"}
