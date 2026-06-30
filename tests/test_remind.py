from aurora.ledger.store import Commitment
from aurora.remind.nudge import plan_nudges
from aurora.remind.state import RemindState

TODAY = "2026-06-30"


def _c(cid, text, **kw):
    return Commitment(id=cid, text=text, **kw)


def test_overdue_due_today_due_tomorrow():
    items = [
        _c("c1", "Pay invoice", due="2026-06-25"),       # overdue
        _c("c2", "Call bank", due="2026-06-30"),         # today
        _c("c3", "Send deck", due="2026-07-01"),         # tomorrow
        _c("c4", "File taxes", due="2026-07-20"),        # further out → no nudge
    ]
    nudges = plan_nudges(items, TODAY)
    by_id = {n.commitment_id: n for n in nudges}
    assert by_id["c1"].kind == "overdue"
    assert by_id["c2"].kind == "due_today"
    assert by_id["c3"].kind == "due_tomorrow"
    assert "c4" not in by_id


def test_stale_waiting_and_progress_checkins():
    items = [
        _c("c1", "Hear back from Sara", owner="other", created="2026-06-20", updated="2026-06-20"),
        _c("c2", "Draft the proposal", owner="me", created="2026-06-20", updated="2026-06-20"),
    ]
    nudges = plan_nudges(items, TODAY, stale_days=3)
    kinds = {n.commitment_id: n.kind for n in nudges}
    assert kinds == {"c1": "waiting", "c2": "progress"}
    assert all(n.is_checkin for n in nudges)


def test_fresh_undated_item_no_checkin():
    items = [_c("c1", "Just added", owner="me", created="2026-06-29", updated="2026-06-29")]
    assert plan_nudges(items, TODAY, stale_days=3) == []


def test_checkin_rate_limited_by_last_checkin():
    items = [_c("c1", "Old loop", owner="me", created="2026-06-01", updated="2026-06-01")]
    # Checked in yesterday → still within the window → suppressed.
    assert plan_nudges(items, TODAY, stale_days=3, last_checkin={"c1": "2026-06-29"}) == []
    # Checked in a week ago → window elapsed → check in again.
    again = plan_nudges(items, TODAY, stale_days=3, last_checkin={"c1": "2026-06-22"})
    assert [n.kind for n in again] == ["progress"]


def test_done_items_skipped():
    items = [_c("c1", "Finished", due="2026-06-25", status="done")]
    assert plan_nudges(items, TODAY) == []


def test_undated_no_dates_skipped():
    # Hand-added line with no created/updated → can't judge staleness → no nudge.
    items = [_c("c1", "mystery task", owner="me")]
    assert plan_nudges(items, TODAY, stale_days=3) == []


def test_remind_state_round_trip(tmp_path):
    st = RemindState(tmp_path)
    assert st.last_checkin("c1") == ""
    st.mark_checkin("c1", TODAY)
    assert RemindState(tmp_path).last_checkin("c1") == TODAY
    assert RemindState(tmp_path).as_dict() == {"c1": TODAY}


def test_remind_state_prune(tmp_path):
    st = RemindState(tmp_path)
    st.mark_checkin("c1", TODAY)
    st.mark_checkin("c2", TODAY)
    st.prune({"c1"})  # c2 no longer exists
    assert st.last_checkin("c2") == ""
    assert st.last_checkin("c1") == TODAY
