"""Sandboxed Python executor with workspace functions.

Uses smolagents' LocalPythonExecutor (AST-based sandbox) with
injected read-only workspace functions.  The LLM cannot import os,
subprocess, pathlib, etc. — it can only use our controlled functions.

Functions available inside the sandbox:
  get_file(path)                          — read a file
  get_lines(path, start, end)             — read specific lines
  list_dir(path, pattern, recursive)      — list directory
  search_files(...)                       — ripgrep-powered regex search
  now()                                   — current datetime string
"""

from __future__ import annotations

import datetime
import fnmatch
import logging
import os
import shutil
import subprocess
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
    rg_bin = shutil.which("rg")
    if not rg_bin:
        raise RuntimeError("ripgrep (rg) is required but not found on PATH")

    def search_files(
        pattern: str,
        path: str = ".",
        file_glob: str = "*",
        fixed_strings: bool = False,
        case_sensitive: bool = False,
        word_boundary: bool = False,
        context_lines: int = 0,
        max_results: int = 50,
    ) -> str:
        """Search files using ripgrep. Returns file:line:content matches.

        Powered by ripgrep — supports full Rust regex syntax, smart-case,
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
        """
        try:
            resolved = _validate_path(workspace, path)
        except ValueError as e:
            return f"Error: {e}"
        if not resolved.is_dir():
            return f"Error: not a directory: {path}"

        args = [
            rg_bin,
            "--no-heading",
            "--line-number",
            "--color", "never",
            "--field-context-separator", ":",  # unify match/context separators
            "--glob", "!.git",        # always exclude .git
            "--glob", "!.*",          # skip other hidden dirs/files
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

        ws_resolved = workspace.resolve()
        results = []
        for line in proc.stdout.splitlines():
            # Context group separator from --context
            if line == "--":
                results.append("--")
                continue
            # Format (unified by --field-context-separator):
            #   absolute_path:lineno:content
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

def search_files(pattern: str, path: str = ".", file_glob: str = "*",
                 fixed_strings: bool = False, case_sensitive: bool = False,
                 word_boundary: bool = False, context_lines: int = 0,
                 max_results: int = 50) -> str:
    """Ripgrep-powered search across files. Returns file:line:content matches.

    Always searches recursively into subdirectories. Automatically skips
    binary files, hidden files/dirs, and .git. Supports Rust regex syntax
    by default. Smart-case: lowercase patterns are case-insensitive,
    patterns with any uppercase letter are case-sensitive.

    Args:
      pattern       - regex pattern (default) or literal text (if fixed_strings=True).
      path          - directory to search, relative to workspace (default '.').
      file_glob     - glob to filter filenames (default '*').
      fixed_strings - treat pattern as literal text, not regex.
      case_sensitive - force case-sensitive search (overrides smart-case).
      word_boundary  - match whole words only (e.g. 'log' won't match 'logging').
      context_lines  - lines of context before/after each match, 0-5.
      max_results    - max matches to return (default 50).

    Examples:
      # Find function definitions in Python files
      search_files(r'def \w+\(', path='src', file_glob='*.py')

      # Literal text search (no regex escaping needed)
      search_files('config["database"]', fixed_strings=True)

      # Whole-word search to avoid partial matches
      search_files('error', file_glob='*.log', word_boundary=True)

      # Get surrounding context to understand matches
      search_files('TODO', file_glob='*.py', context_lines=2)

      # Case-sensitive search for a constant name
      search_files('MAX_RETRIES', case_sensitive=True)

      # Regex alternation
      search_files('class (User|Account|Session)', file_glob='*.py')

      # Search only markdown files in a specific directory
      search_files('agentic loop', path='research/concepts', file_glob='*.md')"""

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
