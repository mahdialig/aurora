import json

from aurora.ledger.propose import revise_steps


class _LLM:
    """A fake LLM that returns a canned (optionally fenced) JSON reply."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        return self.reply


class _BoomLLM:
    def complete(self, messages, **kwargs):
        raise RuntimeError("model down")


BASE = {
    "text": "Reply re: tender",
    "kind": "reply",
    "owner": "me",
    "due": "2026-07-03",
    "steps": ["Send the reply", "Prepare File A", "Prepare File B"],
    "source": "chat",
}


def test_revise_applies_json_and_preserves_passthrough_fields():
    llm = _LLM(json.dumps({"text": "Reply re: tender", "due": "2026-07-04T17:00",
                           "steps": ["Send the reply", "Prepare File A"]}))
    out = revise_steps(llm, BASE, "drop File B and set the due to 4 Jul 5pm")
    assert out["steps"] == ["Send the reply", "Prepare File A"]
    assert out["due"] == "2026-07-04T17:00"
    # kind/owner/source are not revised.
    assert out["kind"] == "reply" and out["owner"] == "me" and out["source"] == "chat"


def test_revise_collapse_to_single_item():
    llm = _LLM(json.dumps({"text": "Reply re: tender", "due": "2026-07-03", "steps": []}))
    out = revise_steps(llm, BASE, "just track it as one item")
    assert out["steps"] == []


def test_revise_tolerates_code_fences():
    llm = _LLM("```json\n" + json.dumps({"text": "X", "due": "", "steps": ["only step"]}) + "\n```")
    out = revise_steps(llm, BASE, "rename")
    assert out["steps"] == ["only step"]
    assert out["text"] == "X"
    assert out["due"] == ""


def test_revise_falls_back_to_unchanged_on_failure():
    assert revise_steps(_BoomLLM(), BASE, "do something") == BASE


def test_revise_bad_json_keeps_payload():
    assert revise_steps(_LLM("not json at all"), BASE, "change") == BASE


def test_revise_empty_instruction_no_call():
    llm = _LLM("{}")
    assert revise_steps(llm, BASE, "   ") == BASE
    assert llm.calls == 0
