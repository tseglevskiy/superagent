# Tool Definitions — Native Tool Calling

## Approach

We use native tool calling (Anthropic's `tools` parameter), NOT code-as-action.
The model is trained for tool calling — output parsing is handled by the API.
Each tool is a JSON schema passed to the LLM.

## Tool Schemas

### get_file

```json
{
  "name": "get_file",
  "description": "Read a file from the workspace. Returns the full content as text. For binary files, returns a summary (size, type). Use for inspecting file content.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Path relative to the workspace root"
      }
    },
    "required": ["path"]
  }
}
```

### get_lines

```json
{
  "name": "get_lines",
  "description": "Read specific lines from a text file. Use when you need only a portion of a large file.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Path relative to workspace root"},
      "start": {"type": "integer", "description": "First line number (1-based)"},
      "end": {"type": "integer", "description": "Last line number (inclusive)"}
    },
    "required": ["path", "start", "end"]
  }
}
```

### list_dir

```json
{
  "name": "list_dir",
  "description": "List directory contents. Returns names, sizes, types, and modification dates. Use glob patterns to filter.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Directory path relative to workspace root. Use '.' for workspace root."},
      "pattern": {"type": "string", "description": "Glob pattern to filter results. Default: '*'", "default": "*"},
      "recursive": {"type": "boolean", "description": "Search subdirectories. Default: false", "default": false}
    },
    "required": ["path"]
  }
}
```

### create_file

```json
{
  "name": "create_file",
  "description": "Create a new file in the workspace. Fails if file already exists. Use replace_file to overwrite.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Path relative to workspace root"},
      "content": {"type": "string", "description": "File content to write"}
    },
    "required": ["path", "content"]
  }
}
```

### replace_file

```json
{
  "name": "replace_file",
  "description": "Overwrite an existing file with new content. The old content is replaced entirely.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Path relative to workspace root"},
      "content": {"type": "string", "description": "New file content"}
    },
    "required": ["path", "content"]
  }
}
```

### replace_lines

```json
{
  "name": "replace_lines",
  "description": "Replace specific lines in a text file. Lines outside the range are unchanged.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "Path relative to workspace root"},
      "start": {"type": "integer", "description": "First line to replace (1-based)"},
      "end": {"type": "integer", "description": "Last line to replace (inclusive)"},
      "content": {"type": "string", "description": "Replacement content (can be more or fewer lines)"}
    },
    "required": ["path", "start", "end", "content"]
  }
}
```

### python_exec

```json
{
  "name": "python_exec",
  "description": "Execute a Python code snippet in the workspace context. The variable WORKSPACE (pathlib.Path) points to the workspace root. Standard library modules are available: os, pathlib, hashlib, json, csv, re, glob, shutil, collections, itertools. Print output is captured and returned. Use for complex file analysis, batch operations, and data processing.",
  "input_schema": {
    "type": "object",
    "properties": {
      "code": {
        "type": "string",
        "description": "Python code to execute. Use print() to produce output."
      }
    },
    "required": ["code"]
  }
}
```

### memory_update

```json
{
  "name": "memory_update",
  "description": "Update a section of your working memory. Your memory blocks are shown in the system prompt under <memory_blocks>. Use this to record important discoveries about the workspace, user preferences, or task patterns that you want to remember.",
  "input_schema": {
    "type": "object",
    "properties": {
      "label": {"type": "string", "description": "The memory block label to update (e.g., 'workspace_info', 'user_preferences')"},
      "old_content": {"type": "string", "description": "The exact text to find and replace. Must match verbatim."},
      "new_content": {"type": "string", "description": "The replacement text."}
    },
    "required": ["label", "old_content", "new_content"]
  }
}
```

### knowledge_search

```json
{
  "name": "knowledge_search",
  "description": "Search your accumulated knowledge from past tasks. Returns observations and patterns you have learned. Use this BEFORE starting a task to check if you already know relevant patterns. Returns empty results if you have no knowledge on the topic yet.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "What to search for in your knowledge"},
      "domain": {"type": "string", "description": "Optional: limit search to a specific domain (e.g., 'data-cleanup', 'scripting'). Omit to search all domains."}
    },
    "required": ["query"]
  }
}
```

## Notes

- All paths are relative to the workspace root. Absolute paths and `..` traversal are rejected by the handler.
- python_exec runs in a subprocess with a 30-second timeout. No network access. No pip install.
- memory_update uses exact string matching for old_content. The agent sees the current block values in the system prompt and can reference them precisely.
- knowledge_search is the key learning indicator: if the agent starts calling it before tasks, it means the knowledge pipeline is producing useful results.
