"""A thin, swappable LLM interface.

The rest of Aurora depends only on :class:`LLMClient`, never on a specific
provider. Today the concrete implementation is DeepSeek (cheap, OpenAI-compatible
chat API); swapping models or providers later means adding a new subclass, not
touching callers.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import httpx

from aurora.config import Config

logger = logging.getLogger("aurora.llm")

Role = Literal["system", "user", "assistant"]


# DeepSeek sometimes emits a tool call as TEXT in ``content`` (using its internal
# markup tokens) instead of through the structured ``tool_calls`` field. The agent
# loop then sees no tool call and would relay the raw markup to the user. These
# lenient patterns recover such leaked calls so the loop can execute them normally.
# They ignore the exact delimiter form (DeepSeek wraps tags in special "｜｜DSML｜｜"
# tokens) and key only on the invoke/parameter structure.
_LEAK_INVOKE_RE = re.compile(
    r'invoke\s+name="([^"]+)"\s*>(.*?)</[^<>]*invoke\s*>', re.DOTALL | re.IGNORECASE
)
_LEAK_PARAM_RE = re.compile(
    r'parameter\s+name="([^"]+)"[^>]*>(.*?)</[^<>]*parameter\s*>', re.DOTALL | re.IGNORECASE
)


def _recover_tool_calls(content: str) -> tuple[list[dict], str]:
    """Parse tool calls leaked into text content into OpenAI-style ``tool_calls``.

    Returns ``(tool_calls, cleaned_content)``. If nothing looks leaked, returns
    ``([], content)`` unchanged — so normal replies are never touched."""
    if not content or "invoke name=" not in content:
        return [], content

    calls: list[dict] = []
    for i, m in enumerate(_LEAK_INVOKE_RE.finditer(content)):
        name, body = m.group(1).strip(), m.group(2)
        args: dict = {}
        for pm in _LEAK_PARAM_RE.finditer(body):
            key, raw = pm.group(1).strip(), pm.group(2).strip()
            try:  # recover real types (bools, numbers, arrays); else keep the string
                args[key] = json.loads(raw)
            except (ValueError, TypeError):
                args[key] = raw
        calls.append({
            "id": f"call_recovered_{i}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        })

    if not calls:
        return [], content

    # Strip the leaked markup so no raw tokens survive into history / the user.
    cleaned = re.sub(r'<[^<>]*tool_calls\s*>.*?</[^<>]*tool_calls\s*>', "", content,
                     flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<[^<>]*invoke\s+name=.*?</[^<>]*invoke\s*>', "", cleaned,
                     flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<[^<>]*DSML[^<>]*>', "", cleaned, flags=re.IGNORECASE).strip()
    return calls, cleaned


@dataclass(frozen=True)
class Message:
    """A single chat message."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMError(RuntimeError):
    """Raised when the LLM provider call fails."""


class LLMClient(ABC):
    """Provider-agnostic chat interface that Aurora codes against."""

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Return the assistant's reply text for a list of messages."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> dict:
        """Low-level OpenAI-style chat for tool use.

        ``messages`` are raw OpenAI-format dicts (supporting ``role: "tool"`` and
        assistant ``tool_calls``). Returns the assistant message dict, which may
        carry ``content`` and/or ``tool_calls``. This is what the agent loop uses.
        """

    def ask(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        """Convenience: single user prompt (with optional system) → reply text."""
        messages: list[Message] = []
        if system:
            messages.append(Message("system", system))
        messages.append(Message("user", prompt))
        return self.complete(messages, **kwargs)


class DeepSeekClient(LLMClient):
    """DeepSeek implementation over its OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    @classmethod
    def from_config(cls, config: Config) -> "DeepSeekClient":
        return cls(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            model=config.deepseek_model,
        )

    def _post(self, payload: dict) -> dict:
        """POST to /chat/completions, returning the parsed JSON or raising LLMError."""
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"DeepSeek returned {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"DeepSeek request failed: {exc}") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise LLMError(f"DeepSeek returned non-JSON: {response.text[:500]}") from exc

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict = {
            "model": self._model,
            "messages": [m.as_dict() for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        data = self._post(payload)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected DeepSeek response shape: {data}") from exc

    def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        data = self._post(payload)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected DeepSeek response shape: {data}") from exc

        # Recover any tool call the model leaked into text instead of tool_calls.
        if not message.get("tool_calls"):
            recovered, cleaned = _recover_tool_calls(message.get("content") or "")
            if recovered:
                logger.warning(
                    "Recovered %d tool call(s) leaked into DeepSeek content: %s",
                    len(recovered),
                    [c["function"]["name"] for c in recovered],
                )
                message["tool_calls"] = recovered
                message["content"] = cleaned or None
        return message
