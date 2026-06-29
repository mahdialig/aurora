"""A thin, swappable LLM interface.

The rest of Aurora depends only on :class:`LLMClient`, never on a specific
provider. Today the concrete implementation is DeepSeek (cheap, OpenAI-compatible
chat API); swapping models or providers later means adding a new subclass, not
touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import httpx

from aurora.config import Config

Role = Literal["system", "user", "assistant"]


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
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected DeepSeek response shape: {data}") from exc
