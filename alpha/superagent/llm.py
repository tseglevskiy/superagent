"""LLM clients — OpenRouter (OpenAI-compat) and Ollama.

Both expose the same call() and stream() interfaces so the engine does not
care which provider is active.  We use the *openai* library for OpenRouter
(it speaks the OpenAI wire format) and the *ollama* library for local models.

All public methods are async.  The engine awaits them from an asyncio loop.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import ollama as ollama_lib
from openai import AsyncOpenAI

from .config import LLMConfig

log = logging.getLogger(__name__)

# Verbosity level — set by __main__.py at startup
_verbose: int = 0


def set_llm_verbose(level: int) -> None:
    global _verbose
    _verbose = level


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
    cached_tokens: int = 0
    model: str = ""
    stop_reason: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class LLMChunk:
    """One delta from a streaming LLM response."""

    content: str = ""
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_call_name: str | None = None
    tool_call_arguments_delta: str = ""
    finish_reason: str | None = None
    # Usage stats — only populated on final chunk (OpenRouter) or post-stream (Ollama)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    model: str = ""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    async def call(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse: ...

    async def stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMChunk]: ...


# ---------------------------------------------------------------------------
# Prompt caching helpers (shared by call and stream)
# ---------------------------------------------------------------------------

_CC = {"type": "ephemeral"}


def _apply_cache_breakpoints(messages: list[dict]) -> None:
    """Apply Anthropic prompt caching breakpoints in-place.

    3 breakpoints (of 4 max):
      1. System prompt (static header: rules, knowledge, memory)
      2. Second-to-last message (failover if last call is retried)
      3. Last message (gradual forward movement)
    """

    def _mark(m: dict) -> None:
        content = m.get("content")
        if isinstance(content, str):
            m["content"] = [{"type": "text", "text": content, "cache_control": _CC}]
        elif isinstance(content, list):
            for block in reversed(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    block["cache_control"] = _CC
                    break

    for m in messages:
        if m.get("role") == "system":
            _mark(m)
            break
    if len(messages) >= 3:
        _mark(messages[-2])
    if len(messages) >= 2:
        _mark(messages[-1])


# ---------------------------------------------------------------------------
# OpenRouter via openai SDK (async)
# ---------------------------------------------------------------------------


class OpenRouterClient:
    """Calls OpenRouter using the async openai Python library."""

    def __init__(self, cfg: LLMConfig) -> None:
        if not cfg.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not set. "
                "Export it or add api_key to config.yaml"
            )
        self._client = AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )
        self._default_model = cfg.chat_model

    async def call(
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

        _apply_cache_breakpoints(messages)

        log.debug("openrouter call  model=%s  msgs=%d", model, len(messages))
        raw = await self._client.chat.completions.create(**kwargs)
        choice = raw.choices[0]
        msg = choice.message

        if _verbose >= 3:
            usage_dict: dict[str, Any] = {}
            if raw.usage:
                usage_dict = {"prompt_tokens": raw.usage.prompt_tokens, "completion_tokens": raw.usage.completion_tokens}
                if hasattr(raw.usage, "prompt_tokens_details") and raw.usage.prompt_tokens_details:
                    usage_dict["prompt_tokens_details"] = str(raw.usage.prompt_tokens_details)
                if hasattr(raw.usage, "completion_tokens_details") and raw.usage.completion_tokens_details:
                    usage_dict["completion_tokens_details"] = str(raw.usage.completion_tokens_details)
            print(f"\033[2m[api-raw] model={model} finish={choice.finish_reason} usage={json.dumps(usage_dict)}\033[0m")

        tc_list: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json.loads(args)
                tc_list.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        usage = raw.usage
        cached = 0
        if usage and hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
        return LLMResponse(
            content=msg.content,
            tool_calls=tc_list,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=cached,
            model=model,
            stop_reason=choice.finish_reason or "",
        )

    async def stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMChunk]:
        model = model or self._default_model
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"] = tools

        _apply_cache_breakpoints(messages)

        log.debug("openrouter stream  model=%s  msgs=%d", model, len(messages))
        response = await self._client.chat.completions.create(**kwargs)

        async for chunk in response:
            if not chunk.choices and hasattr(chunk, "usage") and chunk.usage:
                # Final usage-only chunk (stream_options include_usage)
                usage = chunk.usage
                cached = 0
                if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                    cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
                yield LLMChunk(
                    input_tokens=usage.prompt_tokens or 0,
                    output_tokens=usage.completion_tokens or 0,
                    cached_tokens=cached,
                    model=model,
                )
                continue

            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            # Text content delta
            content = delta.content or ""

            # Tool call deltas
            tc_index = None
            tc_id = None
            tc_name = None
            tc_args = ""
            if delta.tool_calls:
                tc_delta = delta.tool_calls[0]
                tc_index = tc_delta.index
                tc_id = tc_delta.id or None
                if tc_delta.function:
                    tc_name = tc_delta.function.name or None
                    tc_args = tc_delta.function.arguments or ""

            yield LLMChunk(
                content=content,
                tool_call_index=tc_index,
                tool_call_id=tc_id,
                tool_call_name=tc_name,
                tool_call_arguments_delta=tc_args,
                finish_reason=choice.finish_reason,
                model=model,
            )


# ---------------------------------------------------------------------------
# Ollama (async)
# ---------------------------------------------------------------------------


class OllamaClient:
    """Calls a local Ollama instance using the async client."""

    def __init__(self, cfg: LLMConfig) -> None:
        self._client = ollama_lib.AsyncClient(host=cfg.ollama_base)
        self._default_model = cfg.ollama_model

    async def call(
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
        raw = await self._client.chat(**kwargs)

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

    async def stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> AsyncIterator[LLMChunk]:
        model = model or self._default_model
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            options={"temperature": temperature},
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools

        log.debug("ollama stream  model=%s  msgs=%d", model, len(messages))
        response = await self._client.chat(**kwargs)

        input_tokens = 0
        output_tokens = 0
        async for chunk in response:
            content = ""
            if hasattr(chunk, "message") and chunk.message:
                content = chunk.message.content or ""

            # Ollama provides eval counts on the final chunk
            if hasattr(chunk, "prompt_eval_count") and chunk.prompt_eval_count:
                input_tokens = chunk.prompt_eval_count
            if hasattr(chunk, "eval_count") and chunk.eval_count:
                output_tokens = chunk.eval_count

            done = getattr(chunk, "done", False)

            # Tool calls in streaming — Ollama sends them on the final message
            tc_index = None
            tc_id = None
            tc_name = None
            tc_args = ""
            if hasattr(chunk, "message") and chunk.message and hasattr(chunk.message, "tool_calls") and chunk.message.tool_calls:
                tc = chunk.message.tool_calls[0]
                tc_index = 0
                tc_id = f"ollama_0"
                tc_name = tc.function.name
                tc_args = json.dumps(tc.function.arguments or {})

            yield LLMChunk(
                content=content,
                tool_call_index=tc_index,
                tool_call_id=tc_id,
                tool_call_name=tc_name,
                tool_call_arguments_delta=tc_args,
                finish_reason="stop" if done else None,
                input_tokens=input_tokens if done else 0,
                output_tokens=output_tokens if done else 0,
                model=model,
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_client(cfg: LLMConfig) -> LLMClient:
    """Create the right client based on config."""
    if cfg.provider == "ollama":
        return OllamaClient(cfg)
    return OpenRouterClient(cfg)
