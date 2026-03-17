"""Tool registry — python_exec via sandboxed AST interpreter.

The agent talks in Python.  File operations are Python functions
available inside the sandbox (get_file, list_dir, etc.).
The sandbox blocks os, subprocess, pathlib, open() — the agent
can only access files through our controlled functions.

Active tool:
  python_exec  — execute Python in smolagents AST sandbox

Commented out for later:
  memory_update    — update working memory blocks
  knowledge_search — search accumulated knowledge
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .sandbox import make_executor, FUNCTION_STUBS

log = logging.getLogger(__name__)

# Handler signature: (args: dict, context: dict) -> str
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
    """Create the python_exec handler with a persistent sandboxed executor."""
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
# Build registry
# ---------------------------------------------------------------------------

def build_registry(workspace: Path) -> ToolRegistry:
    """Create a registry with active tools."""
    reg = ToolRegistry()

    reg.register(Tool(
        name="python_exec",
        description=(
            "Execute Python code in a sandboxed environment. "
            "Use print() to produce output. "
            "Available workspace functions: get_file, get_lines, list_dir, search_files, now. "
            "Standard modules: json, csv, re, collections, itertools, math, statistics. "
            "State persists between calls — variables from one call are available in the next."
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

    # --- future tools (not sent to model until implemented) ---
    #
    # reg.register(Tool(
    #     name="memory_update",
    #     description="Update a working memory block.",
    #     schema={...},
    #     handler=_make_memory_update_handler(memory_dir),
    # ))
    #
    # reg.register(Tool(
    #     name="knowledge_search",
    #     description="Search accumulated knowledge.",
    #     schema={...},
    #     handler=_make_knowledge_search_handler(knowledge_dir),
    # ))

    return reg
