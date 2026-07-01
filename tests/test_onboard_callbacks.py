"""The onboarding callback parser + its stale-card guard.

Buttons carry the question index they were issued for, so a tap on a leftover
card from an earlier question is detected and ignored rather than saving the
answer under the wrong key (which once mis-filed a sign-off answer).
"""

from aurora.surfaces.telegram import _parse_onb_action


def test_pick_carries_question_and_option_index():
    assert _parse_onb_action("onb:pick:7:2") == ("pick", 7, 2)


def test_confirm_and_question_actions_carry_question_index():
    assert _parse_onb_action("onb:save:7") == ("save", 7, None)
    assert _parse_onb_action("onb:edit:3") == ("edit", 3, None)
    assert _parse_onb_action("onb:skip:5") == ("skip", 5, None)
    assert _parse_onb_action("onb:stop:0") == ("stop", 0, None)


def test_start_menu_has_no_question_index():
    # The pre-interview menu (rerun/review/cancel) isn't tied to a question.
    assert _parse_onb_action("onb:start:rerun") == ("start", None, None)


def test_old_format_callbacks_degrade_to_none_index():
    # A callback minted before this hardening (no index) parses without an index,
    # so the guard treats it as "no claim" rather than crashing.
    assert _parse_onb_action("onb:save") == ("save", None, None)
    assert _parse_onb_action("onb:pick:2") == ("pick", 2, None)


def test_stale_tap_is_detectable():
    # A save button from question 6 tapped while the interview is on question 7:
    # the parsed index differs from the current one, so the handler can reject it.
    _action, qidx, _opt = _parse_onb_action("onb:save:6")
    current_idx = 7
    assert qidx is not None and qidx != current_idx
