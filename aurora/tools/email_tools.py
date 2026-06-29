"""Email tools the agent can call.

Read-only tools (list/search/read) execute inside the agent loop. Action tools
(send/draft) are added in stage 4 and are approval-gated. Handlers return compact
JSON strings — Aurora reads these and reports in her own words; she never dumps
them at the user verbatim.
"""

from __future__ import annotations

import json

from aurora.agent import ToolSpec
from aurora.sources.base import EmailSummary
from aurora.sources.registry import MailAccounts

_MAX_RESULT_CHARS = 6000
_MAX_BODY_CHARS = 3000

_ACCOUNT_PARAM = {
    "type": "string",
    "description": "Which mailbox: 'personal', 'work', or 'all'. Default 'all'.",
}


def _summary_dict(account: str, s: EmailSummary) -> dict:
    return {
        "account": account,
        "id": s.id,
        "from": s.sender,
        "subject": s.subject,
        "date": s.date,
        "snippet": s.snippet,
    }


def build_email_tools(accounts: MailAccounts) -> list[ToolSpec]:
    """Read-only email tools bound to the given accounts."""

    def list_unread(args: dict) -> str:
        pairs = accounts.resolve(args.get("account", "all"))
        if not pairs:
            return json.dumps({"error": "no matching account is connected"})
        limit = int(args.get("limit", 10) or 10)
        out: list[dict] = []
        for name, acc in pairs:
            try:
                out.extend(_summary_dict(name, s) for s in acc.list_unread(limit))
            except Exception as exc:  # noqa: BLE001
                out.append({"account": name, "error": str(exc)})
        return json.dumps(out)[:_MAX_RESULT_CHARS]

    def search_mail(args: dict) -> str:
        query = (args.get("query") or "").strip()
        if not query:
            return json.dumps({"error": "query is required"})
        pairs = accounts.resolve(args.get("account", "all"))
        if not pairs:
            return json.dumps({"error": "no matching account is connected"})
        limit = int(args.get("limit", 10) or 10)
        out: list[dict] = []
        for name, acc in pairs:
            try:
                out.extend(_summary_dict(name, s) for s in acc.search(query, limit))
            except Exception as exc:  # noqa: BLE001
                out.append({"account": name, "error": str(exc)})
        return json.dumps(out)[:_MAX_RESULT_CHARS]

    def read_email(args: dict) -> str:
        name = (args.get("account") or "").strip()
        msg_id = (args.get("id") or "").strip()
        if not name or name == "all" or not msg_id:
            return json.dumps({"error": "read_email needs a specific 'account' and an 'id'"})
        acc = accounts.get(name)
        if acc is None:
            return json.dumps({"error": f"account '{name}' is not connected"})
        try:
            m = acc.get_message(msg_id)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})
        return json.dumps(
            {
                "account": name,
                "from": m.sender,
                "to": m.to,
                "subject": m.subject,
                "date": m.date,
                "body": m.body[:_MAX_BODY_CHARS],
            }
        )

    return [
        ToolSpec(
            name="list_unread",
            handler=list_unread,
            schema={
                "type": "function",
                "function": {
                    "name": "list_unread",
                    "description": "List recent UNREAD emails (sender, subject, snippet) to see what's new.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account": _ACCOUNT_PARAM,
                            "limit": {"type": "integer", "description": "Max emails (default 10)."},
                        },
                    },
                },
            },
        ),
        ToolSpec(
            name="search_mail",
            handler=search_mail,
            schema={
                "type": "function",
                "function": {
                    "name": "search_mail",
                    "description": (
                        "Search mail for matching messages, INCLUDING spam and trash. For the "
                        "personal (Gmail) account, 'query' uses Gmail search syntax — prefer "
                        "searching by sender address (e.g. 'from:alice@x.com') or subject "
                        "(e.g. 'subject:invoice') over a person's name."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query."},
                            "account": _ACCOUNT_PARAM,
                            "limit": {"type": "integer", "description": "Max results (default 10)."},
                        },
                        "required": ["query"],
                    },
                },
            },
        ),
        ToolSpec(
            name="read_email",
            handler=read_email,
            schema={
                "type": "function",
                "function": {
                    "name": "read_email",
                    "description": "Read the full body of one email, by its account and id (from a list/search result).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account": {"type": "string", "description": "'personal' or 'work' (not 'all')."},
                            "id": {"type": "string", "description": "The email id from a previous result."},
                        },
                        "required": ["account", "id"],
                    },
                },
            },
        ),
        # Action tool: NOT executed by the agent loop. It short-circuits to a user
        # approval (Send / Save draft / Cancel). Read the email first for context.
        ToolSpec(
            name="reply_to_email",
            is_action=True,
            schema={
                "type": "function",
                "function": {
                    "name": "reply_to_email",
                    "description": (
                        "Compose a reply to a specific email and present it to the user for "
                        "approval — they choose to send it, save it as a draft, or cancel. "
                        "Read the email first so the reply has context. Write the body in the "
                        "user's voice."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account": {"type": "string", "description": "'personal' or 'work' — where the email is."},
                            "email_id": {"type": "string", "description": "Id of the email to reply to."},
                            "body": {"type": "string", "description": "The reply body text."},
                        },
                        "required": ["account", "email_id", "body"],
                    },
                },
            },
        ),
        ToolSpec(
            name="resend_last_draft",
            is_action=True,
            schema={
                "type": "function",
                "function": {
                    "name": "resend_last_draft",
                    "description": (
                        "Re-propose the most recent reply you drafted earlier in THIS "
                        "conversation, unchanged, so the user can Send / Save draft / Cancel it. "
                        "Use when the user says e.g. 'send the one you drafted', 'resend that "
                        "draft', or 'send the reply you wrote earlier'."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ),
    ]
