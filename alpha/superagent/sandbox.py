"""Sandboxed Python executor with workspace functions.

Uses smolagents' LocalPythonExecutor (AST-based sandbox) with
injected read-only workspace functions.  The LLM cannot import os,
subprocess, pathlib, etc. — it can only use our controlled functions.

Functions available inside the sandbox:
  get_file(path)                          — read a file
  get_lines(path, start, end)             — read specific lines
  list_dir(path, pattern, recursive)      — list directory
  search_files(pattern, path, file_glob)  — regex search in files
  now()                                   — current datetime string
"""

from __future__ import annotations

import datetime
import fnmatch
import logging
import os
import re
from pathlib import Path

from smolagents.local_python_executor import LocalPythonExecutor

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workspace function factories
# ---------------------------------------------------------------------------
# Each factory takes workspace_root and returns a closure.
# The closures are injected into the executor's namespace.
# All paths are validated to stay inside the workspace.


def _validate_path(workspace: Path, relpath: str) -> Path:
    """Resolve a relative path and ensure it stays inside the workspace."""
    # Reject absolute paths
    if relpath.startswith("/"):
        raise ValueError(f"absolute paths not allowed: {relpath}")
    resolved = (workspace / relpath).resolve()
    # Ensure it is inside workspace
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError:
        raise ValueError(f"path escapes workspace: {relpath}")
    return resolved


def _make_get_file(workspace: Path):
    def get_file(path: str) -> str:
        """Read a file from the workspace. Returns content as string.

        Args:
            path: Path relative to workspace root.
        """
        try:
            resolved = _validate_path(workspace, path)
        except ValueError as e:
            return f"Error: {e}"
        if not resolved.exists():
            return f"Error: file not found: {path}"
        if not resolved.is_file():
            return f"Error: not a file: {path}"
        try:
            return resolved.read_text(errors="replace")
        except Exception as e:
            return f"Error reading {path}: {e}"
    return get_file


def _make_get_lines(workspace: Path):
    def get_lines(path: str, start: int, end: int) -> str:
        """Read specific lines from a file. 1-based, inclusive.

        Args:
            path: Path relative to workspace root.
            start: First line number (1-based).
            end: Last line number (inclusive).
        """
        try:
            resolved = _validate_path(workspace, path)
        except ValueError as e:
            return f"Error: {e}"
        if not resolved.exists():
            return f"Error: file not found: {path}"
        try:
            lines = resolved.read_text(errors="replace").splitlines()
            selected = lines[max(0, start - 1):end]
            result = []
            for i, line in enumerate(selected, start=max(1, start)):
                result.append(f"{i}: {line}")
            return "\n".join(result)
        except Exception as e:
            return f"Error reading {path}: {e}"
    return get_lines


def _make_list_dir(workspace: Path):
    def list_dir(path: str = ".", pattern: str = "*", recursive: bool = False) -> str:
        """List directory contents with optional glob pattern.

        Args:
            path: Directory relative to workspace root. Use '.' for root.
            pattern: Glob pattern to filter. Default '*'.
            recursive: If True, search subdirectories.
        """
        try:
            resolved = _validate_path(workspace, path)
        except ValueError as e:
            return f"Error: {e}"
        if not resolved.exists():
            return f"Error: directory not found: {path}"
        if not resolved.is_dir():
            return f"Error: not a directory: {path}"
        try:
            entries = []
            if recursive:
                for root, dirs, files in os.walk(str(resolved)):
                    # Skip hidden directories
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for name in files:
                        if fnmatch.fnmatch(name, pattern):
                            full = Path(root) / name
                            rel = full.relative_to(workspace.resolve())
                            size = full.stat().st_size
                            entries.append(f"{rel}  ({_fmt_size(size)})")
            else:
                for item in sorted(resolved.iterdir()):
                    if item.name.startswith("."):
                        continue
                    if not fnmatch.fnmatch(item.name, pattern):
                        continue
                    kind = "dir" if item.is_dir() else _fmt_size(item.stat().st_size)
                    rel = item.relative_to(workspace.resolve())
                    entries.append(f"{rel}  ({kind})")
            if not entries:
                return "(empty)"
            return "\n".join(entries[:500])  # cap output
        except Exception as e:
            return f"Error listing {path}: {e}"
    return list_dir


def _make_search_files(workspace: Path):
    def search_files(pattern: str, path: str = ".", file_glob: str = "*", max_results: int = 50) -> str:
        """Search for regex pattern in files. Returns file:line:content.

        Args:
            pattern: Regex pattern to search for.
            path: Directory to search, relative to workspace. Default '.'.
            file_glob: Glob to filter filenames. Default '*'.
            max_results: Maximum matches to return. Default 50.
        """
        try:
            resolved = _validate_path(workspace, path)
        except ValueError as e:
            return f"Error: {e}"
        if not resolved.is_dir():
            return f"Error: not a directory: {path}"
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Error: invalid regex: {e}"
        results = []
        for root, dirs, files in os.walk(str(resolved)):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if not fnmatch.fnmatch(fname, file_glob):
                    continue
                full = Path(root) / fname
                rel = full.relative_to(workspace.resolve())
                try:
                    text = full.read_text(errors="replace")
                    for i, line in enumerate(text.splitlines(), 1):
                        if regex.search(line):
                            results.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(results) >= max_results:
                                results.append(f"... (truncated at {max_results})")
                                return "\n".join(results)
                except Exception:
                    continue
        if not results:
            return "(no matches)"
        return "\n".join(results)
    return search_files


def _make_now():
    def now() -> str:
        """Returns the current date and time as ISO string."""
        return datetime.datetime.now().isoformat()
    return now


def _fmt_size(n: int) -> str:
    """Format bytes as human-readable."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ---------------------------------------------------------------------------
# Executor factory
# ---------------------------------------------------------------------------


# The function stubs shown to the LLM in the system prompt
FUNCTION_STUBS = '''
def get_file(path: str) -> str:
    """Read a file from the workspace. Returns content as string.
    Args: path - relative to workspace root."""

def get_lines(path: str, start: int, end: int) -> str:
    """Read specific lines from a file. 1-based, inclusive.
    Args: path, start (1-based), end (inclusive)."""

def list_dir(path: str = ".", pattern: str = "*", recursive: bool = False) -> str:
    """List directory contents.
    Args: path (default '.'), pattern (glob, default '*'), recursive."""

def search_files(pattern: str, path: str = ".", file_glob: str = "*", max_results: int = 50) -> str:
    """Regex search across files. Returns file:line:content matches.
    Args: pattern (regex), path, file_glob, max_results (default 50)."""

def now() -> str:
    """Returns current date and time as ISO string."""
'''.strip()


def make_executor(workspace: Path) -> LocalPythonExecutor:
    """Create a sandboxed executor with workspace functions injected."""
    funcs = {
        "get_file": _make_get_file(workspace),
        "get_lines": _make_get_lines(workspace),
        "list_dir": _make_list_dir(workspace),
        "search_files": _make_search_files(workspace),
        "now": _make_now(),
    }
    executor = LocalPythonExecutor(
        additional_authorized_imports=["json", "csv", "re", "collections", "itertools", "math", "statistics"],
        additional_functions=funcs,
        max_print_outputs_length=10_000,
        timeout_seconds=30,
    )
    executor.send_tools({})  # initializes static_tools with base + our functions
    log.info("sandbox executor created with %d workspace functions", len(funcs))
    return executor
