"""Knowledge store — observations as Python files with SQLite FTS5 index.

Each observation is a .py file on disk. Metadata is in the module docstring.
Functions defined in the file are auto-loaded into the sandbox with ID suffixes.
Text-only observations (comments, data) are injected into context but not loaded.

Operations:
  add(content, ...) -> id
  search(query, ...) -> list of observations (for predict-calibrate)
  retire(id) -> status
  load_all_active() -> list of observations (for context injection)
  get_functions(obs) -> list of (name, code) pairs (for sandbox loading)
"""

from __future__ import annotations

import ast
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .atomicfile import atomic_write

log = logging.getLogger(__name__)


def sanitize_name(name: str) -> str:
    """Sanitize a name for use as a filename or directory.
    Lowercases, replaces spaces with hyphens, strips non-alphanumeric."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\-_]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "uncategorized"


# ---------------------------------------------------------------------------
# Observation dataclass
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    id: str
    content: str  # the full Python source
    domain: str = "uncategorized"
    topic: str = ""
    confidence: float = 0.8
    tags: list[str] = field(default_factory=list)
    source_session: str = ""
    created_at: str = ""
    retired: bool = False
    calls_success: int = 0
    calls_failed: int = 0

    @property
    def short_id(self) -> str:
        """The short suffix for function renaming: obs-abc123 -> abc123."""
        return self.id.replace("obs-", "")


# ---------------------------------------------------------------------------
# Metadata parsing — extract/update metadata in module docstring
# ---------------------------------------------------------------------------

_META_FIELDS = ["id", "domain", "topic", "confidence", "tags",
                "source_session", "created_at", "retired",
                "calls_success", "calls_failed"]


def _parse_metadata(source: str) -> dict[str, Any]:
    """Extract metadata from the module docstring."""
    meta: dict[str, Any] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return meta
    if not tree.body:
        return meta
    first = tree.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, (ast.Constant, ast.Str)):
        docstring = first.value.value if isinstance(first.value, ast.Constant) else first.value.s
        for line in docstring.splitlines():
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip()
                if key in _META_FIELDS:
                    meta[key] = val
    return meta


def _build_source(obs: Observation) -> str:
    """Build the .py file content with metadata docstring + body."""
    # Extract body (everything after the metadata docstring)
    body = obs.content
    tags_str = ", ".join(obs.tags) if obs.tags else ""
    docstring = (
        f'"""\n'
        f'id: {obs.id}\n'
        f'domain: {obs.domain}\n'
        f'topic: {obs.topic}\n'
        f'confidence: {obs.confidence}\n'
        f'tags: {tags_str}\n'
        f'source_session: {obs.source_session}\n'
        f'created_at: {obs.created_at}\n'
        f'retired: {obs.retired}\n'
        f'calls_success: {obs.calls_success}\n'
        f'calls_failed: {obs.calls_failed}\n'
        f'"""\n'
    )
    return docstring + body


def _load_from_file(path: Path) -> Observation | None:
    """Load an observation from a .py file."""
    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return None
    meta = _parse_metadata(source)
    if not meta.get("id"):
        return None
    # Extract body: everything after the closing triple-quote of the docstring
    body = source
    match = re.search(r'^""".*?^"""\n?', source, re.MULTILINE | re.DOTALL)
    if match:
        body = source[match.end():]
    tags_raw = meta.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    return Observation(
        id=str(meta["id"]),
        content=body,
        domain=str(meta.get("domain", "uncategorized")),
        topic=str(meta.get("topic", "")),
        confidence=float(meta.get("confidence", 0.8)),
        tags=tags,
        source_session=str(meta.get("source_session", "")),
        created_at=str(meta.get("created_at", "")),
        retired=str(meta.get("retired", "False")).lower() == "true",
        calls_success=int(meta.get("calls_success", 0)),
        calls_failed=int(meta.get("calls_failed", 0)),
    )


