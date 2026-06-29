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
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Unexpected DeepSeek response shape: {response.text[:500]}") from exc
