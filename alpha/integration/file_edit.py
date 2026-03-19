"""
File Editing API for Code-as-Action Agents.

Provides file editing primitives injected into the agent's Python execution namespace.
All functions use singleton File handles with write-back buffers and atomic writes.

Usage: inject SYSTEM_PROMPT into the agent's system message, then inject all public
functions (read, edit, write, insert, replace_lines, edit_regex, append, batch, delete,
exists, find, grep) into the agent's exec() namespace.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from difflib import SequenceMatcher, unified_diff
from pathlib import Path
from textwrap import dedent


# ---------------------------------------------------------------------------
# System prompt – inject this into the LLM's system message
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
## File Editing Functions

f = read(path)                           – Read a file. Returns a File object with .content, f[line], f.lines(start,end), f.grep(pattern).
edit(path_or_file, old, new)             – Find and replace text. Fuzzy matching handles indentation errors. Accepts path string or File.
  edit(..., dotdotdot=True)              – Use ... as wildcard in old only: prefix... (rest of line), ...suffix (start of line), ... alone (skip lines). new replaces entire match.
write(path, content)                     – Create a new file. Raises if file exists; use overwrite=True to replace.
insert(file_or_path, after, content)     – Insert text after a line number.
replace_lines(file_or_path, start, end, content) – Replace a range of lines.
edit_regex(path_or_file, pattern, replacement)   – Regex find and replace.
with batch():                            – Wrap multiple edits for atomic all-or-nothing application.
delete(path)                             – Delete a file from disk.
find(pattern, path=".", depth=0)         – Find files and dirs by glob. Returns list[str]. Dirs end with '/'.
  find("*")                              – top-level entries only
  find("**/_index.md")                   – all index files (discover document structure)
  find("**/*.py", depth=2)               – Python files up to 2 levels deep
  find("**/*.md", path="research/concepts") – markdown in a subtree
  Raises RuntimeError if >100 results (use depth or narrower path to limit).

Guidelines:
- Use edit() for most changes – works with just a path string, no read() needed.
- For line-number operations (insert, replace_lines), use read() first to get a File handle.
- Use write() only for new files or complete rewrites.
- Use batch() when changing multiple files together – all-or-nothing.
- batch() can be nested safely: inner batch() is transparent, only outermost flushes to disk.
- read() returns a singleton live handle – f.content and f[n] always reflect the latest state.
- If edit() reports multiple matches, add more surrounding context to old.
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EditError(Exception):
    """Base class for all file editing errors."""

    def __init__(self, path: str, message: str, suggestion: str = ""):
        self.path = path
        self.message = message
        self.suggestion = suggestion
        super().__init__(f"{path}: {message}" + (f"\nSuggestion: {suggestion}" if suggestion else ""))


class NoMatchError(EditError):
    """old text not found in file after all fuzzy strategies."""
    pass


class MultipleMatchError(EditError):
    """old text matches 2+ locations and all=False."""
    pass


class NoChangeError(EditError):
    """old == new, nothing to do."""
    pass


class FileModifiedError(EditError):
    """File was modified externally since last read/flush."""
    pass


class FileDeletedError(EditError):
    """File was deleted externally while a handle exists."""
    pass


class BatchError(EditError):
    """One or more edits in batch() failed."""

    def __init__(self, path: str, message: str, *,
                 failed_operation: dict | None = None,
                 original_error: Exception | None = None,
                 completed: list | None = None):
        super().__init__(path, message)
        self.failed_operation = failed_operation
        self.original_error = original_error
        self.completed = completed or []


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class EditResult:
    """Result of an edit/insert/replace_lines/edit_regex/append operation.

    Attributes:
        path:           Relative path to the edited file.
        ok:             True if the edit was applied successfully.
        diff:           Unified diff preview of the change.
        matches_found:  How many locations matched old in the file.
        lines_changed:  Net line count change (positive = added, negative = removed).
    """
    path: str
    ok: bool
    diff: str
    matches_found: int = 1
    lines_changed: int = 0


@dataclass
class WriteResult:
    """Result of a write() operation.

    Attributes:
        path:     Relative path to the written file.
        ok:       True if the write succeeded.
        created:  True if a new file was created, False if overwritten.
        size:     Number of bytes written.
        diff:     Unified diff if overwrite, None if new file.
    """
    path: str
    ok: bool
    created: bool
    size: int
    diff: str | None = None


@dataclass
class BatchResult:
    """Result of a batch() context manager.

    Attributes:
        ok:               True if all edits succeeded and were flushed.
        files_changed:    Number of files modified.
        total_additions:  Total lines added across all files.
        total_deletions:  Total lines removed across all files.
        per_file:         Per-file EditResult list.
    """
    ok: bool
    files_changed: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    per_file: list[EditResult] = field(default_factory=list)




@dataclass
class GrepMatch:
    """A single match from grep().

    Attributes:
        file:            Path to the file containing the match.
        line:            1-indexed line number of the match.
        text:            The matched line text.
        context_before:  Lines before the match.
        context_after:   Lines after the match.
    """
    file: str
    line: int
    text: str
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File handle
# ---------------------------------------------------------------------------

class File:
    """Singleton live handle for a file. Returned by read().

    The handle is a write-back buffer: .content always reflects the latest state
    including all edits (even pending batch changes). Line endings are always
    normalized to '\\n' for the agent. On flush, content is converted to the
    git-expected line ending style.

    Access patterns:
        f.content      – full file text (\\n-normalized)
        f[15]          – line 15 (1-indexed)
        f.lines(10,20) – lines 10-20
        f.grep("pat")  – lines matching pattern with context
        f.line_count   – total number of lines
        str(f)         – same as f.content
    """

    def __init__(self, path: str, workspace: Path):
        self.path = path
        self._workspace = workspace
        self._abs = workspace / path
        self._content: str | None = None
        self._mtime: float | None = None
        self._line_ending: str | None = None  # resolved lazily on first modification
        self._dirty = False
        self._pre_batch_snapshot: str | None = None  # for rollback

    def _load(self) -> None:
        """Read file from disk, normalize line endings, record mtime."""
        raw = self._abs.read_bytes()
        self._mtime = os.stat(self._abs).st_mtime
        text = raw.decode("utf-8", errors="replace")
        # normalize all line endings to \n
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self._content = text

    def _reload_from_disk(self) -> None:
        """Re-read from disk. Raises FileDeletedError if file is gone."""
        if not self._abs.exists():
            raise FileDeletedError(
                self.path,
                "File was deleted from disk.",
                suggestion="Use write() to recreate the file, or check if deletion was intentional.",
            )
        self._load()

    def _resolve_line_ending(self) -> str:
        """Lazily query git for expected line ending on first modification."""
        if self._line_ending is not None:
            return self._line_ending
        try:
            result = subprocess.run(
                ["git", "check-attr", "eol", "--", self.path],
                capture_output=True, text=True, cwd=self._workspace, timeout=5,
            )
            # parse "path: eol: lf" or "path: eol: crlf" or "path: eol: unset"
            parts = result.stdout.strip().rsplit(": ", 1)
            val = parts[-1].strip() if parts else ""
            if val == "crlf":
                self._line_ending = "\r\n"
            elif val == "lf":
                self._line_ending = "\n"
            else:
                self._line_ending = "\n"  # default
        except Exception:
            self._line_ending = "\n"
        return self._line_ending

    def _flush(self) -> None:
        """Write buffer to disk atomically with mtime check."""
        if self._content is None:
            return
        # resolve line ending lazily
        eol = self._resolve_line_ending()
        # convert \n to expected eol
        out = self._content
        if eol != "\n":
            out = out.replace("\n", eol)
        out_bytes = out.encode("utf-8")
        # mtime check
        if self._mtime is not None:
            try:
                current_mtime = os.stat(self._abs).st_mtime
            except FileNotFoundError:
                raise FileDeletedError(
                    self.path,
                    "File was deleted externally before flush.",
                    suggestion="The dirty buffer is preserved. Use write() to recreate.",
                )
            if current_mtime != self._mtime:
                raise FileModifiedError(
                    self.path,
                    "File was modified externally since last read/flush.",
                    suggestion='Use read(path, refresh=True) to reload from disk.',
                )
        # atomic write: temp + rename
        self._abs.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._abs.parent, suffix=".tmp")
        try:
            os.write(fd, out_bytes)
            os.close(fd)
            os.rename(tmp, self._abs)
        except Exception:
            os.close(fd) if not os.get_inheritable(fd) else None
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._mtime = os.stat(self._abs).st_mtime
        self._dirty = False

    @property
    def content(self) -> str:
        """Full file content, always \\n-normalized. Lazy-loads from disk if evicted."""
        if self._content is None:
            self._reload_from_disk()
        return self._content  # type: ignore

    @content.setter
    def content(self, value: str) -> None:
        self._content = value
        self._dirty = True

    @property
    def line_count(self) -> int:
        """Total number of lines in the file."""
        return len(self.content.splitlines())

    def __str__(self) -> str:
        return self.content

    def __repr__(self) -> str:
        return f"File({self.path!r}, {self.line_count} lines)"

    def __getitem__(self, n: int) -> str:
        """Return line n (1-indexed)."""
        lines = self.content.splitlines()
        if n < 1 or n > len(lines):
            raise IndexError(f"Line {n} out of range (1-{len(lines)})")
        return lines[n - 1]

    def lines(self, start: int, end: int) -> str:
        """Return lines start..end (1-indexed, inclusive). Use -1 for end-of-file."""
        all_lines = self.content.splitlines()
        if end == -1:
            end = len(all_lines)
        if start < 1 or end > len(all_lines) or start > end:
            raise ValueError(f"Invalid range {start}-{end} for file with {len(all_lines)} lines")
        selected = all_lines[start - 1:end]
        return "\n".join(f"{start + i:>4}| {line}" for i, line in enumerate(selected))

    def grep(self, pattern: str, context: int = 5) -> str:
        """Find lines matching pattern, return with surrounding context."""
        all_lines = self.content.splitlines()
        results = []
        for i, line in enumerate(all_lines):
            if pattern in line:
                start = max(0, i - context)
                end = min(len(all_lines), i + context + 1)
                chunk = []
                for j in range(start, end):
                    marker = " >> " if j == i else "    "
                    chunk.append(f"{j + 1:>4}{marker}{all_lines[j]}")
                results.append("\n".join(chunk))
        return "\n---\n".join(results) if results else f"No matches for {pattern!r}"


# ---------------------------------------------------------------------------
# Registry and batch state
# ---------------------------------------------------------------------------

_registry: dict[str, File] = {}
_workspace: Path = Path.cwd()
_batch_depth = 0
_batch_mode = False
_batch_completed: list[dict] = []
_lock = threading.Lock()


def _get_handle(path_or_file: str | File) -> File:
    """Resolve a path string or File to the singleton handle."""
    if isinstance(path_or_file, File):
        return path_or_file
    path = str(path_or_file)
    if path not in _registry:
        handle = File(path, _workspace)
        handle._load()
        _registry[path] = handle
    return _registry[path]


def _make_diff(path: str, old_text: str, new_text: str) -> str:
    """Generate a unified diff string."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff_lines = unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    return "".join(diff_lines)


