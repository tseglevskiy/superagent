"""Working memory — Letta-style labeled text blocks stored as files on disk.

Each block is a plain text file under ~/.superagent-sandbox/memory/.
The engine reads them before every LLM call and compiles them into XML
in the system prompt.  When the agent calls memory_update, the handler
writes the new value to disk — the next call picks it up automatically.

No in-memory state.  Kill the process, restart, blocks are on disk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

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


# The four standard blocks from prompts/06-system-prompt.md
STANDARD_BLOCKS: list[BlockDef] = [
    BlockDef(
        label="persona",
        filename="persona.md",
        description="Your identity and behavioral guidelines.",
        char_limit=5_000,
    ),
    BlockDef(
        label="workspace_info",
        filename="workspace_info.md",
        description=(
            "What you know about this workspace's structure and contents. "
            "Update as you learn more."
        ),
        char_limit=10_000,
    ),
    BlockDef(
        label="user_preferences",
        filename="user_preferences.md",
        description=(
            "The user's working style, preferences, and habits. "
            "Update when you notice patterns."
        ),
        char_limit=5_000,
    ),
    BlockDef(
        label="current_domain",
        filename="current_domain.md",
        description=(
            "The current task domain, if detected. Loaded automatically."
        ),
        char_limit=2_000,
        read_only=True,
    ),
]


# ---------------------------------------------------------------------------
# Default content for brand-new blocks
# ---------------------------------------------------------------------------

DEFAULT_CONTENT: dict[str, str] = {
    "persona": (
        "I am a file workspace assistant. "
        "I learn from experience — the more I work with this workspace, "
        "the better I understand its structure and the user's preferences. "
        "I check my accumulated knowledge before starting tasks "
        "and update my memory when I discover something important."
    ),
    "workspace_info": "(No information yet — explore the workspace to learn its structure.)",
    "user_preferences": "(No preferences observed yet.)",
    "current_domain": "(No domain detected.)",
}


# ---------------------------------------------------------------------------
# Disk operations
# ---------------------------------------------------------------------------


def ensure_block_files(memory_dir: Path) -> None:
    """Create default block files if they do not exist."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    for bdef in STANDARD_BLOCKS:
        path = memory_dir / bdef.filename
        if not path.exists():
            path.write_text(DEFAULT_CONTENT.get(bdef.label, ""))
            log.info("created default block %s", path)


def read_block(memory_dir: Path, bdef: BlockDef) -> str:
    """Read block content from disk.  Returns default if file missing."""
    path = memory_dir / bdef.filename
    if path.exists():
        return path.read_text()
    return DEFAULT_CONTENT.get(bdef.label, "")


def write_block(memory_dir: Path, bdef: BlockDef, content: str) -> None:
    """Write block content to disk."""
    if bdef.read_only:
        raise ValueError(f"block '{bdef.label}' is read-only")
    if len(content) > bdef.char_limit:
        raise ValueError(
            f"block '{bdef.label}': {len(content)} chars exceeds limit {bdef.char_limit}"
        )
    path = memory_dir / bdef.filename
    path.write_text(content)
    log.debug("wrote block %s (%d chars)", bdef.label, len(content))


def find_block_def(label: str) -> BlockDef | None:
    """Find a BlockDef by label."""
    for bdef in STANDARD_BLOCKS:
        if bdef.label == label:
            return bdef
    return None


# ---------------------------------------------------------------------------
# Compile blocks into XML for the system prompt
# ---------------------------------------------------------------------------


def compile_blocks_xml(memory_dir: Path) -> str:
    """Read all blocks from disk and render as XML with metadata."""
    parts = ["<memory_blocks>"]
    for bdef in STANDARD_BLOCKS:
        value = read_block(memory_dir, bdef)
        chars = len(value)
        ro = ' read_only="true"' if bdef.read_only else ""
        parts.append(f"<{bdef.label}>")
        parts.append(f"  <description>{bdef.description}</description>")
        parts.append(f"  <metadata>chars={chars}/{bdef.char_limit}{ro}</metadata>")
        parts.append(f"  <value>{value}</value>")
        parts.append(f"</{bdef.label}>")
    parts.append("</memory_blocks>")
    return "\n".join(parts)
