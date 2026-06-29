import httpx
import pytest

from aurora.llm import DeepSeekClient, Message
from aurora.llm.client import LLMError


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