# ---------------------------------------------------------------------------
# Function detection — find FunctionDef nodes in observation source
# ---------------------------------------------------------------------------


def get_functions(obs: Observation) -> list[tuple[str, str, str]]:
    """Extract functions from observation body.

    Returns list of (original_name, suffixed_name, source_code).
    The suffixed_name uses the observation's short_id for namespace safety.
    """
    try:
        tree = ast.parse(obs.content)
    except SyntaxError:
        return []
    results = []
    lines = obs.content.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            orig_name = node.name
            suffixed = f"{orig_name}_{obs.short_id}"
            # Extract source lines for this function
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") and node.end_lineno else len(lines)
            func_source = "\n".join(lines[start:end])
            # Rename in source
            renamed_source = func_source.replace(f"def {orig_name}(", f"def {suffixed}(", 1)
            results.append((orig_name, suffixed, renamed_source))
    return results


# ---------------------------------------------------------------------------
# SQLite FTS5 index
# ---------------------------------------------------------------------------


def _init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            domain TEXT DEFAULT 'uncategorized',
            tags TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            retired INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts
        USING fts5(id, content, tags, domain, content=observations, content_rowid=rowid)
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS obs_ai AFTER INSERT ON observations BEGIN
            INSERT INTO observations_fts(rowid, id, content, tags, domain)
            VALUES (new.rowid, new.id, new.content, new.tags, new.domain);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS obs_ad AFTER DELETE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, id, content, tags, domain)
            VALUES('delete', old.rowid, old.id, old.content, old.tags, old.domain);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS obs_au AFTER UPDATE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, id, content, tags, domain)
            VALUES('delete', old.rowid, old.id, old.content, old.tags, old.domain);
            INSERT INTO observations_fts(rowid, id, content, tags, domain)
            VALUES (new.rowid, new.id, new.content, new.tags, new.domain);
        END
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# KnowledgeStore
# ---------------------------------------------------------------------------


