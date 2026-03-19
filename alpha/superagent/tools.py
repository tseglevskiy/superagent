"""Tool registry — python_exec, memory_update, retire_observation, moan,
confirm_knowledge, use_knowledge.

Active tools:
  python_exec          — execute Python in smolagents AST sandbox
  memory_update        — set/delete entries in working memory blocks
  retire_observation   — mark an observation as outdated
  moan                 — write-only pain report about API/capability issues
  confirm_knowledge    — signal that an observation was confirmed by current work
  use_knowledge        — signal that an observation was essential for reasoning

Removed:
  knowledge_search     — observations are always in context now, no search needed
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .knowledge import KnowledgeStore
from .memory import update_entry
from .sandbox import make_executor

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any], dict[str, Any]], str]


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Handler | None = None


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def dispatch(self, name: str, args: dict[str, Any], context: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        if tool.handler is None:
            return f"Error: tool '{name}' not implemented"
        try:
            return tool.handler(args, context)
        except Exception as e:
            log.exception("tool %s failed", name)
            return f"Error executing {name}: {e}"

    def openai_schemas(self) -> list[dict]:
        result = []
        for t in self._tools.values():
            result.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                },
            })
        return result


# ---------------------------------------------------------------------------
# python_exec handler
# ---------------------------------------------------------------------------

# Default print output limit (characters). Can be overridden per-call via max_output parameter.
DEFAULT_MAX_PRINT_OUTPUT = 10_000


def _make_python_exec_handler(
    integration_functions: dict[str, Any],
    store: KnowledgeStore,
) -> Handler:
    """Create python_exec handler with integration functions + observation symbols."""
    executor = make_executor(integration_functions)

    # Load observation symbols (vars + functions) into sandbox
    _load_observation_symbols(executor, store)

    def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
        code = args.get("code", "")
        if not code.strip():
            return "Error: empty code"

        # Allow per-call override of print output limit
        max_output = args.get("max_output")
        if max_output is not None:
            max_output = min(int(max_output), 200_000)  # hard ceiling
            original_limit = executor.max_print_outputs_length
            executor.max_print_outputs_length = max_output
        else:
            original_limit = None

        try:
            result = executor(code)
        except Exception as e:
            # Include any print output captured before the error so the LLM
            # knows what work was already done (e.g. edits flushed to disk)
            # before the exception fired.
            prior_output = executor.state.get("print_outputs", "")
            if prior_output:
                return f"{prior_output}\nExecution error: {e}"
            return f"Execution error: {e}"
        finally:
            # Always restore default limit
            if original_limit is not None:
                executor.max_print_outputs_length = original_limit

        parts = []
        if result.logs:
            parts.append(result.logs)
        if result.output is not None:
            parts.append(f"Output: {result.output}")
        return "\n".join(parts) if parts else "(no output)"

    return handler


def _load_observation_symbols(executor, store: KnowledgeStore) -> None:
    """Load all active observation symbols (vars + functions) into the sandbox.

    Execs the whole observation body in an isolated namespace, then exports
    each symbol with an ID suffix. Internal references work because they
    share the same exec namespace.
    """
    observations = store.load_all_active()
    loaded = 0
    for obs in observations:
        if not obs.content.strip():
            continue
        # Exec the whole body — internal references between vars and functions work
        ns: dict = {}
        try:
            exec(obs.content, ns)
        except Exception as e:
            log.warning("failed to exec observation %s: %s", obs.id, e)
            continue

        # Export each public symbol with ID suffix
        for name, value in ns.items():
            if name.startswith("_") or name in ("__builtins__",):
                continue
            suffixed = f"{name}_{obs.short_id}"
            if callable(value):
                # Wrap callable with metrics
                def _make_wrapper(fn, oid, sname):
                    def wrapper(*args, **kwargs):
                        try:
                            result = fn(*args, **kwargs)
                            store.record_call(oid, success=True)
                            return result
                        except Exception as e:
                            store.record_call(oid, success=False)
                            raise
                    wrapper.__name__ = sname
                    wrapper.__doc__ = getattr(fn, "__doc__", None)
                    return wrapper
                executor.additional_functions[suffixed] = _make_wrapper(value, obs.id, suffixed)
            else:
                # Non-callable (data structure) — inject directly
                executor.additional_functions[suffixed] = value
            loaded += 1

    if loaded:
        executor.send_tools({})
        log.info("loaded %d observation symbols into sandbox", loaded)


# ---------------------------------------------------------------------------
# memory_update handler
# ---------------------------------------------------------------------------

def _make_memory_update_handler(memory_dir: Path) -> Handler:
    def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
        label = args.get("label", "")
        key = args.get("key", "")
        value = args.get("value", "")
        if not label:
            return "Error: label is required"
        if not key:
            return "Error: key is required"
        return update_entry(memory_dir, label, key, value)
    return handler


# ---------------------------------------------------------------------------
# retire_observation handler
# ---------------------------------------------------------------------------

def _make_retire_observation_handler(store: KnowledgeStore) -> Handler:
    def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
        obs_id = args.get("observation_id", "")
        if not obs_id:
            return "Error: observation_id is required"
        return store.retire(obs_id)
    return handler


# ---------------------------------------------------------------------------
# moan handler — write-only pain reports for humans
# ---------------------------------------------------------------------------

def _make_moan_handler(feedback_dir: Path) -> Handler:
    """Create handler that appends friction/pain reports to a JSONL file.

    Write-only: the agent never reads these back. Humans review them to
    improve the API, prompts, and capabilities.
    """
    feedback_dir.mkdir(parents=True, exist_ok=True)
    moans_file = feedback_dir / "moans.jsonl"

    def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
        message = args.get("message", "").strip()
        if not message:
            return "Error: message is required"
        category = args.get("category", "general").strip()
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "category": category,
            "message": message,
        }
        with open(moans_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.info("moan recorded: [%s] %s", category, message[:80])
        return "OK: pain recorded. Thank you for reporting."

    return handler


# ---------------------------------------------------------------------------
# knowledge signal handlers — confirm_knowledge, use_knowledge
# ---------------------------------------------------------------------------

def _make_knowledge_signal_handler(knowledge_dir: Path, signal_type: str) -> Handler:
    """Create handler that records a knowledge signal (confirmed / used).

    Appends to a JSONL file. Humans and the extraction pipeline can use
    these signals to gauge which observations are valuable.
    """
    signals_file = knowledge_dir / "signals.jsonl"

    def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
        obs_id = args.get("observation_id", "").strip()
        reason = args.get("reason", "").strip()
        if not obs_id:
            return "Error: observation_id is required"
        if not reason:
            return "Error: reason is required - explain how the knowledge was " + (
                "confirmed" if signal_type == "confirmed" else "used"
            )
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "type": signal_type,
            "observation_id": obs_id,
            "reason": reason,
        }
        with open(signals_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.info("knowledge %s: %s - %s", signal_type, obs_id, reason[:80])
        return f"OK: observation {obs_id} marked as {signal_type}."

    return handler


# ---------------------------------------------------------------------------
# Build registry
# ---------------------------------------------------------------------------

def build_registry(
    integration_functions: dict[str, Any],
    memory_dir: Path,
    knowledge_dir: Path,
    data_dir: Path,
) -> ToolRegistry:
    """Build the tool registry with integration functions injected into the sandbox.

    Args:
        integration_functions: merged functions from all integration modules.
        memory_dir: path to memory block files.
        knowledge_dir: path to knowledge store.
        data_dir: path to the top-level data directory (for feedback files).
    """
    store = KnowledgeStore(knowledge_dir)
    reg = ToolRegistry()

    # Build function list for tool description
    func_names = ", ".join(sorted(integration_functions.keys()))

    reg.register(Tool(
        name="python_exec",
        description=(
            "Execute Python code in a sandboxed environment. "
            "Use print() to produce output. "
            f"Available functions: {func_names}. "
            "Learned functions from observations are also available (shown in context). "
            "Standard modules: json, csv, re, collections, itertools, math, statistics. "
            "State persists between calls."
        ),
        schema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use print() for output.",
                },
                "max_output": {
                    "type": "integer",
                    "description": (
                        "Override the default 10K character print output limit. "
                        "Use when you intentionally need to see more output "
                        "(e.g. printing a large file or dataset). Max 200000."
                    ),
                },
            },
            "required": ["code"],
        },
        handler=_make_python_exec_handler(integration_functions, store),
    ))

    reg.register(Tool(
        name="memory_update",
        description=(
            "Set or delete an entry in a working memory block. "
            "Blocks are shown in <memory_blocks> in the system prompt. "
            "Use to record workspace discoveries and user preferences. "
            "Send empty value to delete a key."
        ),
        schema={
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Block name: workspace_info, user_preferences, or persona",
                },
                "key": {
                    "type": "string",
                    "description": "Entry key name",
                },
                "value": {
                    "type": "string",
                    "description": "Entry value. Empty string = delete the key.",
                },
            },
            "required": ["label", "key", "value"],
        },
        handler=_make_memory_update_handler(memory_dir),
    ))

    reg.register(Tool(
        name="retire_observation",
        description=(
            "Retire an outdated observation. Use when you discover that a previously "
            "recorded observation is no longer accurate. The observation stays on disk "
            "but is removed from context and sandbox."
        ),
        schema={
            "type": "object",
            "properties": {
                "observation_id": {
                    "type": "string",
                    "description": "The observation ID from the <observations> section",
                },
            },
            "required": ["observation_id"],
        },
        handler=_make_retire_observation_handler(store),
    ))

    reg.register(Tool(
        name="moan",
        description=(
            "Report pain: something in the API, tools, or capabilities that made "
            "your work impossible, extremely hard, or unnecessarily wasteful. "
            "Write-only — humans review these to improve the system. "
            "Use freely whenever you hit friction, a missing function, a confusing "
            "error, an API that worked differently than expected, or had to use "
            "an ugly workaround."
        ),
        schema={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": (
                        "What went wrong, what was missing, or what made "
                        "the task unnecessarily hard. Be specific."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Category of the pain: missing_function, api_surprise, "
                        "error_message, workaround, prompt_confusion, performance, other"
                    ),
                },
            },
            "required": ["message"],
        },
        handler=_make_moan_handler(data_dir / "feedback"),
    ))

    reg.register(Tool(
        name="confirm_knowledge",
        description=(
            "Signal that your current work independently confirmed something "
            "recorded in an observation. Call when you encounter evidence that "
            "validates a previously extracted pattern, fact, or function."
        ),
        schema={
            "type": "object",
            "properties": {
                "observation_id": {
                    "type": "string",
                    "description": "The observation ID from the <observations> section",
                },
                "reason": {
                    "type": "string",
                    "description": "How your current work confirmed this knowledge",
                },
            },
            "required": ["observation_id", "reason"],
        },
        handler=_make_knowledge_signal_handler(knowledge_dir, "confirmed"),
    ))

    reg.register(Tool(
        name="use_knowledge",
        description=(
            "Signal that an observation was essential for your reasoning — "
            "you used it as a basis or material and could not have reached "
            "your conclusion without it. Call when knowledge from an observation "
            "directly enabled your work."
        ),
        schema={
            "type": "object",
            "properties": {
                "observation_id": {
                    "type": "string",
                    "description": "The observation ID from the <observations> section",
                },
                "reason": {
                    "type": "string",
                    "description": "How this knowledge was used and why it was essential",
                },
            },
            "required": ["observation_id", "reason"],
        },
        handler=_make_knowledge_signal_handler(knowledge_dir, "used"),
    ))

    return reg
