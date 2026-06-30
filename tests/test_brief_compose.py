from aurora.activity.log import ActivityLog
from aurora.brief.compose import build_brief_prompt, compose_brief
from aurora.ledger.store import LedgerStore


class FakeLLM:
    def __init__(self, reply="BRIEF TEXT", boom=False):
        self.reply = reply
        self.boom = boom
        self.calls = []

    def complete(self, messages, temperature=0.0):
        self.calls.append(messages)
        if self.boom:
            raise RuntimeError("llm down")
        return self.reply


def _ledger(tmp_path):
    return LedgerStore(tmp_path)


def test_quiet_day_skips_llm(tmp_path):
    llm = FakeLLM()
    out = compose_brief(llm, _ledger(tmp_path).entries(), [], today_iso="2026-06-30")
    assert out == ""
    assert llm.calls == []


def test_weekly_quiet_day_returns_clean_slate(tmp_path):
    llm = FakeLLM()
    out = compose_brief(llm, [], [], today_iso="2026-06-30", weekly=True)
    assert "clean slate" in out.lower()
    assert llm.calls == []


def test_compose_calls_llm_when_items_exist(tmp_path):
    led = _ledger(tmp_path)
    led.add("Reply to Sara", kind="reply", due="2026-07-02", owner="me")
    llm = FakeLLM(reply="Good morning!")
    out = compose_brief(llm, led.entries(), [], today_iso="2026-06-30")
    assert out == "Good morning!"
    assert len(llm.calls) == 1


def test_prompt_buckets_overdue_due_soon_and_waiting(tmp_path):
    led = _ledger(tmp_path)
    led.add("overdue task", due="2026-06-01", owner="me")
    led.add("due soon", due="2026-07-02", owner="me")
    led.add("far away", due="2026-12-01", owner="me")
    led.add("awaiting reply from Bob", owner="other")
    msgs = build_brief_prompt(
        led.entries(), ["sent invoice to ACME"],
        today_iso="2026-06-30", name="Mahdi", weekly=False, horizon_days=7,
    )
    user = msgs[1].content
    assert "OVERDUE" in user and "overdue task" in user
    assert "DUE SOON" in user and "due soon" in user
    assert "far away" not in user  # outside the 7-day horizon
    assert "WAITING ON OTHERS" in user and "awaiting reply from Bob" in user
    assert "HANDLED" in user and "sent invoice to ACME" in user
    assert "Mahdi" in user


def test_horizon_widens_for_weekly(tmp_path):
    led = _ledger(tmp_path)
    led.add("two weeks out", due="2026-07-12", owner="me")
    daily = build_brief_prompt(led.entries(), [], today_iso="2026-06-30", name="", weekly=False, horizon_days=7)[1].content
    weekly = build_brief_prompt(led.entries(), [], today_iso="2026-06-30", name="", weekly=True, horizon_days=14)[1].content
    assert "two weeks out" not in daily
    assert "two weeks out" in weekly


def test_progress_and_timed_due_in_prompt(tmp_path):
    led = _ledger(tmp_path)
    c = led.add("Reply re: tender", due="2026-07-02T17:00", owner="me",
                steps=["Send reply", "Prepare File A"])
    led.set_step(c.id, text="Send reply", done=True)
    msgs = build_brief_prompt(
        led.entries(), [], today_iso="2026-06-30", name="", weekly=False, horizon_days=7,
    )
    user = msgs[1].content
    # Timed due classifies into the due-soon window, and progress is shown.
    assert "DUE SOON" in user and "Reply re: tender" in user
    assert "[1/2 done]" in user


def test_fallback_when_llm_fails(tmp_path):
    led = _ledger(tmp_path)
    led.add("important thing", due="2026-07-01", owner="me")
    llm = FakeLLM(boom=True)
    out = compose_brief(llm, led.entries(), [], today_iso="2026-06-30")
    assert "important thing" in out


# --- activity log ---------------------------------------------------------


def test_activity_record_and_filter(tmp_path):
    log = ActivityLog(tmp_path)
    log.record("sent reply to Sara", on="2026-06-30")
    log.record("saved a draft", on="2026-06-29")
    assert log.on_day("2026-06-30") == ["sent reply to Sara"]
    assert set(log.since("2026-06-29")) == {"sent reply to Sara", "saved a draft"}
    assert log.since("2026-07-01") == []


def test_activity_persists_and_bounded(tmp_path):
    log = ActivityLog(tmp_path)
    for i in range(250):
        log.record(f"action {i}", on="2026-06-30")
    reloaded = ActivityLog(tmp_path)
    handled = reloaded.on_day("2026-06-30")
    assert len(handled) == 200
    assert "action 249" in handled and "action 0" not in handled
