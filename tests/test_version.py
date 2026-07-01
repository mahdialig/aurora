import aurora
from aurora.surfaces.telegram import _version_text


def test_package_exposes_release_identity():
    assert aurora.__version__
    assert aurora.__codename__
    assert aurora.__release_note__


def test_version_text_includes_version_codename_and_build():
    text = _version_text("0.6.0", "Playbooks", "Procedural playbooks.", "abc1234")
    assert "0.6.0" in text
    assert "Playbooks" in text
    assert "Procedural playbooks." in text
    assert "abc1234" in text


def test_version_text_without_sha_omits_build_line():
    text = _version_text("0.6.0", "Playbooks", "note", "")
    assert "build:" not in text
    assert "0.6.0" in text
