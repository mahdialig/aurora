from datetime import date

from aurora.ledger.store import Commitment, LedgerStore, Step


def test_add_and_query(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("Reply to Sara", kind="reply", due="2026-07-03", source="email:personal:abc")
    assert c.id == "c1"
    assert c.kind == "reply"
    assert c.status == "open"
    assert c.created == date.today().isoformat()
    # Round-trips through the file.
    reloaded = LedgerStore(tmp_path).entries()
    assert len(reloaded) == 1
    assert reloaded[0].text == "Reply to Sara"
    assert reloaded[0].due == "2026-07-03"
    assert reloaded[0].source == "email:personal:abc"


def test_dedup_by_source(tmp_path):
    led = LedgerStore(tmp_path)
    first = led.add("Reply to Sara", source="email:personal:abc")
    again = led.add("Reply to Sara (dup)", source="email:personal:abc")
    assert again.id == first.id
    assert len(led.entries()) == 1


def test_generic_chat_source_does_not_dedup(tmp_path):
    """Regression: a generic source like 'chat' must NOT collapse onto the first
    chat item — only structured provenance keys (email:...) dedup."""
    led = LedgerStore(tmp_path)
    a = led.add("pay and send bukti potong to vOffice", source="chat")
    b = led.add("Remind Pak Indra about the NDA expiry", source="chat")
    assert a.id != b.id
    assert len(led.entries()) == 2
    # An empty source also never dedups.
    c = led.add("third unrelated thing", source="")
    assert len({a.id, b.id, c.id}) == 3


def test_ids_increment(tmp_path):
    led = LedgerStore(tmp_path)
    a = led.add("one")
    b = led.add("two")
    assert (a.id, b.id) == ("c1", "c2")


def test_update_and_mark_done(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("Quarterly report")
    upd = led.update(c.id, status="waiting", due="2026-07-10")
    assert upd is not None
    assert upd.status == "waiting"
    assert upd.due == "2026-07-10"
    done = led.mark_done(c.id)
    assert done.is_done
    # Done items excluded from the default query but kept in the file.
    assert led.query() == []
    assert len(led.entries()) == 1
    assert led.query(include_done=True)[0].is_done


def test_unknown_values_coerced(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("thing", kind="nonsense", owner="alien", status="weird")
    assert (c.kind, c.owner, c.status) == ("task", "me", "open")


def test_open_items_sorted_by_due(tmp_path):
    led = LedgerStore(tmp_path)
    led.add("no due")
    led.add("later", due="2026-08-01")
    led.add("sooner", due="2026-07-01")
    order = [c.text for c in led.open_items()]
    assert order == ["sooner", "later", "no due"]


def test_query_due_on_or_before(tmp_path):
    led = LedgerStore(tmp_path)
    led.add("soon", due="2026-07-01")
    led.add("far", due="2026-09-01")
    led.add("undated")
    due_soon = led.query(due_on_or_before="2026-07-15")
    assert [c.text for c in due_soon] == ["soon"]


def test_remove(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("temp")
    assert led.remove(c.id) is not None
    assert led.entries() == []
    assert led.remove("c999") is None


def test_hand_added_line_loads_and_gets_id(tmp_path):
    path = tmp_path / "ledger" / "commitments.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Aurora's commitments ledger\n\n- call the dentist\n", encoding="utf-8")
    led = LedgerStore(tmp_path)
    items = led.entries()
    assert len(items) == 1
    assert items[0].text == "call the dentist"
    assert items[0].id == "c1"
    assert items[0].status == "open"


def test_prune_done(tmp_path):
    led = LedgerStore(tmp_path)
    ids = [led.add(f"task {i}").id for i in range(5)]
    for cid in ids:
        led.mark_done(cid)
    removed = led.prune_done(keep=2)
    assert removed == 3
    assert len(led.entries()) == 2


def test_render_for_prompt(tmp_path):
    led = LedgerStore(tmp_path)
    assert "No open commitments" in led.render_for_prompt()
    led.add("Reply to Sara", kind="reply", due="2026-07-03")
    rendered = led.render_for_prompt()
    assert "Reply to Sara" in rendered
    assert "due 2026-07-03" in rendered
    assert "(c1)" in rendered


def test_atomic_write_leaves_no_tmp(tmp_path):
    led = LedgerStore(tmp_path)
    led.add("thing")
    assert not (led.path.parent / "commitments.md.tmp").exists()


def test_to_line_round_trip():
    c = Commitment(
        id="c7", text="Do the thing", kind="deadline", owner="me",
        status="waiting", due="2026-07-09", source="chat",
        created="2026-06-30", updated="2026-06-30",
    )
    line = c.to_line()
    assert line.startswith("- Do the thing · ")
    assert "id:c7" in line and "kind:deadline" in line and "status:waiting" in line


# --- slice α: checklists, remind, due-with-time ----------------------------


def test_flat_item_unchanged(tmp_path):
    """0-step item behaves exactly as before: is_done follows the status flag."""
    led = LedgerStore(tmp_path)
    c = led.add("call the dentist")
    assert c.steps == ()
    assert c.progress is None
    assert not c.is_done
    led.mark_done(c.id)
    assert led.get(c.id).is_done


def test_steps_round_trip(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("Reply re: tender", kind="reply", steps=["Send the reply", "Prepare File A", "Prepare File B"])
    assert [s.text for s in c.steps] == ["Send the reply", "Prepare File A", "Prepare File B"]
    assert all(not s.done for s in c.steps)
    assert c.progress == (0, 3)
    # Round-trips through the markdown file (parent line + child task-list lines).
    reloaded = LedgerStore(tmp_path).get(c.id)
    assert [s.text for s in reloaded.steps] == ["Send the reply", "Prepare File A", "Prepare File B"]
    # The child lines are GitHub-style and hand-editable.
    text = (tmp_path / "ledger" / "commitments.md").read_text(encoding="utf-8")
    assert "  - [ ] Send the reply" in text


def test_is_done_from_steps_and_auto_complete(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("Two-parter", steps=["A", "B"])
    assert not c.is_done
    led.set_step(c.id, text="A", done=True)
    mid = led.get(c.id)
    assert mid.progress == (1, 2) and not mid.is_done and mid.status != "done"
    led.set_step(c.id, index=1, done=True)
    last = led.get(c.id)
    assert last.is_done and last.status == "done"  # last step auto-completes the parent


def test_open_steps(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("Task", steps=["A", "B"])
    led.set_step(c.id, text="A", done=True)
    assert [s.text for s in led.open_steps(c.id)] == ["B"]
    assert led.open_steps("c999") == []
    flat = led.add("flat")
    assert led.open_steps(flat.id) == []  # no checklist → nothing to guard


def test_mark_done_ticks_all_steps(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("Task", steps=["A", "B"])
    led.mark_done(c.id)
    done = led.get(c.id)
    assert done.is_done and all(s.done for s in done.steps)


def test_remind_default_on_and_optout_serialization(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("watched")
    assert c.remind is True  # default on (no regression for existing items)
    text = (tmp_path / "ledger" / "commitments.md").read_text(encoding="utf-8")
    assert "remind:off" not in text  # default-on is omitted from the line
    led.update(c.id, remind=False)
    assert led.get(c.id).remind is False
    assert "remind:off" in (tmp_path / "ledger" / "commitments.md").read_text(encoding="utf-8")
    # And it round-trips back to False.
    assert LedgerStore(tmp_path).get(c.id).remind is False


def test_due_with_time_round_trip_and_query(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("timed", due="2026-07-03T17:00")
    assert led.get(c.id).due == "2026-07-03T17:00"
    # due_on_or_before compares on the date portion, so a timed due on the boundary day matches.
    hits = led.query(due_on_or_before="2026-07-03")
    assert [x.id for x in hits] == [c.id]


def test_hand_edited_checklist_loads(tmp_path):
    path = tmp_path / "ledger" / "commitments.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Aurora's commitments ledger\n\n"
        "- Reply re: tender · kind:reply owner:me status:open id:c1\n"
        "  - [x] Send the reply\n"
        "  - [ ] Prepare File A\n",
        encoding="utf-8",
    )
    c = LedgerStore(path.parent.parent).get("c1")
    assert c.progress == (1, 2)
    assert [s.done for s in c.steps] == [True, False]


def test_step_helper_drops_blanks_and_collapses_single():
    from aurora.ledger.store import _as_steps
    assert _as_steps(["A", "  ", "B"]) == (Step("A"), Step("B"))
    assert _as_steps(None) == ()
    # A checklist needs ≥2 items — 0 or 1 collapses to a flat task.
    assert _as_steps([Step("X", done=True)]) == ()
    assert _as_steps(["only one"]) == ()
    assert _as_steps(["one", "  "]) == ()  # blanks dropped first, then collapsed


def test_single_step_add_is_flat(tmp_path):
    led = LedgerStore(tmp_path)
    c = led.add("Remind Pak Indra about the NDA expiry", steps=["Remind Pak Indra about the NDA expiry"])
    assert c.steps == ()  # no redundant one-item checklist
    assert c.progress is None
    # Two distinct steps are kept.
    d = led.add("Reply re: tender", steps=["Send the reply", "Prepare File A"])
    assert len(d.steps) == 2
