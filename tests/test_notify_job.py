import asyncio
import json

from aurora.notify.job import poll_once
from aurora.notify.state import NotifyState
from aurora.sources.base import EmailSummary
from aurora.sources.registry import MailAccounts


class FakeAccount:
    def __init__(self, summaries):
        self._s = summaries

    def list_unread(self, limit=20):
        return self._s[:limit]


class FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    def complete(self, messages, **kwargs):
        return self._reply


class Recorder:
    def __init__(self):
        self.sent = []

    async def __call__(self, text, meta):
        self.sent.append((text, meta))


def _summary(id, subj="Subject", sender="Ann <ann@x.com>"):
    return EmailSummary(id=id, thread_id="t", sender=sender, subject=subj, date="", snippet="snip")


def _run(coro):
    return asyncio.run(coro)


def test_first_poll_seeds_silently(tmp_path):
    acc = FakeAccount([_summary("1"), _summary("2")])
    accounts = MailAccounts({"work": acc})
    state = NotifyState(tmp_path)
    rec = Recorder()
    _run(poll_once(accounts, state, FakeLLM("[]"), None, rec))
    assert rec.sent == []  # no startup flood
    assert not state.is_first_contact("work")


def test_new_email_notifies(tmp_path):
    acc = FakeAccount([_summary("1")])
    accounts = MailAccounts({"work": acc})
    state = NotifyState(tmp_path)
    rec = Recorder()
    _run(poll_once(accounts, state, FakeLLM("[]"), None, rec))  # seed
    acc._s = [_summary("2", subj="Deadline"), _summary("1")]
    llm = FakeLLM('[{"id":"2","decision":"notify","headline":"Boss asks about deadline"}]')
    _run(poll_once(accounts, state, llm, None, rec))
    assert len(rec.sent) == 1
    text, meta = rec.sent[0]
    assert "deadline" in text.lower()
    assert meta["account"] == "work" and meta["decision"] == "notify"


def test_skip_is_silent_and_marked_seen(tmp_path):
    acc = FakeAccount([_summary("1")])
    accounts = MailAccounts({"work": acc})
    state = NotifyState(tmp_path)
    rec = Recorder()
    _run(poll_once(accounts, state, FakeLLM("[]"), None, rec))  # seed
    acc._s = [_summary("2", subj="50% OFF"), _summary("1")]
    llm = FakeLLM('[{"id":"2","decision":"skip","headline":"promo"}]')
    _run(poll_once(accounts, state, llm, None, rec))
    assert rec.sent == []
    assert state.unseen("work", ["2", "1"]) == []  # skipped mail won't re-trigger


def test_ask_sends_a_question(tmp_path):
    acc = FakeAccount([_summary("1")])
    accounts = MailAccounts({"work": acc})
    state = NotifyState(tmp_path)
    rec = Recorder()
    _run(poll_once(accounts, state, FakeLLM("[]"), None, rec))  # seed
    acc._s = [_summary("2", subj="Webinar invite"), _summary("1")]
    llm = FakeLLM('[{"id":"2","decision":"ask","headline":"webinar"}]')
    _run(poll_once(accounts, state, llm, None, rec))
    assert len(rec.sent) == 1
    assert "?" in rec.sent[0][0]


def test_commitment_surfaced_in_meta(tmp_path):
    acc = FakeAccount([_summary("1")])
    accounts = MailAccounts({"work": acc})
    state = NotifyState(tmp_path)
    rec = Recorder()
    _run(poll_once(accounts, state, FakeLLM("[]"), None, rec))  # seed
    acc._s = [_summary("2", subj="Proposal"), _summary("1")]
    llm = FakeLLM(
        '[{"id":"2","decision":"notify","headline":"Sara wants the proposal",'
        '"commitment":"Reply to Sara about the proposal"}]'
    )
    _run(poll_once(accounts, state, llm, None, rec))
    _text, meta = rec.sent[0]
    assert meta["commitment"] == "Reply to Sara about the proposal"
    assert meta["email_id"] == "2"  # so the source dedup key can be built


def test_no_commitment_leaves_field_empty(tmp_path):
    acc = FakeAccount([_summary("1")])
    accounts = MailAccounts({"work": acc})
    state = NotifyState(tmp_path)
    rec = Recorder()
    _run(poll_once(accounts, state, FakeLLM("[]"), None, rec))  # seed
    acc._s = [_summary("2", subj="FYI newsletter"), _summary("1")]
    llm = FakeLLM('[{"id":"2","decision":"notify","headline":"newsletter"}]')
    _run(poll_once(accounts, state, llm, None, rec))
    assert rec.sent[0][1]["commitment"] == ""


def test_cap_limits_notifications(tmp_path):
    acc = FakeAccount([_summary("seed")])
    accounts = MailAccounts({"work": acc})
    state = NotifyState(tmp_path)
    rec = Recorder()
    _run(poll_once(accounts, state, FakeLLM("[]"), None, rec))  # seed
    new = [_summary(str(i), subj=f"E{i}") for i in range(8)]
    acc._s = new + [_summary("seed")]
    reply = json.dumps([{"id": str(i), "decision": "notify", "headline": f"h{i}"} for i in range(8)])
    _run(poll_once(accounts, state, FakeLLM(reply), None, rec))
    assert len(rec.sent) == 7  # 6 individual + 1 "…and N more"
    assert "more" in rec.sent[-1][0]
    assert rec.sent[-1][1] is None
