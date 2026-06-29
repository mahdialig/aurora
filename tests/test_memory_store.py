from aurora.memory import MemoryStore


def test_empty_store(tmp_path):
    store = MemoryStore(tmp_path)
    assert store.entries() == []
    assert store.is_empty()
    assert store.display_name() is None
    # Empty render still nudges Aurora to learn about the user.
    assert "don't know" in store.render_for_prompt().lower()


def test_add_and_read(tmp_path):
    store = MemoryStore(tmp_path)
    entry = store.add("I prefer concise replies.")
    assert entry.text == "I prefer concise replies."
    assert entry.on  # today's date stamped
    assert entry.source == "you told me"

    items = store.entries()
    assert [e.text for e in items] == ["I prefer concise replies."]
    assert not store.is_empty()


def test_add_rejects_empty(tmp_path):
    store = MemoryStore(tmp_path)
    try:
        store.add("   ")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on empty memory")


def test_persistence_across_instances(tmp_path):
    MemoryStore(tmp_path).add("I'm Mahdi, a startup founder.")
    # A brand-new instance over the same dir must see the saved memory.
    reopened = MemoryStore(tmp_path)
    assert [e.text for e in reopened.entries()] == ["I'm Mahdi, a startup founder."]


def test_render_includes_entries(tmp_path):
    store = MemoryStore(tmp_path)
    store.add("Keep replies short.")
    rendered = store.render_for_prompt()
    assert "Keep replies short." in rendered
    assert "MEMORY" in rendered


def test_forget_by_index(tmp_path):
    store = MemoryStore(tmp_path)
    store.add("first")
    store.add("second")
    removed = store.forget(1)
    assert removed is not None and removed.text == "first"
    assert [e.text for e in store.entries()] == ["second"]


def test_forget_by_substring(tmp_path):
    store = MemoryStore(tmp_path)
    store.add("I like tea")
    store.add("I dislike spam")
    removed = store.forget("spam")
    assert removed is not None and removed.text == "I dislike spam"
    assert [e.text for e in store.entries()] == ["I like tea"]


def test_forget_no_match(tmp_path):
    store = MemoryStore(tmp_path)
    store.add("only entry")
    assert store.forget("nonexistent") is None
    assert store.forget(99) is None
    assert len(store.entries()) == 1


def test_display_name_detection(tmp_path):
    store = MemoryStore(tmp_path)
    store.add("I'm Mahdi, a founder.")
    assert store.display_name() == "Mahdi"


def test_display_name_skips_stopwords(tmp_path):
    store = MemoryStore(tmp_path)
    store.add("I'm a founder and currently busy.")
    # "a" is a stopword, so no false-positive name.
    assert store.display_name() is None


def test_hand_edited_plain_bullet_is_read(tmp_path):
    # A line without [date]/(source), as a human might type directly into the file.
    path = tmp_path / "memory" / "memory.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Aurora's memory of the user\n\n- I work in Europe/Brussels time.\n", encoding="utf-8")
    store = MemoryStore(tmp_path)
    assert [e.text for e in store.entries()] == ["I work in Europe/Brussels time."]
