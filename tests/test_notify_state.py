from aurora.notify.state import NotifyState


def test_first_contact_then_seen(tmp_path):
    st = NotifyState(tmp_path)
    assert st.is_first_contact("work")
    st.mark_seen("work", ["1", "2"])
    assert not st.is_first_contact("work")
    # Already-seen filtered out; new ones returned.
    assert st.unseen("work", ["1", "2", "3"]) == ["3"]


def test_unseen_preserves_order():
    st = NotifyState.__new__(NotifyState)  # no file needed
    st._seen = {"a": ["2"]}
    assert st.unseen("a", ["3", "2", "1"]) == ["3", "1"]


def test_persists_across_restart(tmp_path):
    NotifyState(tmp_path).mark_seen("personal", ["x", "y"])
    reloaded = NotifyState(tmp_path)
    assert not reloaded.is_first_contact("personal")
    assert reloaded.unseen("personal", ["x", "y", "z"]) == ["z"]


def test_bounded_growth(tmp_path):
    st = NotifyState(tmp_path)
    st.mark_seen("work", [str(i) for i in range(600)])
    stored = st._seen["work"]
    assert len(stored) == 500
    # Oldest dropped, newest kept.
    assert "599" in stored and "0" not in stored