class KnowledgeStore:

    def __init__(self, knowledge_dir: Path) -> None:
        self.knowledge_dir = knowledge_dir
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "domains" / "uncategorized" / "observations").mkdir(
            parents=True, exist_ok=True
        )
        self._db = _init_db(knowledge_dir / "index.db")
        self._sync_index()

    def _obs_dir(self, domain: str) -> Path:
        d = self.knowledge_dir / "domains" / domain / "observations"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _obs_path(self, obs: Observation) -> Path:
        return self._obs_dir(obs.domain) / f"{obs.id}.py"

    def _save(self, obs: Observation) -> None:
        source = _build_source(obs)
        atomic_write(self._obs_path(obs), source)

    def _upsert_index(self, obs: Observation) -> None:
        full_text = obs.content
        self._db.execute(
            """INSERT OR REPLACE INTO observations
               (id, content, domain, tags, created_at, retired)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (obs.id, full_text, obs.domain,
             " ".join(obs.tags), obs.created_at,
             1 if obs.retired else 0),
        )

    def _sync_index(self) -> None:
        """Rebuild index from .py files on disk."""
        domains_dir = self.knowledge_dir / "domains"
        if not domains_dir.exists():
            return
        for domain_dir in domains_dir.iterdir():
            if not domain_dir.is_dir():
                continue
            obs_dir = domain_dir / "observations"
            if not obs_dir.exists():
                continue
            for f in obs_dir.glob("*.py"):
                obs = _load_from_file(f)
                if obs:
                    self._upsert_index(obs)
        self._db.commit()

    # --- public API ---

    def add(
        self,
        content: str,
        *,
        confidence: float = 0.8,
        tags: list[str] | None = None,
        domain: str = "uncategorized",
        topic: str = "",
        source_session: str = "",
    ) -> str:
        """Add a new observation. Content is the Python body (no docstring header)."""
        obs_id = f"obs-{uuid.uuid4().hex[:8]}"
        obs = Observation(
            id=obs_id,
            content=content,
            confidence=confidence,
            tags=tags or [],
            domain=sanitize_name(domain),
            topic=topic,
            source_session=source_session,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self._save(obs)
        self._upsert_index(obs)
        self._db.commit()
        log.info("added observation %s", obs_id)
        return obs_id

    def retire(self, obs_id: str) -> str:
        """Retire an observation by ID."""
        domains_dir = self.knowledge_dir / "domains"
        for domain_dir in domains_dir.iterdir():
            if not domain_dir.is_dir():
                continue
            path = domain_dir / "observations" / f"{obs_id}.py"
            if path.exists():
                obs = _load_from_file(path)
                if not obs:
                    return f"Error: could not parse {obs_id}"
                obs.retired = True
                self._save(obs)
                self._db.execute(
                    "UPDATE observations SET retired = 1 WHERE id = ?", (obs_id,)
                )
                self._db.commit()
                return f"OK: retired observation {obs_id}"
        return f"Error: observation {obs_id} not found"

    def record_call(self, obs_id: str, success: bool) -> None:
        """Record a function call metric for an observation."""
        domains_dir = self.knowledge_dir / "domains"
        for domain_dir in domains_dir.iterdir():
            if not domain_dir.is_dir():
                continue
            path = domain_dir / "observations" / f"{obs_id}.py"
            if path.exists():
                obs = _load_from_file(path)
                if obs:
                    if success:
                        obs.calls_success += 1
                    else:
                        obs.calls_failed += 1
                    self._save(obs)
                return

    def search(self, query: str, *, domain: str | None = None, limit: int = 10) -> list[Observation]:
        """FTS5 search for predict-calibrate baseline retrieval."""
        if not query.strip():
            return []
        safe = query.replace('"', '""')
        try:
            if domain:
                rows = self._db.execute(
                    """SELECT o.id, o.content, o.domain, o.tags, o.created_at
                       FROM observations o
                       JOIN observations_fts f ON o.rowid = f.rowid
                       WHERE observations_fts MATCH ? AND o.domain = ? AND o.retired = 0
                       ORDER BY o.created_at DESC LIMIT ?""",
                    (f'"{safe}"', domain, limit),
                ).fetchall()
            else:
                rows = self._db.execute(
                    """SELECT o.id, o.content, o.domain, o.tags, o.created_at
                       FROM observations o
                       JOIN observations_fts f ON o.rowid = f.rowid
                       WHERE observations_fts MATCH ? AND o.retired = 0
                       ORDER BY o.created_at DESC LIMIT ?""",
                    (f'"{safe}"', limit),
                ).fetchall()
        except sqlite3.OperationalError:
            like_q = f"%{query}%"
            rows = self._db.execute(
                """SELECT id, content, domain, tags, created_at
                   FROM observations WHERE content LIKE ? AND retired = 0
                   ORDER BY created_at DESC LIMIT ?""",
                (like_q, limit),
            ).fetchall()
        return [
            Observation(
                id=r[0], content=r[1], domain=r[2],
                tags=r[3].split() if r[3] else [],
                created_at=r[4],
            )
            for r in rows
        ]

    def load_all_active(self) -> list[Observation]:
        """Load all non-retired observations from disk. For context injection."""
        results = []
        domains_dir = self.knowledge_dir / "domains"
        if not domains_dir.exists():
            return results
        for domain_dir in sorted(domains_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            obs_dir = domain_dir / "observations"
            if not obs_dir.exists():
                continue
            for f in sorted(obs_dir.glob("*.py")):
                obs = _load_from_file(f)
                if obs and not obs.retired:
                    results.append(obs)
        # Sort newest first
        results.sort(key=lambda o: o.created_at, reverse=True)
        return results

    def count(self, domain: str | None = None) -> int:
        if domain:
            row = self._db.execute(
                "SELECT COUNT(*) FROM observations WHERE domain = ? AND retired = 0",
                (domain,),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COUNT(*) FROM observations WHERE retired = 0"
            ).fetchone()
        return row[0] if row else 0
