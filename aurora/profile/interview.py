"""The /onboard interview — the proven week-1 EA questions.

A short, staged interview that seeds the :class:`~aurora.profile.store.ProfileStore`.
Each question maps to a real lever Aurora already pulls (how she greets, when she
interrupts, what she pings about, the voice she drafts email in, what she escalates),
so answers change her behavior the same day.

The question set is grounded in how a good executive assistant / PA learns their
principal in the first week: how to address them and their rhythm, channels and
urgency, the principal's email voice, what to handle vs. escalate, who always gets
through, and the real-time notification threshold.

``options`` are preset tap-buttons; free-text is always allowed (and lightly
distilled into a clean preference line by :func:`distill`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aurora.llm.client import Message

logger = logging.getLogger("aurora.profile")


@dataclass(frozen=True)
class Question:
    """One interview question and its preset answers."""

    key: str                                    # ProfileField key it writes to
    label: str                                  # what Aurora asks
    options: tuple[tuple[str, str], ...] = ()   # (button label, canonical value)
    hint: str = ""                              # extra line under the question
    optional: bool = False                      # the "nice to have" tail


# The recommended week-1 set: 8 core, then 2 optional so it never becomes a slog.
QUESTIONS: list[Question] = [
    Question(
        key="preferred_name",
        label="What should I call you?",
        hint="(Tap your name if it's there, or just type it.)",
    ),
    Question(
        key="work_hours",
        label="What are your usual working hours, and when are you at your best?",
        options=(
            ("Early bird (mornings)", "Sharpest in the mornings"),
            ("Standard 9–6", "Works roughly 9am–6pm"),
            ("Night owl (evenings)", "Sharpest in the evenings"),
            ("Flexible / varies", "Flexible hours, varies day to day"),
        ),
    ),
    Question(
        key="dnd",
        label="When should I *not* interrupt you?",
        options=(
            ("After hours", "Don't interrupt outside working hours"),
            ("Weekends", "Don't interrupt on weekends"),
            ("Focus mornings", "Keep mornings interruption-free for focus"),
            ("Anytime is fine", "Fine to interrupt anytime"),
        ),
    ),
    Question(
        key="notify_threshold",
        label="What's worth pinging you about the moment it lands?",
        options=(
            ("Money & key people", "Ping right away for money and key people; hold the rest"),
            ("Only if I must act", "Ping only when something genuinely needs my action"),
            ("Any real human", "Ping for anything from a real person; skip automated mail"),
            ("Almost nothing", "Rarely ping live; save it for the daily brief"),
        ),
    ),
    Question(
        key="vips",
        label="Whose messages should *always* get through to me?",
        hint="(Names or email addresses — type as many as you like, or Skip.)",
    ),
    Question(
        key="reply_tone",
        label="When I draft email as you, what tone should I use?",
        options=(
            ("Warm", "Warm and friendly"),
            ("Neutral", "Neutral and professional"),
            ("Direct & concise", "Direct and concise"),
            ("Formal", "Formal and polished"),
        ),
    ),
    Question(
        key="reply_length",
        label="Default length for the email replies I draft?",
        options=(
            ("One-liner", "One or two lines — as short as possible"),
            ("Short", "Short — a few sentences"),
            ("Thorough", "Thorough when the topic needs it"),
        ),
    ),
    Question(
        key="signature",
        label="How should I sign off your emails?",
        hint="(e.g. “Best, Mahdi” — type it, or Skip to use none.)",
    ),
    Question(
        key="handle_vs_check",
        label="What should I just handle on my own vs. always check with you first?",
        hint="(Type a sentence or two, or Skip.)",
        optional=True,
    ),
    Question(
        key="off_my_plate",
        label="What do you most want off your plate?",
        hint="(Type whatever comes to mind, or Skip.)",
        optional=True,
    ),
]


_DISTILL_SYSTEM = (
    "You turn a user's free-text answer to a setup question into ONE short, clean "
    "preference value Aurora (their assistant) can store and act on. Keep the user's "
    "meaning exactly; drop filler and preamble. Write it as a concise phrase or short "
    "sentence — NOT a question, NOT 'You prefer…', just the value itself. No quotes, "
    "no trailing punctuation unless it's a list. Reply with ONLY the value."
)


def distill(llm, question: "Question", raw: str) -> str:
    """Tidy a free-text answer into a clean preference value.

    Mirrors ``brief.compose``: one light LLM call, and on ANY failure fall back to
    the user's raw text — onboarding must never break because the model hiccuped.
    """
    raw = raw.strip()
    if not raw:
        return raw
    try:
        messages = [
            Message("system", _DISTILL_SYSTEM),
            Message("user", f"Question: {question.label}\nUser's answer: {raw}"),
        ]
        out = llm.complete(messages, temperature=0.2).strip()
        return out or raw
    except Exception:  # noqa: BLE001 - never let distillation break the interview
        logger.exception("Onboarding distill failed; keeping raw answer.")
        return raw


__all__ = ["Question", "QUESTIONS", "distill"]
