"""Tools for teaching Aurora what to notify about.

When the user reacts to a proactive notification ("don't notify me about these",
"that was important", or answering her "is this important?" question), the agent
calls ``set_notification_rule`` to persist the lesson. It writes straight to memory
(no Remember-button) because the user gave an explicit instruction — and because the
classifier reads memory, the rule takes effect on the very next poll.
"""

from __future__ import annotations

import json

from aurora.agent import ToolSpec
from aurora.memory.store import MemoryStore


def build_notify_tools(memory: MemoryStore) -> list[ToolSpec]:
    """Inline tools (bound to the memory store) for notification preferences."""

    def set_notification_rule(args: dict) -> str:
        rule = (args.get("rule") or "").strip()
        if not rule:
            return json.dumps({"error": "rule is required"})
        kind = (args.get("kind") or "").strip().lower()
        prefix = {"mute": "don't notify me about", "prioritize": "always flag"}.get(kind)
        text = f"For email notifications: {rule}"
        if prefix and prefix not in rule.lower():
            text = f"For email notifications, {prefix}: {rule}"
        entry = memory.add(text)
        return json.dumps({"saved": entry.text})

    return [
        ToolSpec(
            name="set_notification_rule",
            handler=set_notification_rule,
            schema={
                "type": "function",
                "function": {
                    "name": "set_notification_rule",
                    "description": (
                        "Remember how the user wants to be notified about email, based on their "
                        "reaction to a notification. Call this when they say things like 'don't "
                        "notify me about newsletters', 'this kind of email is important', or answer "
                        "your 'is this important?' question. The rule takes effect immediately. "
                        "After calling it, confirm naturally in one short line."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rule": {
                                "type": "string",
                                "description": "The preference in the user's terms, e.g. 'promotional emails from shops' or 'anything from my bank'.",
                            },
                            "kind": {
                                "type": "string",
                                "description": "'mute' to stop flagging these, or 'prioritize' to always flag them.",
                            },
                        },
                        "required": ["rule", "kind"],
                    },
                },
            },
        ),
    ]
