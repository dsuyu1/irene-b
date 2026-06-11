"""LLM provider abstraction.

Everything in IRENE that talks to a model — the analyst policy, the free-text
action resolver, and the LLM-as-judge — goes through a single tiny ``LLMClient``
interface. That keeps the rest of the codebase provider-agnostic and makes
adding a backend a matter of implementing one ``complete`` method.

Two backends ship today:

- ``AnthropicClient`` — the Claude API.
- ``OpenAIClient``    — any OpenAI-compatible endpoint (OpenAI itself, vLLM,
  Together, Groq, Ollama, LM Studio, OpenRouter, …) via ``base_url`` + API key.

SDKs are imported lazily so you only need the one you actually use installed.
"""

from __future__ import annotations

import os
from typing import Protocol


class LLMClient(Protocol):
    """Minimal text-in/text-out interface."""

    model: str

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> str:
        """Return the model's text response to ``prompt`` under ``system``."""
        ...


class AnthropicClient:
    """Claude API backend."""

    def __init__(self, model: str = "claude-opus-4-8", api_key: str | None = None, client=None):
        self.model = model
        if client is None:
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self._client = client

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in message.content if b.type == "text")


class OpenAIClient:
    """OpenAI-compatible backend (base_url + api_key).

    Works with the official OpenAI API and any server that implements the
    ``/v1/chat/completions`` contract. Point it at a local or self-hosted model
    by setting ``base_url`` (or the ``OPENAI_BASE_URL`` env var).
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        client=None,
    ):
        self.model = model
        if client is None:
            from openai import OpenAI

            # Many self-hosted servers don't check the key but the SDK still
            # requires a non-empty string, so fall back to a dummy.
            client = OpenAI(
                api_key=api_key or os.environ.get("OPENAI_API_KEY") or "not-needed",
                base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
            )
        self._client = client

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""


def make_client(
    provider: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMClient:
    """Construct a client from a provider name.

    ``provider`` is ``"anthropic"`` or ``"openai"``. For ``"openai"``, ``model``
    is required (there is no universal default across compatible servers).
    """
    provider = provider.lower()
    if provider == "anthropic":
        return AnthropicClient(model=model or "claude-opus-4-8", api_key=api_key)
    if provider in {"openai", "openai-compatible", "compat"}:
        if not model:
            raise ValueError("an OpenAI-compatible provider requires --model")
        return OpenAIClient(model=model, api_key=api_key, base_url=base_url)
    raise ValueError(f"unknown provider '{provider}' (expected 'anthropic' or 'openai')")
