"""Tools that let Aurora track the user's open loops conversationally.

The commitments ledger (``data/ledger/commitments.md``) is Aurora's "don't-miss-a-
thing" source of truth. These are inline ``handler`` tools (like ``set_notification_
rule``) — NOT approval-gated, because they change internal tracking state, not
anything that leaves the user's mailbox. Aurora calls them when the user mentions
something they owe, await, or must do by a date, and to update or close items.
"""

from __future__ import annotations

import json

from aurora.agent import ToolSpec
from aurora.ledger.store import KINDS, STATUSES, LedgerStore


def build_ledger_tools(ledger: LedgerStore) -> list[ToolSpec]:
    """Inline tools (bound to the ledger) for tracking commitments.

    ``propose_commitment`` and ``suggest_step_done`` are *action* tools: like
    ``reply_to_email`` they have no handler and short-circuit the agent loop so the
    surface can show the user an approval / confirmation card. The rest run inline."""

    def list_commitments(args: dict) -> str:
        status = (args.get("status") or "").strip().lower() or None
        owner = (args.get("owner") or "").strip().lower() or None
        items = ledger.query(status=status, owner=owner) if (status or owner) else ledger.open_items()
        out = [
            {"id": c.id, "text": c.text, "kind": c.kind, "owner": c.owner,
             "status": c.status, "due": c.due}
            for c in items
        ]
        return json.dumps({"commitments": out})

    def update_commitment(args: dict) -> str:
        cid = (args.get("id") or "").strip()
        if not cid:
            return json.dumps({"error": "id is required"})
        changes = {k: args.get(k) for k in ("text", "kind", "owner", "status", "due") if args.get(k)}
        updated = ledger.update(cid, **changes)
        if updated is None:
            return json.dumps({"error": f"no commitment with id {cid}"})
        return json.dumps({"updated": {"id": updated.id, "text": updated.text, "status": updated.status, "due": updated.due}})

    def mark_done(args: dict) -> str:
        cid = (args.get("id") or "").strip()
        if not cid:
            return json.dumps({"error": "id is required"})
        force = bool(args.get("force"))
        open_steps = ledger.open_steps(cid)
        if open_steps and not force:
            # Guard: don't silently close an item whose checklist isn't finished.
            # Name what's open so Aurora can confirm with the user (D20/D21).
            return json.dumps({
                "needs_confirmation": True,
                "id": cid,
                "open_steps": [s.text for s in open_steps],
                "hint": "Steps remain. Tick them off (suggest_step_done), or call mark_done again with force:true once the user confirms the whole thing is truly done.",
            })
        done = ledger.mark_done(cid)
        if done is None:
            return json.dumps({"error": f"no commitment with id {cid}"})
        return json.dumps({"done": {"id": done.id, "text": done.text}})

    return [
        ToolSpec(
            name="propose_commitment",
            is_action=True,
            schema={
                "type": "function",
                "function": {
                    "name": "propose_commitment",
                    "description": (
                        "Propose tracking an open loop so the user never misses it: something they "
                        "owe someone, a reply they owe, a deadline, or meeting prep. Use this "
                        "WHENEVER you'd track a commitment in chat — it shows the user a card to "
                        "confirm (you do NOT track silently). Break the task into its "
                        "definition-of-done steps: read the actual content (e.g. the email) and "
                        "derive the candidate sub-tasks it implies (each file/action requested = a "
                        "step). The user owns the granularity and can adjust or collapse them. If "
                        "the task is genuinely a single action, pass one step (or none). Do NOT "
                        "call this for items already tracked."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Short task title, e.g. 'Reply to Finnet re: OpenWay tender'."},
                            "kind": {"type": "string", "enum": list(KINDS), "description": "task = the user must do something; reply = the user owes a reply; deadline = a date-bound obligation; meeting-prep = prepare for a meeting."},
                            "owner": {"type": "string", "enum": ["me", "other"], "description": "'me' = the user is on the hook; 'other' = waiting on someone else."},
                            "due": {"type": "string", "description": "Due date as ISO YYYY-MM-DD, or with a time as YYYY-MM-DDTHH:MM, if any."},
                            "steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Candidate definition-of-done steps derived from the content, in order. Each is one concrete sub-task. Omit or use one item for a genuinely atomic task.",
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
        ),
        ToolSpec(
            name="suggest_step_done",
            is_action=True,
            schema={
                "type": "function",
                "function": {
                    "name": "suggest_step_done",
                    "description": (
                        "When something (an email, an event) implies one step of a tracked "
                        "checklist is now done, SUGGEST ticking it off — never tick silently. This "
                        "shows the user a confirm card. Name the specific step and a one-line note "
                        "on why you think it's done. Use the commitment id and the exact step text "
                        "from the LEDGER block. Remaining steps stay open."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "commitment_id": {"type": "string", "description": "The commitment id, e.g. 'c7'."},
                            "step": {"type": "string", "description": "The exact text of the step you think is done."},
                            "note": {"type": "string", "description": "One short line on why it looks done, e.g. 'vOffice confirmed they received the bukti potong'."},
                        },
                        "required": ["commitment_id", "step"],
                    },
                },
            },
        ),
        ToolSpec(
            name="list_commitments",
            handler=list_commitments,
            schema={
                "type": "function",
                "function": {
                    "name": "list_commitments",
                    "description": (
                        "Look at the user's tracked commitments (open loops) before answering "
                        "questions like 'what's on my plate?', 'what am I waiting on?', or when "
                        "deciding what's due soon. Returns open items by default."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": list(STATUSES), "description": "Filter by status."},
                            "owner": {"type": "string", "enum": ["me", "other"], "description": "Filter by who's on the hook."},
                        },
                    },
                },
            },
        ),
        ToolSpec(
            name="update_commitment",
            handler=update_commitment,
            schema={
                "type": "function",
                "function": {
                    "name": "update_commitment",
                    "description": (
                        "Change a tracked commitment by id — e.g. set status to 'waiting' or "
                        "'blocked', adjust the due date, or edit the text. Use list_commitments "
                        "first if you don't know the id."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "The commitment id, e.g. 'c3'."},
                            "text": {"type": "string"},
                            "kind": {"type": "string", "enum": list(KINDS)},
                            "owner": {"type": "string", "enum": ["me", "other"]},
                            "status": {"type": "string", "enum": list(STATUSES)},
                            "due": {"type": "string", "description": "ISO YYYY-MM-DD."},
                        },
                        "required": ["id"],
                    },
                },
            },
        ),
        ToolSpec(
            name="mark_done",
            handler=mark_done,
            schema={
                "type": "function",
                "function": {
                    "name": "mark_done",
                    "description": (
                        "Mark a tracked commitment complete by id when the user says it's handled. "
                        "If it has a checklist with open steps, this returns needs_confirmation with "
                        "the open steps instead of closing — surface those to the user and only pass "
                        "force:true once they confirm the whole obligation is truly done (not just a "
                        "step acknowledged)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "The commitment id, e.g. 'c3'."},
                            "force": {"type": "boolean", "description": "Complete even if checklist steps remain open. Only after the user confirms."},
                        },
                        "required": ["id"],
                    },
                },
            },
        ),
    ]
