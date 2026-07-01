"""Tool that lets Aurora save a recurring workflow as a reusable playbook.

``propose_playbook`` is an *action* tool: like ``propose_commitment`` it has no
handler and short-circuits the agent loop so the surface can show the user a
confirm card (Aurora never saves a playbook silently — correct-and-remember, D3).
Aurora calls it when she notices the user handle a repeatable process worth
templating, so next time she proposes the right definition-of-done steps.

Playbooks are also managed by hand via the ``/playbook`` command and by editing
``data/playbook/playbooks.md`` directly; reading them needs no tool because the
store is rendered into the system prompt each turn.
"""

from __future__ import annotations

from aurora.agent import ToolSpec


def build_playbook_tools() -> list[ToolSpec]:
    """The (single) action tool for teaching Aurora a new workflow playbook."""
    return [
        ToolSpec(
            name="propose_playbook",
            is_action=True,
            schema={
                "type": "function",
                "function": {
                    "name": "propose_playbook",
                    "description": (
                        "Offer to save a RECURRING workflow as a reusable playbook — a named "
                        "set of definition-of-done steps you'll reuse whenever a similar task "
                        "comes up. Use this when the user handles (or teaches you) a repeatable "
                        "process, ESPECIALLY one whose real 'done' is non-obvious (e.g. a tax, "
                        "filing, or multi-party process where a receipt is only step one). Shows "
                        "the user a confirm card — you never save silently. Don't propose a "
                        "playbook for a one-off task, or one that already exists in the PLAYBOOKS "
                        "block (correct it with the same name instead)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Short kebab-case slug naming the workflow, e.g. 'withholding-tax'.",
                            },
                            "steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "The ordered definition-of-done steps, each a concrete sub-task. The final step should be the true completion (e.g. paying DJP), not merely a hand-off.",
                            },
                            "triggers": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Keywords/phrases that should match a future task to this playbook, e.g. ['bukti potong', 'PPh', 'withholding tax'].",
                            },
                            "notes": {
                                "type": "string",
                                "description": "One short line of guidance, e.g. what counts as truly done vs. just a step.",
                            },
                        },
                        "required": ["name", "steps"],
                    },
                },
            },
        ),
    ]


__all__ = ["build_playbook_tools"]
