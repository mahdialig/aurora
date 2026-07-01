from datetime import date

from aurora.playbook.store import Playbook, PlaybookStore

_STEPS = [
    "Prepare the bukti potong",
    "Send the bukti potong to the counterparty",
    "Pay DJP and keep the payment proof",
]


def test_set_and_roundtrip(tmp_path):
    pb = PlaybookStore(tmp_path)
    p = pb.set(
        "withholding-tax",
        steps=_STEPS,
        triggers=["bukti potong", "PPh"],
        notes="Receipt is not done — paying DJP is.",
    )
    assert p.name == "withholding-tax"
    assert p.steps == tuple(_STEPS)
    assert p.on == date.today().isoformat()
    # Round-trips through the file.
    reloaded = PlaybookStore(tmp_path).playbooks()
    assert len(reloaded) == 1
    r = reloaded[0]
    assert r.name == "withholding-tax"
    assert r.steps == tuple(_STEPS)
    assert r.triggers == ("bukti potong", "PPh")
    assert r.notes == "Receipt is not done — paying DJP is."


def test_set_upserts_by_name_no_duplicate(tmp_path):
    pb = PlaybookStore(tmp_path)
    pb.set("withholding-tax", steps=["a", "b"])
    pb.set("withholding-tax", steps=_STEPS)  # correction replaces in place
    items = pb.playbooks()
    assert len(items) == 1
    assert items[0].steps == tuple(_STEPS)


def test_set_preserves_other_playbooks(tmp_path):
    pb = PlaybookStore(tmp_path)
    pb.set("withholding-tax", steps=_STEPS)
    pb.set("send-invoice", steps=["Draft invoice", "Email it", "Log in finance sheet"])
    assert set(pb.names()) == {"withholding-tax", "send-invoice"}


def test_empty_steps_rejected(tmp_path):
    pb = PlaybookStore(tmp_path)
    try:
        pb.set("bad", steps=["   "])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a playbook with no real steps")
    assert pb.is_empty()


def test_remove_reverts(tmp_path):
    pb = PlaybookStore(tmp_path)
    pb.set("withholding-tax", steps=_STEPS)
    removed = pb.remove("withholding-tax")
    assert removed is not None and removed.name == "withholding-tax"
    assert pb.is_empty()
    assert pb.remove("withholding-tax") is None  # already gone


def test_match_by_trigger_and_name(tmp_path):
    pb = PlaybookStore(tmp_path)
    pb.set("withholding-tax", steps=_STEPS, triggers=["bukti potong", "PPh"])
    assert pb.match("I need to handle the bukti potong for vOffice").name == "withholding-tax"
    assert pb.match("sort out withholding tax").name == "withholding-tax"  # name (hyphen→space)
    assert pb.match("reply to the tender email") is None
    assert pb.match("") is None


def test_render_empty_nudges_to_teach(tmp_path):
    block = PlaybookStore(tmp_path).render_for_prompt()
    assert "PLAYBOOKS" in block
    assert "propose_playbook" in block


def test_render_lists_steps(tmp_path):
    pb = PlaybookStore(tmp_path)
    pb.set("withholding-tax", steps=_STEPS, triggers=["bukti potong"], notes="Pay DJP is the real done.")
    block = pb.render_for_prompt()
    assert "withholding-tax" in block
    assert "Pay DJP and keep the payment proof" in block
    assert "bukti potong" in block
    assert "Pay DJP is the real done." in block


def test_hand_edited_file_tolerated(tmp_path):
    # A user writes a playbook by hand, minimal form (no provenance, no trigger/notes).
    path = tmp_path / "playbook" / "playbooks.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Aurora's playbooks — step templates for recurring workflows\n\n"
        "## onboarding-vendor\n"
        "- Collect their NPWP\n"
        "- Add them to the finance sheet\n",
        encoding="utf-8",
    )
    items = PlaybookStore(tmp_path).playbooks()
    assert len(items) == 1
    assert items[0].name == "onboarding-vendor"
    assert items[0].steps == ("Collect their NPWP", "Add them to the finance sheet")
    assert items[0].triggers == ()


def test_to_lines_shape():
    p = Playbook(name="x", steps=("s1", "s2"), triggers=("t1",), notes="n", on="2026-07-01", source="you told me")
    lines = p.to_lines()
    assert lines[0] == "## x · on:2026-07-01 src:you told me"
    assert "trigger: t1" in lines
    assert "- s1" in lines and "- s2" in lines
    assert "notes: n" in lines
