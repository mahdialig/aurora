import json

import httpx
import pytest

from aurora.llm import DeepSeekClient, Message
from aurora.llm.client import LLMError, _recover_tool_calls


def test_complete_parses_reply(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hello back"}}]}
        )

    monkeypatch.setattr(
        "aurora.llm.client.httpx.post",
        lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw),
    )
    client = DeepSeekClient(api_key="sk-test")
    reply = client.complete([Message("user", "hi")])
    assert reply == "hello back"


def test_http_error_becomes_llmerror(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    monkeypatch.setattr(
        "aurora.llm.client.httpx.post",
        lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw),
    )
    client = DeepSeekClient(api_key="sk-bad")
    with pytest.raises(LLMError, match="401"):
        client.complete([Message("user", "hi")])


def _mock_post(monkeypatch, handler):
    monkeypatch.setattr(
        "aurora.llm.client.httpx.post",
        lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw),
    )


def test_chat_returns_text_message(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]})

    _mock_post(monkeypatch, handler)
    msg = DeepSeekClient(api_key="sk-test").chat([{"role": "user", "content": "hello"}])
    assert msg["content"] == "hi"
    assert "tool_calls" not in msg


def test_chat_returns_tool_calls_and_sends_tools(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "list_unread", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
        )

    _mock_post(monkeypatch, handler)
    tools = [{"type": "function", "function": {"name": "list_unread", "parameters": {}}}]
    msg = DeepSeekClient(api_key="sk-test").chat([{"role": "user", "content": "any mail?"}], tools=tools)
    assert msg["tool_calls"][0]["function"]["name"] == "list_unread"
    # tools were forwarded in the request payload
    assert captured["body"]["tools"] == tools


# --- recovery of tool calls leaked into text content (DeepSeek quirk) -------

# The exact markup DeepSeek leaked in a real session (special "｜｜DSML｜｜" tokens).
_LEAKED = (
    "<｜｜DSML｜｜tool_calls>\n"
    '<｜｜DSML｜｜invoke name="search_mail">\n'
    '<｜｜DSML｜｜parameter name="query" string="true">OpenWay Aji</｜｜DSML｜｜parameter>\n'
    '<｜｜DSML｜｜parameter name="account" string="true">all</｜｜DSML｜｜parameter>\n'
    "</｜｜DSML｜｜invoke>\n"
    "</｜｜DSML｜｜tool_calls>"
)


def test_recover_parses_leaked_call_and_strips_markup():
    calls, cleaned = _recover_tool_calls(_LEAKED)
    assert len(calls) == 1
    fn = calls[0]["function"]
    assert fn["name"] == "search_mail"
    assert json.loads(fn["arguments"]) == {"query": "OpenWay Aji", "account": "all"}
    assert cleaned == ""  # no raw tokens survive


def test_recover_coerces_value_types():
    leaked = (
        '<｜｜DSML｜｜invoke name="mark_done">'
        '<｜｜DSML｜｜parameter name="id">c3</｜｜DSML｜｜parameter>'
        '<｜｜DSML｜｜parameter name="force">true</｜｜DSML｜｜parameter>'
        "</｜｜DSML｜｜invoke>"
    )
    calls, _ = _recover_tool_calls(leaked)
    args = json.loads(calls[0]["function"]["arguments"])
    assert args == {"id": "c3", "force": True}  # bool recovered, id stays a string


def test_recover_ignores_normal_text():
    assert _recover_tool_calls("Just a normal reply, nothing to see.") == ([], "Just a normal reply, nothing to see.")
    assert _recover_tool_calls("") == ([], "")


def test_chat_recovers_leaked_tool_call(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": _LEAKED}}]}
        )

    _mock_post(monkeypatch, handler)
    msg = DeepSeekClient(api_key="sk-test").chat([{"role": "user", "content": "track NDA"}])
    assert msg["tool_calls"][0]["function"]["name"] == "search_mail"
    assert not msg.get("content")  # cleaned to empty/None, not raw markup
