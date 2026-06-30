from datetime import date

from aurora.ledger.store import Commitment, LedgerStore


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
