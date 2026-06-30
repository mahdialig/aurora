from aurora.notify.classifier import build_prompt, classify_new


class _FakeLLM:
    def __init__(self, reply):
        self._reply = reply
        self.seen_messages = None

    def complete(self, messages, **kwargs):
        self.seen_messages = messages
        return self._reply


_ITEMS = [
    {"id": "1", "account": "work", "from": "Boss <boss@co.com>", "subject": "Deadline", "snippet": "ship?"},
    {"id": "2", "account": "personal", "from": "Shop <no-reply@shop.com>", "subject": "50% OFF", "snippet": "sale"},
]


def test_build_prompt_includes_memory_and_emails():
    msgs = build_prompt(_ITEMS, "don't notify me about promotions")
    user = msgs[-1].content
    assert "don't notify me about promotions" in user
    assert "Deadline" in user and "50% OFF" in user


def test_classify_parses_decisions():
    reply = '[{"id":"1","decision":"notify","headline":"Boss asks about deadline"},' \
            '{"id":"2","decision":"skip","headline":"promo"}]'
    verdicts = classify_new(_FakeLLM(reply), _ITEMS, "")
    by_id = {v.id: v for v in verdicts}
    assert by_id["1"].decision == "notify"
    assert by_id["2"].decision == "skip"


def test_classify_tolerates_fences_and_prose():
    reply = 'Sure!\n```json\n[{"id":"1","decision":"ask","headline":"x"},{"id":"2","decision":"skip","headline":"y"}]\n```'
    verdicts = classify_new(_FakeLLM(reply), _ITEMS, "")
    assert {v.id: v.decision for v in verdicts} == {"1": "ask", "2": "skip"}


def test_classify_fallback_on_garbage_notifies_all():
    verdicts = classify_new(_FakeLLM("the model said something useless"), _ITEMS, "")
    assert all(v.decision == "notify" for v in verdicts)
    assert {v.id for v in verdicts} == {"1", "2"}


def test_classify_unknown_decision_defaults_to_notify():
    reply = '[{"id":"1","decision":"maybe","headline":"x"},{"id":"2","decision":"skip","headline":"y"}]'
    by_id = {v.id: v for v in classify_new(_FakeLLM(reply), _ITEMS, "")}
    assert by_id["1"].decision == "notify"  # unknown -> notify


def test_classify_missing_email_is_notified():
    reply = '[{"id":"1","decision":"skip","headline":"x"}]'  # model omitted id 2
    by_id = {v.id: v for v in classify_new(_FakeLLM(reply), _ITEMS, "")}
    assert by_id["2"].decision == "notify"  # never silently dropped
