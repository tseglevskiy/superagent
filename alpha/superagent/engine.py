"""Engine — stateless disk-first agentic loop.

The core principle: NO in-memory state.

Every turn:
  1. Read session JSONL from disk  (conversation history)
  2. Read memory block files from disk  (working memory)
  3. Compile system prompt + history into messages
  4. Call LLM
  5. Write assistant response to session JSONL
  6. If tool calls → execute, write results to JSONL, goto 1
  7. Display response

Kill the process, restart, everything continues from the JSONL.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from .bus import EventBus
from .config import Config
from .llm import LLMClient, LLMResponse, ToolCall
from .knowledge import KnowledgeStore, get_functions
from .memory import compile_blocks_xml, ensure_block_files
from .tools import ToolRegistry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Debug output — clean, focused, no logging framework noise
# ---------------------------------------------------------------------------

_verbose = False

DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def set_verbose(on: bool) -> None:
    global _verbose
    _verbose = on


def _dbg(prefix: str, text: str) -> None:
    """Print a debug line if verbose mode is on."""
    if _verbose:
        print(f"{DIM}{prefix}{RESET} {text}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Session JSONL — append-only message log
# ---------------------------------------------------------------------------


def append_message(session_file: Path, msg: dict) -> None:
    """Append a message to the session JSONL.  Creates file if needed."""
    msg_with_ts = {**msg, "ts": time.time()}
    with open(session_file, "a") as f:
        f.write(json.dumps(msg_with_ts, ensure_ascii=False) + "\n")


def load_history(session_file: Path) -> list[dict]:
    """Load all messages from the session JSONL."""
    if not session_file.exists():
        return []
    messages = []
    for line in session_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg.pop("ts", None)
        messages.append(msg)
    return messages


# ---------------------------------------------------------------------------
# System prompt compilation
# ---------------------------------------------------------------------------


def _compile_observations_section(knowledge_dir) -> str:
    """Load active observations and render as a context section.

    All symbols (variables and functions) are shown with ID suffix
    so the LLM knows the exact callable/accessible names in the sandbox.
    """
    store = KnowledgeStore(knowledge_dir)
    observations = store.load_all_active()
    if not observations:
        return ""
    parts = ["<observations>"]
    parts.append("<!-- All names below have an ID suffix. Use the suffixed name in python_exec. -->")
    parts.append("<!-- If an observation is outdated, call retire_observation with its ID. -->")
    for obs in observations:
        sid = obs.short_id
        parts.append(f'<observation id="{obs.id}" domain="{obs.domain}" created="{obs.created_at}">')
        # Suffix all top-level names (variables and functions)
        import re as _re
        content = obs.content
        # Suffix function definitions
        content = _re.sub(r'^(def )(\w+)(\()', lambda m: f"{m.group(1)}{m.group(2)}_{sid}{m.group(3)}", content, flags=_re.MULTILINE)
        # Suffix top-level variable assignments (name = ...)
        content = _re.sub(r'^(\w+)( = )', lambda m: f"{m.group(1)}_{sid}{m.group(2)}", content, flags=_re.MULTILINE)
        parts.append(content.rstrip())
        parts.append("</observation>")
    parts.append("</observations>")
    return "\n".join(parts)


# Module-level storage for integration prompts, set by __main__.py at startup
_integration_prompts: str = ""


def set_integration_prompts(prompts: str) -> None:
    """Set the integration system prompts. Called once at startup."""
    global _integration_prompts
    _integration_prompts = prompts


def compile_system_prompt(cfg: Config) -> str:
    """Build the full system prompt from disk files + integration prompts."""
    memory_xml = compile_blocks_xml(cfg.memory_dir)
    domain_section = ""
    observations_section = _compile_observations_section(cfg.knowledge_dir)

    budget_section = (
        "<budget_info>\n"
        "  <context_usage>estimating...</context_usage>\n"
        "  <session_cost>$0.00</session_cost>\n"
        "</budget_info>"
    )

    return (
        f"You are a file workspace assistant. You help the user manage, "
        f"analyze, and organize files in their workspace at {cfg.workspace}.\n"
        f"\n"
        f"You interact with the workspace by writing Python code via the python_exec tool. "
        f"The code runs in a secure sandbox. You CANNOT use open(), os, pathlib, subprocess. "
        f"You MUST use the provided functions below.\n"
        f"\n"
        f"RULES:\n"
        f"- Use python_exec for ALL workspace interactions.\n"
        f"- Always use print() to show results to the user.\n"
        f"- State persists between python_exec calls — variables survive.\n"
        f"- When you discover something important, save it with memory_update.\n"
        f"- If you find that an observation in <observations> is outdated or wrong, "
        f"call retire_observation immediately with its ID.\n"
        f"- Be concise. Show results, not process.\n"
        f"\n"
        f"FEEDBACK TOOLS — USE THEM:\n"
        f"- moan: ALWAYS call this when you hit a capability gap, a missing function, a sandbox\n"
        f"  restriction that blocks the user's request, a confusing error, or anything that forced\n"
        f"  you to tell the user 'I can't do this.' Even if you provide a workaround, still moan.\n"
        f"  Example: user asks you to run git commands but subprocess is blocked — call moan\n"
        f"  with category='missing_function' BEFORE telling the user you can't do it.\n"
        f"- confirm_knowledge: call when your current work independently confirms something\n"
        f"  recorded in an observation from <observations>.\n"
        f"- use_knowledge: call when an observation was essential for your reasoning —\n"
        f"  you could not have reached your conclusion without it.\n"
        f"\n"
        f"FILE LOOKUP:\n"
        f"- If read() raises FileNotFoundError, search the WHOLE workspace with find(\"**/<name>*\")\n"
        f"  before telling the user the file doesn't exist. Files are often in subdirectories.\n"
        f"- Also try ripgrep for content-based search if the filename is ambiguous.\n"
        f"\n"
        f"FILE READING — PROCESS IN MEMORY, DON'T PRINT CHUNKS:\n"
        f"- read() returns a File object with .content — the FULL text is already in memory.\n"
        f"- NEVER print large files in chunks like print(f.content[:5000]) then print(f.content[5000:10000]).\n"
        f"  Each print() is an inference round-trip. Reading a 60KB file in 5KB chunks = 12 wasted calls.\n"
        f"- Instead, process files IN MEMORY in a single python_exec call:\n"
        f"  f = read('file.md'); lines = f.content.splitlines()  # then extract, count, filter, etc.\n"
        f"- Only print() RESULTS: summaries, extracted data, computed answers — not raw file content.\n"
        f"- If you need to understand a file's structure, use f.grep(), f.lines(), or write Python to parse it.\n"
        f"- Print output is limited to 10K characters by default as a safety measure against accidental dumps.\n"
        f"  If you know the size and intentionally need more, pass max_output to python_exec:\n"
        f"  python_exec(code=\"print(f.content)\", max_output=80000)  # override for this call only\n"
        f"\n"
        f"WRITING AND CREATIVE TASKS:\n"
        f"- When asked to create a document, DON'T just collect and reorganize existing text.\n"
        f"- First, decide what UNIQUE VALUE the new document should provide — what insight, structure,\n"
        f"  or perspective doesn't exist in the source material?\n"
        f"- Plan the output's thesis and structure BEFORE gathering data. Write the outline first.\n"
        f"- Cross-reference sources to find patterns, contradictions, or gaps — that's the original contribution.\n"
        f"- Gather data efficiently: one python_exec call to extract what you need from multiple files,\n"
        f"  not one call per file.\n"
        f"- Produce the deliverable. Don't spend all your budget on data collection.\n"
        f"\n"
        f"{_integration_prompts}\n"
        f"\n"
        f"ALLOWED MODULES: json, csv, re, collections, itertools, math, statistics\n"
        f"\n"
        f"EXAMPLES:\n"
        f"```python\n"
        f"# Browse a directory\n"
        f"print(read(\"research/concepts\"))\n"
        f"```\n"
        f"```python\n"
        f"# Find and iterate over files\n"
        f"for path in find(\"**/_index.md\"):\n"
        f"    print(path)\n"
        f"```\n"
        f"```python\n"
        f"# Read and analyze a file — process in memory, print results\n"
        f"f = read(\"README.md\")\n"
        f"print(f\"Lines: {{len(f.content.splitlines())}}, Size: {{len(f.content)}} chars\")\n"
        f"print(f.grep(\"## \"))  # find section headings\n"
        f"```\n"
        f"```python\n"
        f"# Extract data from multiple files in one call\n"
        f"data = {{}}\n"
        f"for path in find(\"**/_index.md\", path=\"research/concepts\"):\n"
        f"    f = read(path)\n"
        f"    title = next((l.lstrip(\"#\").strip() for l in f.content.splitlines() if l.startswith(\"# \")), \"\")\n"
        f"    data[path] = {{\"title\": title, \"lines\": len(f.content.splitlines())}}\n"
        f"print(json.dumps(data, indent=2))\n"
        f"```\n"
        f"```python\n"
        f"# Search file contents\n"
        f"print(ripgrep(\"TODO\", file_glob=\"*.md\"))\n"
        f"```\n"
        f"```python\n"
        f"# Edit a file\n"
        f"edit(\"src/app.py\", old=\"return hello\", new=\"return world\")\n"
        f"```\n"
        f"\n"
        f"{memory_xml}\n"
        f"\n"
        f"{observations_section}\n"
        f"\n"
        f"{domain_section}"
        f"{budget_section}"
    )


# ---------------------------------------------------------------------------
# The turn: one full read-call-write cycle
# ---------------------------------------------------------------------------


def run_turn(
    cfg: Config,
    client: LLMClient,
    registry: ToolRegistry,
    bus: EventBus,
) -> str | None:
    """Execute one complete turn.  Returns the assistant's text response,
    or None if the conversation ended with a tool call (more turns needed).
    """
    system_prompt = compile_system_prompt(cfg)
    history = load_history(cfg.session_file)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    tool_schemas = registry.openai_schemas()

    # Show the last message going to the LLM
    if history:
        last = history[-1]
        role = last.get("role", "?")
        content = last.get("content", "")
        if role == "user":
            _dbg("-> user:", content[:200])
        elif role == "tool":
            _dbg("-> tool result:", content[:200])

    # Call LLM
    bus.emit("llm_call_start", {"msg_count": len(messages)})
    try:
        response = client.call(messages, tools=tool_schemas if tool_schemas else None)
    except Exception as e:
        bus.emit("llm_call_error", {"error": str(e)})
        return f"[LLM error: {e}]"

    _dbg("<- llm:", f"in={response.input_tokens} out={response.output_tokens} stop={response.stop_reason}")

    bus.emit("llm_call_end", {
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "model": response.model,
        "has_tool_calls": response.has_tool_calls,
    })

    if response.has_tool_calls:
        # Show the LLM's thinking text (if any) before tool calls
        if response.content:
            _dbg("<- thinking:", response.content[:300])

        # Write assistant message with tool calls
        tc_dicts = []
        for tc in response.tool_calls:
            tc_dicts.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            })
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": tc_dicts,
        }
        append_message(cfg.session_file, assistant_msg)

        # Execute each tool call
        for tc in response.tool_calls:
            # Show tool call details
            if tc.name == "python_exec":
                code = tc.arguments.get("code", "")
                _dbg("== python_exec:", "")
                for line in code.splitlines():
                    _dbg("  |", line)
            elif tc.name == "memory_update":
                _dbg("== memory_update:", f'{tc.arguments.get("label")}.{tc.arguments.get("key")} = {tc.arguments.get("value", "")[:100]}')
            elif tc.name == "knowledge_search":
                _dbg("== knowledge_search:", f'query="{tc.arguments.get("query")}" domain={tc.arguments.get("domain", "all")}')
            elif tc.name == "retire_observation":
                _dbg("== retire_observation:", tc.arguments.get("observation_id", ""))
            elif tc.name == "moan":
                _dbg("== moan:", f'[{tc.arguments.get("category", "general")}] {tc.arguments.get("message", "")[:120]}')
            elif tc.name in ("confirm_knowledge", "use_knowledge"):
                _dbg(f"== {tc.name}:", f'{tc.arguments.get("observation_id", "")} - {tc.arguments.get("reason", "")[:100]}')
            else:
                _dbg(f"== {tc.name}:", str(tc.arguments)[:200])

            bus.emit("tool_call_start", {"name": tc.name, "args": tc.arguments})
            result = registry.dispatch(
                tc.name,
                tc.arguments,
                {"workspace": str(cfg.workspace), "memory_dir": str(cfg.memory_dir)},
            )

            # Show function output
            _dbg("== result:", result[:500])

            bus.emit("tool_call_end", {"name": tc.name, "result_len": len(result)})
            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            }
            append_message(cfg.session_file, tool_msg)

        return None
    else:
        assistant_msg = {
            "role": "assistant",
            "content": response.content or "",
        }
        append_message(cfg.session_file, assistant_msg)
        return response.content or ""


def run_agent_turn(
    cfg: Config,
    client: LLMClient,
    registry: ToolRegistry,
    bus: EventBus,
    *,
    max_tool_rounds: int = 20,
) -> str:
    """Run turns until the agent produces a text response."""
    for i in range(max_tool_rounds):
        result = run_turn(cfg, client, registry, bus)
        if result is not None:
            return result
    return "[max tool rounds reached]"


# ---------------------------------------------------------------------------
# User message ingestion
# ---------------------------------------------------------------------------


def add_user_message(cfg: Config, text: str) -> None:
    append_message(cfg.session_file, {"role": "user", "content": text})


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def new_session(cfg: Config) -> None:
    if cfg.session_file.exists() and cfg.session_file.stat().st_size > 0:
        ts = time.strftime("%Y%m%dT%H%M%S")
        archive = cfg.sessions_dir / f"session-{ts}.jsonl"
        cfg.session_file.rename(archive)
    cfg.session_file.touch()


def session_message_count(cfg: Config) -> int:
    if not cfg.session_file.exists():
        return 0
    return sum(1 for line in cfg.session_file.read_text().splitlines() if line.strip())
