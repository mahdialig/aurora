import json

from aurora.memory.store import MemoryStore
from aurora.tools.notify_tools import build_notify_tools


def _tool(memory):
    return {t.name: t for t in build_notify_tools(memory)}["set_notification_rule"]


def test_mute_rule_saved_to_memory(tmp_path):
    mem = MemoryStore(tmp_path)
    tool = _tool(mem)
    out = json.loads(tool.handler({"rule": "newsletters", "kind": "mute"}))
    assert "newsletters" in out["saved"]
    texts = [e.text for e in mem.entries()]
    assert any("don't notify me about" in t and "newsletters" in t for t in texts)


def test_prioritize_rule_saved(tmp_path):
    mem = MemoryStore(tmp_path)
    out = json.loads(_tool(mem).handler({"rule": "anything from my bank", "kind": "prioritize"}))
    assert "bank" in out["saved"]
    assert any("always flag" in e.text for e in mem.entries())


def test_empty_rule_rejected(tmp_path):
    mem = MemoryStore(tmp_path)
    out = json.loads(_tool(mem).handler({"rule": "", "kind": "mute"}))
    assert "error" in out
    assert mem.is_empty()
