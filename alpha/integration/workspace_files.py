"""Workspace operations — ripgrep, now.

Integration module providing ripgrep-powered content search
and current time.
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

_workspace: Path = Path.cwd()


def _validate_path(relpath: str) -> Path:
    """Resolve a relative path and ensure it stays inside the workspace."""
    if relpath.startswith("/"):
        raise ValueError(f"absolute paths not allowed: {relpath}")
    resolved = (_workspace / relpath).resolve()
    try:
        resolved.relative_to(_workspace.resolve())
    except ValueError:
        raise ValueError(f"path escapes workspace: {relpath}")
    return resolved


# ---------------------------------------------------------------------------
# ripgrep
# ---------------------------------------------------------------------------


def ripgrep(
    pattern: str,
    path: str = ".",
    file_glob: str = "*",
    fixed_strings: bool = False,
    case_sensitive: bool = False,
    word_boundary: bool = False,
    context_lines: int = 0,
    max_results: int = 50,
) -> str:
    """Search file contents using ripgrep. Returns file:line:content matches.

    Powered by ripgrep (rg) — supports full Rust regex syntax, smart-case,
    word boundaries, context lines, and glob-based file filtering.

    Args:
        pattern: Search pattern. Rust regex by default, or literal if fixed_strings=True.
        path: Directory to search, relative to workspace. Default '.'.
        file_glob: Glob to filter filenames, e.g. '*.py', '*.md'. Default '*'.
        fixed_strings: If True, treat pattern as literal text, not regex. Default False.
        case_sensitive: If True, force case-sensitive. Default False (smart-case:
                        case-insensitive unless pattern has uppercase).
        word_boundary: If True, match whole words only. Default False.
        context_lines: Number of context lines before and after each match. Default 0.
        max_results: Maximum matches to return. Default 50.

    Examples:
        ripgrep(r'def \\w+\\(', path='src', file_glob='*.py')
        ripgrep('config["database"]', fixed_strings=True)
        ripgrep('error', file_glob='*.log', word_boundary=True)
        ripgrep('TODO', file_glob='*.py', context_lines=2)
        ripgrep('MAX_RETRIES', case_sensitive=True)
    """
    rg_bin = shutil.which("rg")
    if not rg_bin:
        return "Error: ripgrep (rg) not found on PATH"

    try:
        resolved = _validate_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not resolved.is_dir():
        return f"Error: not a directory: {path}"

    args = [
        rg_bin,
        "--no-heading",
        "--line-number",
        "--color", "never",
        "--field-context-separator", ":",
        "--glob", "!.git",
        "--glob", "!.*",
        "--glob", file_glob,
    ]
    if fixed_strings:
        args.append("--fixed-strings")
    if case_sensitive:
        args.append("--case-sensitive")
    else:
        args.append("--smart-case")
    if word_boundary:
        args.append("--word-regexp")
    if context_lines > 0:
        args.extend(["--context", str(min(context_lines, 5))])
    args.extend(["-e", pattern, str(resolved)])

    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "Error: search timed out after 15s - use a more specific pattern"
    except Exception as e:
        return f"Error running ripgrep: {e}"

    if proc.returncode == 1:
        return "(no matches)"
    if proc.returncode == 2:
        err = proc.stderr.strip()
        return f"Error: ripgrep: {err}" if err else "Error: ripgrep failed"

    ws_resolved = _workspace.resolve()
    results = []
    for line in proc.stdout.splitlines():
        if line == "--":
            results.append("--")
            continue
        try:
            colon1 = line.index(":")
            rest = line[colon1 + 1:]
            colon2 = rest.index(":")
            lineno = rest[:colon2]
            if not lineno.isdigit():
                continue
            content = rest[colon2 + 1:]
            abs_path = line[:colon1]
            rel = os.path.relpath(abs_path, ws_resolved)
            results.append(f"{rel}:{lineno}: {content.rstrip()}")
        except (ValueError, Exception):
            continue
        if len(results) >= max_results:
            results.append(f"... (truncated at {max_results})")
            break
    if not results:
        return "(no matches)"
    return "\n".join(results)


# ---------------------------------------------------------------------------
# now
# ---------------------------------------------------------------------------


def now() -> str:
    """Returns the current date and time as ISO string."""
    return datetime.datetime.now().isoformat()


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
## Workspace Search Functions

ripgrep(pattern, path=".", file_glob="*", ...)  — Search file contents using ripgrep (rg). Returns file:line:content string.
now()                                            — Current date and time as ISO string.

ripgrep examples:
  print(ripgrep("class Config", file_glob="*.py"))    # find class definitions
  print(ripgrep("TODO", file_glob="*.py", context_lines=2))  # TODOs with context
  print(ripgrep("import requests", fixed_strings=True))       # literal search
"""


# ---------------------------------------------------------------------------
# Integration registration
# ---------------------------------------------------------------------------


def register(workspace: Path) -> dict:
    """Integration protocol: configure and return metadata."""
    global _workspace
    _workspace = Path(workspace).resolve()
    return {
        "name": "workspace_files",
        "functions": {
            "ripgrep": ripgrep,
            "now": now,
        },
        "system_prompt": SYSTEM_PROMPT,
    }
