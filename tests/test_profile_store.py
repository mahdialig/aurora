from datetime import date

from aurora.profile.store import ProfileField, ProfileStore


def test_set_and_roundtrip(tmp_path):
    prof = ProfileStore(tmp_path)
    f = prof.set("reply_tone", "Direct and concise")
    assert f.key == "reply_tone"
    assert f.value == "Direct and concise"
    assert f.on == date.today().isoformat()
    assert f.source == "onboarding"
    # Round-trips through the file (value may contain spaces).
    reloaded = ProfileStore(tmp_path).fields()
    assert len(reloaded) == 1
    assert reloaded[0].key == "reply_tone"
    assert reloaded[0].value == "Direct and concise"


def test_set_upserts_by_key_no_duplicate(tmp_path):
    prof = ProfileStore(tmp_path)
    prof.set("reply_tone", "Warm")
    prof.set("reply_tone", "Formal")
    fields = prof.fields()
    assert len(fields) == 1
    assert fields[0].value == "Formal"


def test_set_preserves_other_keys(tmp_path):
    prof = ProfileStore(tmp_path)
    prof.set("preferred_name", "Aji")
    prof.set("reply_tone", "Warm")
    prof.set("reply_tone", "Direct and concise")
    by_key = {f.key: f.value for f in prof.fields()}
    assert by_key == {"preferred_name": "Aji", "reply_tone": "Direct and concise"}


def test_get(tmp_path):
    prof = ProfileStore(tmp_path)
    assert prof.get("vips") is None
    prof.set("vips", "Sara, the boss")
    got = prof.get("vips")
    assert got is not None
    assert got.value == "Sara, the boss"


def test_remove_truly_reverts(tmp_path):
    prof = ProfileStore(tmp_path)
    prof.set("reply_tone", "Formal")
    removed = prof.remove("reply_tone")
    assert removed is not None
    assert removed.key == "reply_tone"
    # Gone from the file, not just from memory.
    assert ProfileStore(tmp_path).get("reply_tone") is None
    assert prof.is_empty()


def test_remove_unknown_key(tmp_path):
    prof = ProfileStore(tmp_path)
    prof.set("reply_tone", "Warm")
    assert prof.remove("nope") is None
    assert len(prof.fields()) == 1


def test_empty_value_rejected(tmp_path):
    prof = ProfileStore(tmp_path)
    for bad in ("", "   "):
        try:
            prof.set("reply_tone", bad)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected ValueError on empty value")
    assert prof.is_empty()


def test_render_for_prompt_empty_and_filled(tmp_path):
    prof = ProfileStore(tmp_path)
    empty = prof.render_for_prompt()
    assert "PROFILE" in empty
    assert "/onboard" in empty

    prof.set("reply_tone", "Direct and concise")
    prof.set("preferred_name", "Aji")
    rendered = prof.render_for_prompt()
    assert "standing preferences" in rendered
    # Keys are humanized (underscores → spaces) and values shown.
    assert "- reply tone: Direct and concise" in rendered
    assert "- preferred name: Aji" in rendered


def test_tolerates_hand_edited_bare_line(tmp_path):
    prof = ProfileStore(tmp_path)
    prof.path.parent.mkdir(parents=True, exist_ok=True)
    # No "· on:/src:" provenance block — a line typed by hand.
    prof.path.write_text(
        "# Aurora's profile of the user\n\n- reply_tone: warm and chatty\n",
        encoding="utf-8",
    )
    fields = prof.fields()
    assert len(fields) == 1
    assert fields[0] == ProfileField(key="reply_tone", value="warm and chatty")


def test_skips_unparseable_lines(tmp_path):
    prof = ProfileStore(tmp_path)
    prof.path.parent.mkdir(parents=True, exist_ok=True)
    prof.path.write_text(
        "# Aurora's profile of the user\n\n"
        "- no_colon_here\n"          # missing ": value" → skipped
        "- reply_tone: warm\n"
        "not a bullet\n",
        encoding="utf-8",
    )
    fields = prof.fields()
    assert [f.key for f in fields] == ["reply_tone"]
