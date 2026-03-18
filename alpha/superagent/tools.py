"""Tool registry — python_exec, memory_update, knowledge_search.

Active tools:
  python_exec       — execute Python in smolagents AST sandbox
  memory_update     — set/delete entries in working memory blocks
  knowledge_search  — search accumulated knowledge (stub for now)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .memory import update_entry
from .sandbox import make_executor, FUNCTION_STUBS

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

def _make_python_exec_handler(workspace: Path) -> Handler:
    executor = make_executor(workspace)

    def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
        code = args.get("code", "")
        if not code.strip():
            return "Error: empty code"
        try:
            result = executor(code)
        except Exception as e:
            return f"Execution error: {e}"
        parts = []
        if result.logs:
            parts.append(result.logs)
        if result.output is not None:
            parts.append(f"Output: {result.output}")
        return "\n".join(parts) if parts else "(no output)"

    return handler


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
# knowledge_search handler (stub)
# ---------------------------------------------------------------------------

def _make_knowledge_search_handler() -> Handler:
    def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
        query = args.get("query", "")
        return f"(no knowledge yet — knowledge store not initialized)"

    return handler


# ---------------------------------------------------------------------------
# Build registry
# ---------------------------------------------------------------------------

def build_registry(workspace: Path, memory_dir: Path) -> ToolRegistry:
    """Create a registry with all active tools."""
    reg = ToolRegistry()

    reg.register(Tool(
        name="python_exec",
        description=(
            "Execute Python code in a sandboxed environment. "
            "Use print() to produce output. "
            "Available workspace functions: get_file, get_lines, list_dir, search_files, now. "
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
            },
            "required": ["code"],
        },
        handler=_make_python_exec_handler(workspace),
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
                    "description": "Entry key name (e.g. 'structure', 'preferred_format')",
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
        name="knowledge_search",
        description=(
            "Search accumulated knowledge from past tasks. "
            "Returns observations and patterns. "
            "Use BEFORE starting a task to check for known patterns."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "domain": {"type": "string", "description": "Optional domain filter"},
            },
            "required": ["query"],
        },
        handler=_make_knowledge_search_handler(),
    ))

    return reg
