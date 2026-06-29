from aurora.surfaces.telegram import parse_remember_marker


def test_no_marker_returns_text_and_none():
    visible, fact = parse_remember_marker("Sure, here's a tip: take breaks.")
    assert visible == "Sure, here's a tip: take breaks."
    assert fact is None


def test_marker_is_stripped_and_fact_extracted():
    raw = "Nice, working late suits some people.\n[[REMEMBER: I usually work late at night]]"
    visible, fact = parse_remember_marker(raw)
    assert visible == "Nice, working late suits some people."
    assert fact == "I usually work late at night"


def test_marker_case_insensitive_and_inline():
    raw = "Got it [[remember: I'm based in Brussels]] — noted."
    visible, fact = parse_remember_marker(raw)
    assert fact == "I'm based in Brussels"
    assert "[[remember" not in visible.lower()


def test_empty_fact_treated_as_none():
    visible, fact = parse_remember_marker("Hello [[REMEMBER: ]]")
    assert fact is None
    assert visible == "Hello"
