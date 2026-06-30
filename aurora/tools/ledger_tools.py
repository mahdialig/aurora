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
    """Inline tools (bound to the ledger) for tracking commitments."""

    def add_commitment(args: dict) -> str:
        text = (args.get("text") or "").strip()
        if not text:
            return json.dumps({"error": "text is required"})
        c = ledger.add(
            text,
            kind=(args.get("kind") or "task"),
            owner=(args.get("owner") or "me"),
            due=(args.get("due") or "").strip(),
            source=(args.get("source") or "chat").strip(),
        )
        return json.dumps({"tracked": {"id": c.id, "text": c.text, "kind": c.kind, "due": c.due}})

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
        done = ledger.mark_done(cid)
        if done is None:
            return json.dumps({"error": f"no commitment with id {cid}"})
        return json.dumps({"done": {"id": done.id, "text": done.text}})

    return [
        ToolSpec(
            name="add_commitment",
            handler=add_commitment,
            schema={
                "type": "function",
                "function": {
                    "name": "add_commitment",
                    "description": (
                        "Track an open loop so the user never misses it: something they owe "
                        "someone, a reply they're awaiting from someone else, a deadline, or "
                        "meeting prep. Call this whenever the user mentions a task, commitment, "
                        "or due date — or asks you to remind/track something. Confirm briefly after."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Short description, e.g. 'Reply to Sara about the proposal'."},
                            "kind": {"type": "string", "enum": list(KINDS), "description": "task = the user must do something; reply = the user owes a reply; deadline = a date-bound obligation; meeting-prep = prepare for a meeting."},
                            "owner": {"type": "string", "enum": ["me", "other"], "description": "'me' = the user is on the hook; 'other' = waiting on someone else."},
                            "due": {"type": "string", "description": "Due date as ISO YYYY-MM-DD, if any."},
                        },
                        "required": ["text"],
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
                    "description": "Mark a tracked commitment complete by id when the user says it's handled.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "The commitment id, e.g. 'c3'."},
                        },
                        "required": ["id"],
                    },
                },
            },
        ),
    ]
