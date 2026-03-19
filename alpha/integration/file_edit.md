# file_edit.py - Design Report

## What This Is

A Python library that gives LLM agents file editing primitives in the code-as-action paradigm.
The agent writes Python code that calls `edit()`, `read()`, `write()`, `batch()`, etc.
These functions are injected into the agent's execution namespace alongside user-defined tools.

The design is informed by a study of 33 open-source AI agent projects, focusing on what works and what breaks in practice.

## Why Code-as-Action

Most coding agents (Cline, Claude Code, OpenHands, Goose, OpenCode) use structured tool calls: the LLM emits JSON with `old_str`/`new_str`, and the host parses it.
A few (smolagents, Voyager) use code-as-action: the LLM writes Python code that runs in a sandbox.

We chose code-as-action because:
- **Composability** - the agent can loop, branch, and combine operations in ways tool calls cannot express
- **Flexibility** - the agent picks the right editing strategy per situation, rather than being limited to one tool
- **Familiarity** - Python is the language LLMs are best at; no special edit format to learn
- **Testability** - functions can be unit-tested independently

The trade-off: we need a sandboxed execution environment (smolagents provides several), and the framework has less control over what the agent does.

## How It Compares to Other Agents

### vs. OpenHands `str_replace_editor`

OpenHands provides a single tool with 5 commands (view, create, str_replace, insert, undo_edit), called via native JSON tool calls.
Our API provides the same operations but as Python functions with additional capabilities.

Key differences:
- **Fuzzy matching**: OpenHands requires exact match only. We have a 5-strategy cascade (exact, line-trimmed, indentation-flexible, whitespace-normalized, escape-normalized) that handles the most common LLM errors.
- **Multi-file atomicity**: OpenHands has no atomic multi-file edit. Our `batch()` provides all-or-nothing.
- **Regex support**: OpenHands has none. We provide `edit_regex()` for pattern-based changes.
- **File handle model**: OpenHands has no caching or live handles. We use singleton File handles with write-back buffers.

### vs. Cline `replace_in_file` / `write_to_file` / `apply_patch`

Cline provides 3 separate tools via XML tags or native tool calls: whole-file write, SEARCH/REPLACE markers, and unified diff.
The LLM must choose which tool to use and format the edit accordingly.

Key differences:
- **Single primary tool**: Our `edit()` is the main tool for all targeted changes. The agent does not need to choose between formats.
- **No format to learn**: Cline requires the LLM to produce `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` markers. Our API uses plain Python strings.
- **Fuzzy matching**: Cline requires exact character-for-character match. We handle indentation errors automatically.
- **Atomicity**: Cline's `replace_in_file` is atomic per invocation (all blocks pass or none). Our `batch()` extends this to multi-file operations.

### vs. OpenCode `edit` / `apply_patch`

OpenCode provides search-replace via Vercel AI SDK tool calls, with a separate `apply_patch` for GPT models.
It has the most sophisticated fuzzy matching we found (9 strategies).

Key differences:
- **Similar fuzzy cascade**: We adapted our cascade from OpenCode's design (5 strategies vs their 9 - we cover the most impactful ones).
- **Singleton handles**: OpenCode has `FileTime` tracking per session. We use singleton File handles with live buffers - the agent can inspect `f.content` at any time and always see the latest state.
- **No format switching**: OpenCode selects between `edit` and `apply_patch` based on model ID. We provide one primary API that works with all models.

### vs. Aider (text markers, no tool calls)

Aider is unique: no tool calls at all. The LLM produces SEARCH/REPLACE text markers in its response, and Aider parses them out.
It supports 6+ edit format variants, selected per model.

Key differences:
- **Code-as-action vs text-parsing**: Aider parses free-form text. We run Python code. This eliminates parsing fragility.
- **Model-aware format**: Aider selects the format per model. We provide one API; the model just writes Python.
- **Fuzzy matching**: Aider has a 5-step cascade similar to ours (exact, leading-whitespace-flexible, drop-blank-line, dotdotdot, edit-distance). Ours is comparable.
- **No `batch()`**: Aider has no atomic multi-file edit. It compensates with git auto-commits and `/undo`.

### vs. smolagents (raw Python)

smolagents is the closest relative: the agent writes Python code to do everything.
But smolagents has no built-in file editing tools - the agent uses `open().read()` and `open().write()`.

Key differences:
- **Everything we add**: fuzzy matching, uniqueness enforcement, mtime tracking, atomic writes, `batch()`, rich error messages with suggestions, diff previews. Raw smolagents has none of this.
- **Singleton handles**: smolagents has no file handle concept. Each `open()` is independent.
- **Same paradigm**: Both are code-as-action. Our library could be integrated into smolagents as a tool collection.

## How to Use

### 1. Configure the workspace

```python
from file_edit import configure, SYSTEM_PROMPT
configure("/path/to/project")
```

### 2. Inject the system prompt

Add `SYSTEM_PROMPT` to the LLM's system message so it knows the available functions.

### 3. Inject functions into the agent's namespace

```python
from file_edit import (
    read, edit, write, insert, replace_lines, edit_regex,
    append, batch, delete, exists, find, grep, diff,
)

namespace = {
    "read": read, "edit": edit, "write": write, "insert": insert,
    "replace_lines": replace_lines, "edit_regex": edit_regex,
    "append": append, "batch": batch, "delete": delete,
    "exists": exists, "find": find, "grep": grep, "diff": diff,
}
exec(agent_code, namespace)
```

### 4. Between agent steps

```python
from file_edit import cleanup_step
cleanup_step()  # drops content from clean handles to free memory
```

### 5. End of task

```python
from file_edit import reset_session
reset_session()  # clears all handles
```

### What the agent writes

