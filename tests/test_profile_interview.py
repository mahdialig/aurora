import pytest

from aurora.profile.interview import QUESTIONS, distill


def test_questions_have_unique_keys():
    keys = [q.key for q in QUESTIONS]
    assert len(keys) == len(set(keys)), "duplicate question keys"


def test_questions_well_formed():
    for q in QUESTIONS:
        assert q.key and q.key.replace("_", "").isalnum()
        assert q.label.strip()
        # Each preset option is a (button label, canonical value) pair, both non-empty.
        for opt in q.options:
            assert len(opt) == 2
            label, value = opt
            assert label.strip() and value.strip()


def test_core_levers_present():
    keys = {q.key for q in QUESTIONS}
    # The answers Aurora actually acts on must exist.
    for required in ("preferred_name", "notify_threshold", "vips", "reply_tone", "signature"):
        assert required in keys


class _OkLLM:
    def complete(self, messages, **kwargs):
        return "  Tidy value.  "


class _BoomLLM:
    def complete(self, messages, **kwargs):
        raise RuntimeError("model down")


def test_distill_uses_llm_output():
    q = QUESTIONS[0]
    assert distill(_OkLLM(), q, "uhh just call me whatever") == "Tidy value."


def test_distill_falls_back_to_raw_on_failure():
    q = QUESTIONS[0]
    assert distill(_BoomLLM(), q, "  call me Aji  ") == "call me Aji"


def test_distill_empty_passthrough():
    q = QUESTIONS[0]
    # Empty stays empty without calling the model.
    assert distill(_BoomLLM(), q, "   ") == ""


@pytest.mark.parametrize("q", QUESTIONS, ids=[q.key for q in QUESTIONS])
def test_distill_empty_string_for_every_question(q):
    assert distill(_BoomLLM(), q, "") == ""