def _count_changes(old_text: str, new_text: str) -> int:
    """Count net line change."""
    return len(new_text.splitlines()) - len(old_text.splitlines())


def _should_flush() -> bool:
    """Return True if edits should flush immediately (not in batch mode)."""
    return not _batch_mode


# ---------------------------------------------------------------------------
# Fuzzy match cascade
# ---------------------------------------------------------------------------

def _find_exact(content: str, old: str) -> list[int]:
    """Find all exact occurrences, return start indices."""
    positions = []
    start = 0
    while True:
        idx = content.find(old, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def _match_line_trimmed(content: str, old: str) -> tuple[int, int] | None:
    """Match by trimming each line's leading/trailing whitespace."""
    old_lines = [l.strip() for l in old.splitlines()]
    content_lines = content.splitlines()
    window = len(old_lines)
    for i in range(len(content_lines) - window + 1):
        candidate = [l.strip() for l in content_lines[i:i + window]]
        if candidate == old_lines:
            start = sum(len(l) + 1 for l in content_lines[:i])
            end = sum(len(l) + 1 for l in content_lines[:i + window])
            return start, end
    return None


def _match_indent_flexible(content: str, old: str) -> tuple[int, int, int] | None:
    """Match ignoring common indentation, return (start, end, indent_offset)."""
    old_stripped = dedent(old)
    old_lines = old_stripped.splitlines()
    content_lines = content.splitlines()
    window = len(old_lines)
    for i in range(len(content_lines) - window + 1):
        candidate = content_lines[i:i + window]
        candidate_stripped = dedent("\n".join(candidate)).splitlines()
        if candidate_stripped == old_lines:
            # compute indent offset
            offsets = []
            for cl, ol in zip(candidate, old.splitlines()):
                ci = len(cl) - len(cl.lstrip())
                oi = len(ol) - len(ol.lstrip())
                offsets.append(ci - oi)
            if len(set(offsets)) <= 1:
                offset = offsets[0] if offsets else 0
                start = sum(len(l) + 1 for l in content_lines[:i])
                end = sum(len(l) + 1 for l in content_lines[:i + window])
                return start, end, offset
    return None


def _match_whitespace_normalized(content: str, old: str) -> tuple[int, int] | None:
    """Match after collapsing all whitespace to single spaces."""
    norm_old = re.sub(r"\s+", " ", old)
    content_lines = content.splitlines()
    old_line_count = len(old.splitlines())
    for i in range(len(content_lines) - old_line_count + 1):
        window = "\n".join(content_lines[i:i + old_line_count])
        if re.sub(r"\s+", " ", window) == norm_old:
            start = sum(len(l) + 1 for l in content_lines[:i])
            end = sum(len(l) + 1 for l in content_lines[:i + old_line_count])
            return start, end
    return None


def _find_similar(content: str, old: str, threshold: float = 0.6) -> str:
    """Find the most similar block in content, return context for error message."""
    old_lines = old.splitlines()
    content_lines = content.splitlines()
    window = len(old_lines)
    best_ratio = 0.0
    best_idx = 0
    for i in range(max(1, len(content_lines) - window + 1)):
        candidate = "\n".join(content_lines[i:i + window])
        ratio = SequenceMatcher(None, old, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_idx = i
    if best_ratio >= threshold:
        ctx_start = max(0, best_idx - 3)
        ctx_end = min(len(content_lines), best_idx + window + 3)
        lines = []
        for j in range(ctx_start, ctx_end):
            lines.append(f"{j + 1:>4}| {content_lines[j]}")
        return f"Most similar block (similarity {best_ratio:.0%}):\n" + "\n".join(lines)
    return ""


def _apply_edit(handle: File, old: str, new: str, *, all_occurrences: bool = False,
                dotdotdot: bool = False) -> EditResult:
    """Core edit logic with fuzzy cascade. Modifies handle buffer."""
    content = handle.content
    old_content = content

    if dotdotdot:
        return _apply_dotdotdot_edit(handle, old, new)

    # --- Exact match ---
    positions = _find_exact(content, old)
    if len(positions) == 1 or (len(positions) > 1 and all_occurrences):
        if all_occurrences:
            new_content = content.replace(old, new)
        else:
            idx = positions[0]
            new_content = content[:idx] + new + content[idx + len(old):]
        handle.content = new_content
        return EditResult(
            path=handle.path, ok=True,
            diff=_make_diff(handle.path, old_content, new_content),
            matches_found=len(positions),
            lines_changed=_count_changes(old_content, new_content),
        )
    if len(positions) > 1:
        lines = content.splitlines()
        locs = []
        for pos in positions:
            line_num = content[:pos].count("\n") + 1
            locs.append(f"  line {line_num}: {lines[line_num - 1].strip()}")
        raise MultipleMatchError(
            handle.path,
            f"Found {len(positions)} matches for old text:\n" + "\n".join(locs),
            suggestion="Add more surrounding context to old, or use all=True.",
        )

    # --- Line-trimmed match ---
    result = _match_line_trimmed(content, old)
    if result:
        start, end = result
        matched = content[start:end]
        # preserve original indentation in replacement
        new_content = content[:start] + new + content[end:]
        handle.content = new_content
        return EditResult(
            path=handle.path, ok=True,
            diff=_make_diff(handle.path, old_content, new_content),
            lines_changed=_count_changes(old_content, new_content),
        )

    # --- Indentation-flexible match ---
    result3 = _match_indent_flexible(content, old)
    if result3:
        start, end, offset = result3
        # auto-correct new by the indent offset
        new_lines = []
        for line in new.splitlines():
            if line.strip() and offset != 0:
                if offset > 0:
                    new_lines.append(" " * offset + line)
                else:
                    stripped = line[min(abs(offset), len(line) - len(line.lstrip())):]
                    new_lines.append(stripped)
            else:
                new_lines.append(line)
        corrected_new = "\n".join(new_lines)
        if not old.endswith("\n") and content[start:end].endswith("\n"):
            corrected_new += "\n"
        new_content = content[:start] + corrected_new + content[end:]
        handle.content = new_content
        return EditResult(
            path=handle.path, ok=True,
            diff=_make_diff(handle.path, old_content, new_content),
            lines_changed=_count_changes(old_content, new_content),
        )

    # --- Whitespace-normalized match ---
    result4 = _match_whitespace_normalized(content, old)
    if result4:
        start, end = result4
        new_content = content[:start] + new + content[end:]
        handle.content = new_content
        return EditResult(
            path=handle.path, ok=True,
            diff=_make_diff(handle.path, old_content, new_content),
            lines_changed=_count_changes(old_content, new_content),
        )

    # --- Escape-normalized match ---
    unescaped = old.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r").replace("\\\\", "\\")
    if unescaped != old:
        positions = _find_exact(content, unescaped)
        if len(positions) == 1:
            idx = positions[0]
            new_content = content[:idx] + new + content[idx + len(unescaped):]
            handle.content = new_content
            return EditResult(
                path=handle.path, ok=True,
                diff=_make_diff(handle.path, old_content, new_content),
                lines_changed=_count_changes(old_content, new_content),
            )

    # --- All strategies failed ---
    similar = _find_similar(content, old)
    # check if new already exists
    already = ""
    if new and new in content:
        already = "\nNote: the replacement text already exists in the file - the edit may have been applied previously."
    raise NoMatchError(
        handle.path,
        f"Could not find old text in file.{already}",
        suggestion=(similar + "\n" if similar else "") +
                   "Ensure old matches exactly including whitespace, indentation, and comments.",
    )


def _apply_dotdotdot_edit(handle: File, old: str, new: str) -> EditResult:
    """Handle dotdotdot=True: ... in old acts as wildcard."""
    content = handle.content
    old_content = content
    old_lines = old.splitlines()

    # Build a regex from the old pattern
    # ... at end of line = match rest of line
    # ... at start of line = match start of line
    # ... alone = match any lines
    regex_parts = []
    for line in old_lines:
        stripped = line.strip()
        if stripped == "...":
            regex_parts.append("(.*?)")  # match any lines (non-greedy)
        elif line.endswith("..."):
            prefix = re.escape(line[:-3])
            regex_parts.append(prefix + ".*")
        elif line.startswith("..."):
            suffix = re.escape(line[3:])
            regex_parts.append(".*" + suffix)
        else:
            regex_parts.append(re.escape(line))
    pattern = "\n".join(regex_parts)
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        raise NoMatchError(
            handle.path,
            "Could not find matching region for dotdotdot pattern.",
            suggestion="Check that the anchor lines exist in the file.",
        )
    new_content = content[:match.start()] + new + content[match.end():]
    handle.content = new_content
    return EditResult(
        path=handle.path, ok=True,
        diff=_make_diff(handle.path, old_content, new_content),
        lines_changed=_count_changes(old_content, new_content),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read(path: str, *, lines: tuple[int, int] | None = None,
         grep: str | None = None, refresh: bool = False) -> File | str:
    """Read a file and return its singleton File handle.

    Calling read() on the same path always returns the same object.
    The handle is a live buffer: .content, f[n], f.lines(), f.grep()
    always reflect the latest state including all edits.

    Args:
        path:    Relative path from workspace root.
        lines:   Optional (start, end) line range, 1-indexed inclusive. Use -1 for EOF.
        grep:    Optional search pattern. Returns context around the first match.
        refresh: If True, force re-read from disk (after external modification).

    Returns:
        File object. If path is a directory, returns a listing string instead.

    Raises:
        FileNotFoundError: file does not exist.
        IsADirectoryError: path is a directory and lines or grep was specified.

    Example::

        f = read("src/app.py")
        print(f.content)        # full text
        print(f[15])            # line 15
        print(f.lines(10, 20))  # lines 10-20 with numbers
        print(f.grep("class"))  # context around matches
    """
    abs_path = _workspace / path
    if abs_path.is_dir():
        if lines or grep:
            raise IsADirectoryError(f"{path} is a directory")
        entries = sorted(abs_path.iterdir())
        parts = []
        for e in entries:
            if e.is_dir():
                parts.append(f"d {e.name}/")
            else:
                size = e.stat().st_size
                parts.append(f"- {e.name}  ({_fmt_size(size)})")
        return "\n".join(parts)

    handle = _get_handle(path)
    if refresh:
        handle._reload_from_disk()

    if lines:
        return handle.lines(lines[0], lines[1])
    if grep:
        return handle.grep(grep)
    return handle


def edit(path_or_file: str | File, old: str, new: str = "", *,
         all: bool = False, dotdotdot: bool = False) -> EditResult:
    """Find exact text in a file and replace it. The primary editing tool.

    Uses a 5-strategy fuzzy matching cascade: exact, line-trimmed,
    indentation-flexible, whitespace-normalized, escape-normalized.
    Automatically corrects indentation when the match differs only in indent level.

    No read() required before edit(). The content match itself guards against stale edits.

    Args:
        path_or_file: Path string or File handle from read().
        old:          The exact text to find. Must be non-empty.
        new:          Replacement text. Defaults to "" (deletion).
        all:          If True, replace ALL occurrences. Default requires exactly one match.
        dotdotdot:    If True, ... in old acts as a wildcard (only in old, never in new).
                      prefix... matches rest of line, ...suffix matches start of line,
                      ... alone on a line matches any number of lines.
                      new replaces the ENTIRE matched region.

    Returns:
        EditResult with .diff, .matches_found, .lines_changed.

    Raises:
        NoMatchError:       old not found after all strategies. Includes most-similar-block suggestion.
        MultipleMatchError: old matches 2+ locations and all=False. Lists match locations.
        NoChangeError:      old == new.
        FileNotFoundError:  file does not exist.

    Example::

        edit("app.py", old="return 'hello'", new="return 'world'")
        edit("app.py", old="TODO", new="DONE", all=True)
        edit("app.py", old="def old_name():", new="def new_name():")
    """
    if not old:
        raise ValueError("old must be non-empty")
    if old == new:
        handle = _get_handle(path_or_file)
        raise NoChangeError(handle.path, "old and new are identical, nothing to change.")

    handle = _get_handle(path_or_file)
    result = _apply_edit(handle, old, new, all_occurrences=all, dotdotdot=dotdotdot)

    if _should_flush():
        handle._flush()

    return result


def write(path: str, content: str, *, overwrite: bool = False) -> WriteResult:
    """Create a new file or overwrite an existing one with complete content.

    Creates parent directories automatically.

    Args:
        path:      Relative path from workspace root.
        content:   Complete file content.
        overwrite: If False (default), raises FileExistsError if file exists.

    Returns:
        WriteResult with .created, .size, .diff.

    Raises:
        FileExistsError: file exists and overwrite=False.

    Example::

        write("src/new_module.py", "import os\\n\\ndef main():\\n    pass\\n")
        write("src/app.py", new_content, overwrite=True)
    """
    abs_path = _workspace / path
    existed = abs_path.exists()
    if existed and not overwrite:
        raise FileExistsError(f"{path} already exists. Use overwrite=True to replace.")

    old_content = ""
    if existed:
        old_content = abs_path.read_text(encoding="utf-8", errors="replace")
        old_content = old_content.replace("\r\n", "\n").replace("\r", "\n")

    handle = File(path, _workspace)
    handle.content = content.replace("\r\n", "\n").replace("\r", "\n")
    handle._dirty = True
    _registry[path] = handle

    diff_str = _make_diff(path, old_content, handle.content) if existed else None

    if _should_flush():
        # for new files, skip mtime check
        handle._mtime = None if not existed else os.stat(abs_path).st_mtime
        handle._flush()

    return WriteResult(
        path=path,
        ok=True,
        created=not existed,
        size=len(content.encode("utf-8")),
        diff=diff_str,
    )


def insert(file_or_path: str | File, after: int, content: str) -> EditResult:
    """Insert text after a specific line number.

    Args:
        file_or_path: File handle or path string (resolved to singleton).
        after:        Line number after which to insert. 0 = beginning, 1-indexed.
        content:      Text to insert.

    Returns:
        EditResult with diff preview.

    Raises:
        FileModifiedError: file mtime changed since handle was created.
        ValueError:        after is out of range.

    Example::

        f = read("src/app.py")
        insert(f, after=10, content="    logger.info('called')\\n")
        insert("src/app.py", after=0, content="#!/usr/bin/env python3\\n")
    """
    handle = _get_handle(file_or_path)
    old_content = handle.content
    lines = old_content.splitlines(keepends=True)

    if after < 0 or after > len(lines):
        if after == -1:
            after = len(lines)
        else:
            raise ValueError(f"after={after} out of range (0-{len(lines)})")

    new_lines = lines[:after] + [content if content.endswith("\n") else content + "\n"] + lines[after:]
    new_content = "".join(new_lines)
    handle.content = new_content

    if _should_flush():
        handle._flush()

    return EditResult(
        path=handle.path, ok=True,
        diff=_make_diff(handle.path, old_content, new_content),
        lines_changed=_count_changes(old_content, new_content),
    )


def replace_lines(file_or_path: str | File, start: int, end: int, content: str) -> EditResult:
    """Replace a range of lines with new content.

    Args:
        file_or_path: File handle or path string.
        start:        First line to replace (1-indexed, inclusive).
        end:          Last line to replace (1-indexed, inclusive). Use -1 for EOF.
        content:      Replacement text.

    Returns:
        EditResult with diff preview.

    Raises:
        FileModifiedError: file mtime changed since handle was created.
        ValueError:        start or end out of range.

    Example::

        f = read("src/app.py")
        replace_lines(f, start=15, end=20, content="    new_code()\\n")
    """
    handle = _get_handle(file_or_path)
    old_content = handle.content
    lines = old_content.splitlines(keepends=True)

    if end == -1:
        end = len(lines)
    if start < 1 or end > len(lines) or start > end:
        raise ValueError(f"Invalid range {start}-{end} for file with {len(lines)} lines")

    replacement = [content if content.endswith("\n") else content + "\n"] if content else []
    new_lines = lines[:start - 1] + replacement + lines[end:]
    new_content = "".join(new_lines)
    handle.content = new_content

    if _should_flush():
        handle._flush()

    return EditResult(
        path=handle.path, ok=True,
        diff=_make_diff(handle.path, old_content, new_content),
        lines_changed=_count_changes(old_content, new_content),
    )


def edit_regex(path_or_file: str | File, pattern: str, replacement: str, *,
               count: int = 1) -> EditResult:
    """Regex find and replace.

    Args:
        path_or_file: Path string or File handle.
        pattern:      Regex pattern (Python re syntax).
        replacement:  Replacement string. Supports \\1, \\2 backreferences.
        count:        Max replacements. 1 by default. 0 = replace all.

    Returns:
        EditResult with .matches_found.

    Raises:
        NoMatchError: pattern not found in file.
        re.error:     invalid regex.

    Example::

        edit_regex("setup.py", pattern=r'version = "[\\d.]+"', replacement='version = "2.0.0"')
        edit_regex("app.py", pattern=r"#\\s*TODO:.*$", replacement="", count=0)
    """
    handle = _get_handle(path_or_file)
    old_content = handle.content
    compiled = re.compile(pattern, re.MULTILINE)
    matches = compiled.findall(old_content)
    if not matches:
        raise NoMatchError(handle.path, f"Pattern {pattern!r} not found.", suggestion="Check regex syntax.")
    new_content = compiled.sub(replacement, old_content, count=count if count > 0 else 0)
    handle.content = new_content

    if _should_flush():
        handle._flush()

    return EditResult(
        path=handle.path, ok=True,
        diff=_make_diff(handle.path, old_content, new_content),
        matches_found=len(matches),
        lines_changed=_count_changes(old_content, new_content),
    )


def append(path_or_file: str | File, content: str) -> EditResult:
    """Append text to the end of a file.

    Convenience shorthand for insert(path, after=-1, content=content).

    Example::

        append("src/app.py", "\\n# End of file\\n")
    """
    return insert(path_or_file, after=-1, content=content)


@contextmanager
def batch():
    """Apply multiple edits atomically. All-or-nothing.

    Inside batch(), edit/write/insert/replace_lines modify the in-memory buffer
    (so f[n] reflects changes) but defer flushing to disk. On successful exit,
    all dirty handles are flushed atomically.

    Nested batch() is transparent: only the outermost controls flushing.

    Raises:
        BatchError: one or more edits failed. No files are modified.

    Example::

        with batch():
            edit("src/a.py", old="import foo", new="import bar")
            edit("src/b.py", old="from foo import", new="from bar import")
    """
    global _batch_depth, _batch_mode
    _batch_depth += 1
    is_outermost = _batch_depth == 1

    if is_outermost:
        _batch_mode = True
        # snapshot all existing handles for rollback
        for h in _registry.values():
            h._pre_batch_snapshot = h._content

    try:
        yield
        if is_outermost:
            # flush all dirty handles atomically
            dirty = [h for h in _registry.values() if h._dirty]
            # phase 1: check mtimes
            for h in dirty:
                if h._mtime is not None:
                    try:
                        current = os.stat(h._abs).st_mtime
                    except FileNotFoundError:
                        raise BatchError(h.path, f"File deleted externally: {h.path}")
                    if current != h._mtime:
                        raise BatchError(h.path, f"External modification detected: {h.path}")
            # phase 2: write temps
            temps: dict[str, str] = {}
            for h in dirty:
                eol = h._resolve_line_ending()
                out = h._content or ""
                if eol != "\n":
                    out = out.replace("\n", eol)
                h._abs.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=h._abs.parent, suffix=".tmp")
                os.write(fd, out.encode("utf-8"))
                os.close(fd)
                temps[h.path] = tmp
            # phase 3: rename all
            for h in dirty:
                os.rename(temps[h.path], h._abs)
            # phase 4: update mtimes
            for h in dirty:
                h._mtime = os.stat(h._abs).st_mtime
                h._dirty = False
    except Exception:
        if is_outermost:
            # rollback buffers
            for h in _registry.values():
                if h._pre_batch_snapshot is not None:
                    h._content = h._pre_batch_snapshot
                    h._dirty = False
                h._pre_batch_snapshot = None
        raise
    finally:
        _batch_depth -= 1
        if is_outermost:
            _batch_mode = False
            for h in _registry.values():
                h._pre_batch_snapshot = None


def delete(path: str) -> None:
    """Delete a file from disk and clear its handle from the registry.

    Args:
        path: Relative path to the file.

    Raises:
        FileNotFoundError: file does not exist.

    Example::

        delete("src/obsolete.py")
    """
    abs_path = _workspace / path
    if not abs_path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    abs_path.unlink()
    _registry.pop(path, None)




# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def exists(path: str) -> bool:
    """Check if a file or directory exists.

    Example::

        if exists("src/config.py"):
            f = read("src/config.py")
    """
    return (_workspace / path).exists()


def find(pattern: str, *, path: str = ".", depth: int = 0) -> list[str]:
    """Find files and directories by glob pattern.

    Args:
        pattern: Glob pattern (e.g. "**/*.py", "*", "**/_index.md").
        path:    Directory to search in. Defaults to workspace root.
        depth:   Max directory depth to search. 0 = unlimited, 1 = direct children only,
                 2 = children + grandchildren, etc.

    Returns:
        List of relative paths. Directories end with '/'.

    Raises:
        RuntimeError: more than 100 results found (depth > 1 only). Narrow the query.

    Example::

        find("*")                                # top-level entries (depth 1 implicit)
        find("**/*.py", depth=2)                 # Python files up to 2 levels deep
        find("**/_index.md")                     # discover document structure
        find("**/*.md", path="research/concepts") # markdown in a subtree
    """
    base = _workspace / path
    base_depth = len(base.resolve().parts)
    results = []
    limit = 100
    for p in base.glob(pattern):
        if depth > 0:
            p_depth = len(p.resolve().parts) - base_depth
            if p_depth > depth:
                continue
        rel = str(p.relative_to(_workspace))
        if p.is_dir():
            results.append(rel + "/")
        else:
            results.append(rel)
        # Check limit for deep searches (depth != 1)
        if depth != 1 and len(results) > limit:
            raise RuntimeError(
                f"find() returned more than {limit} results. "
                f"Narrow the query with a more specific pattern, path, or depth parameter."
            )
    return sorted(results)






def configure(workspace: str | Path = ".") -> None:
    """Set the workspace root directory. Call before any other function.

    Example::

        configure("/path/to/project")
    """
    global _workspace
    _workspace = Path(workspace).resolve()


def cleanup_step() -> None:
    """Drop content from clean handles between agent steps.

    Called by the framework after each agent code execution step.
    Frees memory while keeping singleton handles alive for metadata.
    """
    for handle in _registry.values():
        if not handle._dirty:
            handle._content = None


def reset_session() -> None:
    """Clear all handles. Called when the agent task finishes."""
    _registry.clear()


# ---------------------------------------------------------------------------
# Integration registration
# ---------------------------------------------------------------------------


def register(workspace: Path) -> dict:
    """Integration protocol: configure and return metadata."""
    configure(workspace)
    return {
        "name": "file_edit",
        "functions": {
            "read": read,
            "edit": edit,
            "write": write,
            "insert": insert,
            "replace_lines": replace_lines,
            "edit_regex": edit_regex,
            "append": append,
            "batch": batch,
            "delete": delete,
            "exists": exists,
            "find": find,
        },
        "system_prompt": SYSTEM_PROMPT,
        "cleanup_step": cleanup_step,
        "reset_session": reset_session,
    }
