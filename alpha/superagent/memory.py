"""Working memory — key-value blocks stored as YAML files on disk.

Each block is a YAML file under sandbox/memory/.
Keys are named entries the agent can set, update, or delete individually.
The engine reads them before every LLM call and compiles them into XML.

No in-memory state.  Kill the process, restart, blocks are on disk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Block definition
# ---------------------------------------------------------------------------

@dataclass
class BlockDef:
    """Static metadata for a memory block."""

    label: str
    filename: str
    description: str
    char_limit: int = 10_000
    read_only: bool = False


STANDARD_BLOCKS: list[BlockDef] = [
    BlockDef(
        label="persona",
        filename="persona.yaml",
        description="Your identity and behavioral guidelines.",
        char_limit=5_000,
    ),
    BlockDef(
        label="workspace_info",
        filename="workspace_info.yaml",
        description=(
            "What you know about this workspace. "
            "Update keys as you learn more."
        ),
        char_limit=10_000,
    ),
    BlockDef(
        label="user_preferences",
        filename="user_preferences.yaml",
        description=(
            "The user's working style, preferences, and habits."
        ),
        char_limit=5_000,
    ),
    BlockDef(
        label="current_domain",
        filename="current_domain.yaml",
        description="The current task domain, if detected.",
        char_limit=2_000,
        read_only=True,
    ),
]

DEFAULT_ENTRIES: dict[str, dict[str, str]] = {
    "persona": {
        "identity": (
            "I am a file workspace assistant. "
            "I learn from experience and update my memory when I discover something important."
        ),
    },
    "workspace_info": {},
    "user_preferences": {},
    "current_domain": {},
}


# ---------------------------------------------------------------------------
# Disk operations
# ---------------------------------------------------------------------------


def ensure_block_files(memory_dir: Path) -> None:
    """Create default block files if they do not exist."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    # Clean up old .md files from Day 1
    for bdef in STANDARD_BLOCKS:
        old_md = memory_dir / bdef.filename.replace(".yaml", ".md")
        if old_md.exists():
            old_md.unlink()
    for bdef in STANDARD_BLOCKS:
        path = memory_dir / bdef.filename
        if not path.exists():
            entries = DEFAULT_ENTRIES.get(bdef.label, {})
            path.write_text(yaml.dump(entries, default_flow_style=False, allow_unicode=True))
            log.info("created default block %s", path)


def read_block(memory_dir: Path, bdef: BlockDef) -> dict[str, str]:
    """Read block entries from disk.  Returns dict of key→value."""
    path = memory_dir / bdef.filename
    if not path.exists():
        return DEFAULT_ENTRIES.get(bdef.label, {})
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        log.warning("failed to parse %s, returning empty", path)
        return {}


def write_block(memory_dir: Path, bdef: BlockDef, entries: dict[str, str]) -> None:
    """Write block entries to disk."""
    if bdef.read_only:
        raise ValueError(f"block '{bdef.label}' is read-only")
    total = sum(len(v) for v in entries.values())
    if total > bdef.char_limit:
        raise ValueError(
            f"block '{bdef.label}': {total} chars exceeds limit {bdef.char_limit}"
        )
    path = memory_dir / bdef.filename
    path.write_text(yaml.dump(entries, default_flow_style=False, allow_unicode=True))


def update_entry(memory_dir: Path, label: str, key: str, value: str) -> str:
    """Set or delete a single entry in a block.  Empty value = delete.

    Returns a status message.
    """
    bdef = find_block_def(label)
    if bdef is None:
        return f"Error: unknown block '{label}'"
    if bdef.read_only:
        return f"Error: block '{label}' is read-only"
    entries = read_block(memory_dir, bdef)
    if not value.strip():
        # Delete
        if key in entries:
            del entries[key]
            action = f"deleted key '{key}'"
        else:
            return f"Error: key '{key}' not found in '{label}'"
    else:
        action = f"updated key '{key}'" if key in entries else f"added key '{key}'"
        entries[key] = value
    # Check capacity
    total = sum(len(v) for v in entries.values())
    if total > bdef.char_limit:
        return f"Error: would exceed capacity ({total}/{bdef.char_limit} chars)"
    write_block(memory_dir, bdef, entries)
    return f"OK: {action} in '{label}' ({total}/{bdef.char_limit} chars used)"


def find_block_def(label: str) -> BlockDef | None:
    for bdef in STANDARD_BLOCKS:
        if bdef.label == label:
            return bdef
    return None


# ---------------------------------------------------------------------------
# Compile blocks into XML for the system prompt
# ---------------------------------------------------------------------------


def compile_blocks_xml(memory_dir: Path) -> str:
    """Read all blocks from disk and render as XML with key-value entries."""
    parts = ["<memory_blocks>"]
    for bdef in STANDARD_BLOCKS:
        entries = read_block(memory_dir, bdef)
        total_chars = sum(len(v) for v in entries.values())
        ro = ' read_only="true"' if bdef.read_only else ""
        parts.append(f"<{bdef.label}>")
        parts.append(f"  <description>{bdef.description}</description>")
        parts.append(f"  <metadata>entries={len(entries)} chars={total_chars}/{bdef.char_limit}{ro}</metadata>")
        if entries:
            for k, v in entries.items():
                parts.append(f'  <entry key="{k}">{v}</entry>')
        else:
            parts.append("  (empty)")
        parts.append(f"</{bdef.label}>")
    parts.append("</memory_blocks>")
    return "\n".join(parts)
