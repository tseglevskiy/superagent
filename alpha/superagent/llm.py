"""LLM clients — OpenRouter (OpenAI-compat) and Ollama.

Both expose the same call() interface so the engine does not care
which provider is active.  We use the *openai* library for OpenRouter
(it speaks the OpenAI wire format) and the *ollama* library for local models.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import ollama as ollama_lib
from openai import OpenAI

from .config import LLMConfig

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A single tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Normalized response from any provider."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    def call(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse: ...


# ---------------------------------------------------------------------------
# OpenRouter via openai SDK
# ---------------------------------------------------------------------------


class OpenRouterClient:
    """Calls OpenRouter using the openai Python library."""

    def __init__(self, cfg: LLMConfig) -> None:
        if not cfg.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not set. "
                "Export it or add api_key to config.yaml"
            )
        self._client = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )
        self._default_model = cfg.chat_model

    def call(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        model = model or self._default_model
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        if tools:
            kwargs["tools"] = tools

        log.debug("openrouter call  model=%s  msgs=%d", model, len(messages))
        raw = self._client.chat.completions.create(**kwargs)
        choice = raw.choices[0]
        msg = choice.message

        # parse tool calls
        tc_list: list[ToolCall] = []
        if msg.tool_calls:
            import json

            for tc in msg.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json.loads(args)
                tc_list.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        usage = raw.usage
        return LLMResponse(
            content=msg.content,
            tool_calls=tc_list,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=model,
            stop_reason=choice.finish_reason or "",
        )


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class OllamaClient:
    """Calls a local Ollama instance."""

    def __init__(self, cfg: LLMConfig) -> None:
        self._client = ollama_lib.Client(host=cfg.ollama_base)
        self._default_model = cfg.ollama_model

    def call(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        model = model or self._default_model
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            options={"temperature": temperature},
        )
        if tools:
            kwargs["tools"] = tools

        log.debug("ollama call  model=%s  msgs=%d", model, len(messages))
        raw = self._client.chat(**kwargs)

        # parse tool calls (Ollama >= 0.5 supports tool calling)
        tc_list: list[ToolCall] = []
        if hasattr(raw.message, "tool_calls") and raw.message.tool_calls:
            for i, tc in enumerate(raw.message.tool_calls):
                tc_list.append(
                    ToolCall(
                        id=f"ollama_{i}",
                        name=tc.function.name,
                        arguments=tc.function.arguments or {},
                    )
                )

        return LLMResponse(
            content=raw.message.content or None,
            tool_calls=tc_list,
            input_tokens=raw.prompt_eval_count or 0,
            output_tokens=raw.eval_count or 0,
            model=model,
            stop_reason="stop",
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_client(cfg: LLMConfig) -> LLMClient:
    """Create the right client based on config."""
    if cfg.provider == "ollama":
        return OllamaClient(cfg)
    return OpenRouterClient(cfg)
