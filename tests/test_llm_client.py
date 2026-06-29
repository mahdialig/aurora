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