```python
# Simple edit - no read() needed
edit("src/app.py", old="return 'hello'", new="return 'world'")

# Read then inspect
f = read("src/app.py")
print(f[15])  # line 15
print(f.grep("class Config"))

# Multi-file atomic change
with batch(message="rename foo to bar"):
    edit("src/a.py", old="import foo", new="import bar")
    edit("src/b.py", old="from foo", new="from bar")

# Create new file
write("src/new.py", "def hello():\n    pass\n")

# Line-number operations
f = read("src/app.py")
insert(f, after=10, content="    logger.info('called')\n")

# Regex
edit_regex("setup.py", pattern=r'version = "[\d.]+"', replacement='version = "2.0.0"')
```

## Design Decisions and Tradeoffs

### 1. Search-and-replace as the primary primitive

**Decision:** `edit(path, old, new)` with substring matching, not line-number-based replacement or unified diff.

**Why:** 8 of 13 coding agents in our study converged on search-and-replace. It is the sweet spot between token efficiency (only reproducing the changed region) and reliability (content match is self-guarding against stale edits). Line-number operations (`insert`, `replace_lines`) are available but secondary - line numbers are fragile and shift after earlier edits.

**Tradeoff:** Substring matching can match inside string literals (e.g., `old="x = 1"` matches inside `print("x = 1")`). We mitigate with uniqueness enforcement - `MultipleMatchError` forces the agent to add context.

### 2. Singleton live File handles

**Decision:** `read("app.py")` always returns the same object. The handle is a live buffer - `f.content` always reflects the latest state.

**Why:** Eliminates stale-handle confusion. The agent can use path strings or File handles interchangeably - they resolve to the same buffer. Inside `batch()`, all edits modify the same buffer, so `f[n]` always shows the current state.

**Tradeoff:** Memory usage - all open handles hold content in memory. Mitigated by between-step cleanup that drops content from clean handles.

### 3. Content match as the freshness guard for edit()

**Decision:** `edit()` does NOT require `read()` first. If the file changed externally, the `old` text simply will not match, and the agent gets a clear `NoMatchError`.

**Why:** In code-as-action, read and edit can happen in the same code block or across steps. Requiring `read()` before every `edit()` is unnecessary ceremony for the common case. The content match itself is the guard.

**Tradeoff:** `insert()` and `replace_lines()` DO require a File handle because line numbers can silently be wrong if the file shifted. The mtime check happens through the File object.

### 4. Fuzzy matching cascade (5 strategies)

**Decision:** Try exact match first, then increasingly permissive strategies: line-trimmed, indentation-flexible, whitespace-normalized, escape-normalized.

**Why:** LLMs routinely produce edits with wrong indentation (most common), extra trailing whitespace, or escape character differences. Only 3 of 33 projects in our study implement fuzzy matching (OpenCode, Aider, Moatless). The rest use exact-only and force the LLM to retry, wasting turns and tokens.

**Tradeoff:** Fuzzy matching can make the wrong match if the file has multiple similar blocks. We mitigate with uniqueness enforcement - even fuzzy matches must be unique.

### 5. batch() with transparent nesting

**Decision:** `batch()` is a context manager that defers flushing. Nested `batch()` is transparent - only the outermost controls flushing.

**Why:** Enables composable helper functions. A function that uses `batch()` internally works correctly when called from another `batch()`. This is the same pattern as Django's `atomic()`.

**Tradeoff:** Inside `batch()`, `edit()` modifies the buffer but does not flush. If the agent runs a subprocess inside the batch (e.g., `run("pytest")`), the subprocess sees the old disk content, not the buffered changes. Edits are only visible to the File handle, not to external processes, until the batch exits.

### 6. Lazy git check-attr for line endings

**Decision:** Line ending detection is deferred until first modification. Reading a file normalizes to `\n` without querying git.

**Why:** Most files in a session are read-only (the agent inspects them but doesn't edit). Querying `git check-attr` for every `read()` would be wasteful. We only need the expected line ending when flushing to disk.

**Tradeoff:** If the agent reads a file and checks for `\r\n` in `f.content`, it will never find it (content is always `\n`-normalized). This is by design - the agent should never need to handle line endings.

### 7. Atomic writes via temp + rename

**Decision:** Flush writes to a temp file first, then atomically renames to the target path. Mtime is checked between temp-write and rename.

**Why:** Prevents partial writes (power loss, crash) and detects external modifications. If another process modifies the file between the buffer update and the flush, the mtime check catches it.

**Tradeoff:** On some filesystems (NFS, some network mounts), `os.rename()` across directories is not atomic. We mitigate by creating the temp file in the same directory as the target.

### 8. Content cache cleanup between steps

**Decision:** After each agent step, drop content from clean (flushed) handles. Keep singleton handles alive with their metadata (path, mtime, line ending).

**Why:** Agents can read hundreds of files during exploration. Keeping all content in memory wastes RAM. The singleton handle persists so the next access can lazy-load from disk without creating a new handle.

**Tradeoff:** The first access to an evicted handle in the next step triggers a disk read. For the typical case (5-20 files actively edited), this is negligible.

### 9. dotdotdot as opt-in wildcard

**Decision:** `edit(..., dotdotdot=True)` enables `...` as a wildcard in `old`. Off by default so `...` is treated as literal text.

**Why:** Useful for targeting a region by its boundaries without reproducing long lines or large unchanged blocks. Saves tokens for files with data URLs, base64 blobs, or minified code.

**Tradeoff:** When `dotdotdot=True`, `new` replaces the ENTIRE matched region including whatever `...` expanded to. The agent cannot selectively keep parts of the matched region - it must reproduce everything it wants to preserve in `new`. This was a deliberate simplification after considering (and rejecting) having `...` in `new` as a "keep this part" marker.

