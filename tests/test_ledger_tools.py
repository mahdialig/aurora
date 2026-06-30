import json

from aurora.ledger.store import LedgerStore
from aurora.tools.ledger_tools import build_ledger_tools


def _tools(tmp_path):
    led = LedgerStore(tmp_path)
    return led, {t.name: t for t in build_ledger_tools(led)}


def test_tools_are_inline_not_actions(tmp_path):
    _, by_name = _tools(tmp_path)
    assert set(by_name) == {"add_commitment", "list_commitments", "update_commitment", "mark_done"}
    for t in by_name.values():
        assert t.handler is not None
        assert t.is_action is False


def test_add_commitment(tmp_path):
    led, by_name = _tools(tmp_path)
    out = json.loads(by_name["add_commitment"].handler({"text": "Reply to Sara", "kind": "reply", "due": "2026-07-03"}))
    assert out["tracked"]["id"] == "c1"
    assert out["tracked"]["kind"] == "reply"
    assert len(led.entries()) == 1


def test_add_commitment_requires_text(tmp_path):
    _, by_name = _tools(tmp_path)
    out = json.loads(by_name["add_commitment"].handler({"text": "  "}))
    assert "error" in out


def test_add_commitment_defaults_source_to_chat(tmp_path):
    led, by_name = _tools(tmp_path)
    by_name["add_commitment"].handler({"text": "thing"})
    assert led.entries()[0].source == "chat"


def test_list_commitments(tmp_path):
    led, by_name = _tools(tmp_path)
    led.add("open one")
    led.add("waiting one", status="waiting")
    everything = json.loads(by_name["list_commitments"].handler({}))
    assert len(everything["commitments"]) == 2
    only_waiting = json.loads(by_name["list_commitments"].handler({"status": "waiting"}))
    assert [c["text"] for c in only_waiting["commitments"]] == ["waiting one"]


def test_update_commitment(tmp_path):
    led, by_name = _tools(tmp_path)
    c = led.add("thing")
    out = json.loads(by_name["update_commitment"].handler({"id": c.id, "status": "blocked"}))
    assert out["updated"]["status"] == "blocked"
    bad = json.loads(by_name["update_commitment"].handler({"id": "c999", "status": "open"}))
    assert "error" in bad


def test_mark_done(tmp_path):
    led, by_name = _tools(tmp_path)
    c = led.add("thing")
    out = json.loads(by_name["mark_done"].handler({"id": c.id}))
    assert out["done"]["id"] == c.id
    assert led.get(c.id).is_done
