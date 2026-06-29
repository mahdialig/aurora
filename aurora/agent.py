"""The agent loop — Aurora's reasoning core.

Given a conversation and a set of tools, run the LLM in a tool-use loop:
read-only tools execute immediately and feed their results back; the first
*action* tool short-circuits (it is NOT executed) so the surface can ask the
user to approve it. This keeps "approve-before-acting" intact while letting
Aurora freely read/search to answer.

Surface-agnostic and provider-agnostic: it only needs an ``LLMClient.chat`` and
a list of :class:`ToolSpec`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("aurora.agent")


@dataclass
class ToolSpec:
    """A tool the agent can call.

    ``schema`` is the OpenAI function spec. ``handler`` runs a read-only tool and
    returns a string result. Action tools (``is_action=True``) have no handler —
    the loop returns them for user approval instead of executing.
    """

    name: str
    schema: dict
    handler: Callable[[dict], str] | None = None
    is_action: bool = False


@dataclass
class AgentResult:
    """Either a spoken reply, or an action awaiting the user's approval."""

    text: str | None = None
    action_name: str | None = None
    action_args: dict | None = None

    @property
    def is_action(self) -> bool:
        return self.action_name is not None


def _parse_args(call: dict) -> dict:
    raw = (call.get("function") or {}).get("arguments") or "{}"
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def run_agent(llm, messages: list[dict], tools: list[ToolSpec], max_steps: int = 6) -> AgentResult:
    """Drive the LLM tool-use loop. ``messages`` is mutated with intermediate steps."""
    specs = [t.schema for t in tools]
    by_name = {t.name: t for t in tools}

    for _ in range(max_steps):
        msg = llm.chat(messages, tools=specs if specs else None)
        tool_calls = msg.get("tool_calls")

        if not tool_calls:
            return AgentResult(text=(msg.get("content") or "").strip())

        # Per the OpenAI protocol, the assistant message (with tool_calls) must be
        # in the history before the matching tool results.
        messages.append(msg)

        for call in tool_calls:
            name = (call.get("function") or {}).get("name", "")
            args = _parse_args(call)
            tool = by_name.get(name)

            if tool is None:
                result = f"(unknown tool: {name})"
            elif tool.is_action:
                # Short-circuit: do not execute — hand back for approval.
                return AgentResult(action_name=name, action_args=args)
            else:
                try:
                    result = tool.handler(args) if tool.handler else "(no handler)"
                except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
                    logger.exception("Tool %s failed", name)
                    result = f"(error running {name}: {exc})"

            messages.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}
            )

    # Out of tool-use steps: force a final natural-language answer (no tools) so
    # Aurora reports what she did/didn't find instead of dead-ending.
    try:
        final = llm.chat(messages)
        text = (final.get("content") or "").strip()
        if text:
            return AgentResult(text=text)
    except Exception:  # noqa: BLE001
        logger.exception("Final agent answer failed")
    return AgentResult(text="(I looked but couldn't pin that down — could you rephrase?)")
