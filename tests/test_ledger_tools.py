import json

from aurora.ledger.store import LedgerStore
from aurora.tools.ledger_tools import build_ledger_tools


def _tools(tmp_path):
    led = LedgerStore(tmp_path)
    return led, {t.name: t for t in build_ledger_tools(led)}


def test_tool_set_and_kinds(tmp_path):
    _, by_name = _tools(tmp_path)
    assert set(by_name) == {
        "propose_commitment", "suggest_step_done",
        "list_commitments", "update_commitment", "mark_done",
    }
    # Capture + tick-off are action tools (no handler, short-circuit for approval).
    for name in ("propose_commitment", "suggest_step_done"):
        assert by_name[name].is_action is True
        assert by_name[name].handler is None
    # The rest run inline.
    for name in ("list_commitments", "update_commitment", "mark_done"):
        assert by_name[name].is_action is False
        assert by_name[name].handler is not None


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


def test_mark_done_flat(tmp_path):
    led, by_name = _tools(tmp_path)
    c = led.add("thing")
    out = json.loads(by_name["mark_done"].handler({"id": c.id}))
    assert out["done"]["id"] == c.id
    assert led.get(c.id).is_done


def test_mark_done_guards_on_open_steps(tmp_path):
    led, by_name = _tools(tmp_path)
    c = led.add("Reply re: tender", steps=["Send reply", "Prepare File A"])
    # Steps remain → guard returns needs_confirmation instead of closing.
    out = json.loads(by_name["mark_done"].handler({"id": c.id}))
    assert out["needs_confirmation"] is True
    assert out["open_steps"] == ["Send reply", "Prepare File A"]
    assert not led.get(c.id).is_done
    # force:true completes anyway.
    forced = json.loads(by_name["mark_done"].handler({"id": c.id, "force": True}))
    assert forced["done"]["id"] == c.id
    assert led.get(c.id).is_done
