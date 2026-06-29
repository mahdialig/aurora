from aurora.sources.registry import MailAccounts


class _FakeAccount:
    def __init__(self, label):
        self.label = label

    # MailAccount methods unused in these tests.


def test_resolve_named():
    accts = MailAccounts({"personal": _FakeAccount("personal"), "work": _FakeAccount("work")})
    resolved = accts.resolve("work")
    assert [name for name, _ in resolved] == ["work"]


def test_resolve_all_and_none():
    accts = MailAccounts({"personal": _FakeAccount("personal"), "work": _FakeAccount("work")})
    assert {name for name, _ in accts.resolve("all")} == {"personal", "work"}
    assert {name for name, _ in accts.resolve(None)} == {"personal", "work"}


def test_resolve_unknown_is_empty():
    accts = MailAccounts({"personal": _FakeAccount("personal")})
    assert accts.resolve("work") == []


def test_empty_registry():
    accts = MailAccounts({})
    assert accts.is_empty()
    assert accts.names() == []
    assert accts.resolve("all") == []
