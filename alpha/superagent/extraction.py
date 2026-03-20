"""Extraction pipeline — episode segmentation + predict-calibrate.

Runs in foreground (D7): visible output, not background.
Triggered after EXTRACTION_EVERY_N_MESSAGES user messages.

Flow:
  1. Count user messages since last extraction
  2. If threshold reached, load unprocessed messages
  3. Call LLM to segment into episodes (prompt 01)
  4. For each episode, call LLM to extract observations (prompt 02)
  5. Store observations in KnowledgeStore
  6. Advance the extraction pointer
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from .budget import record_and_print
from .config import Config, EXTRACTION_EVERY_N_MESSAGES
from .knowledge import KnowledgeStore
from .llm import LLMClient

log = logging.getLogger(__name__)

DIM = "\033[2m"
MAGENTA = "\033[35m"
RESET = "\033[0m"


def _info(text: str) -> None:
    """Print extraction progress visibly (always, not just verbose)."""
    print(f"{MAGENTA}[extraction]{RESET} {text}")


# ---------------------------------------------------------------------------
# Extraction pointer — tracks which messages have been processed
# ---------------------------------------------------------------------------


def _pointer_file(cfg: Config) -> Path:
    return cfg.data_dir / "extraction_pointer.txt"


def _read_pointer(cfg: Config) -> int:
    """Read the extraction pointer (number of user messages already processed)."""
    pf = _pointer_file(cfg)
    if pf.exists():
        try:
            return int(pf.read_text().strip())
        except ValueError:
            return 0
    return 0


def _write_pointer(cfg: Config, count: int) -> None:
    """Write the extraction pointer."""
    _pointer_file(cfg).write_text(str(count))


# ---------------------------------------------------------------------------
# Count user messages in session
# ---------------------------------------------------------------------------


def _count_user_messages(cfg: Config) -> int:
    """Count user messages in current session JSONL."""
    if not cfg.session_file.exists():
        return 0
    count = 0
    for line in cfg.session_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("role") == "user":
                count += 1
        except json.JSONDecodeError:
            continue
    return count


def _load_messages_since(cfg: Config, since_user_msg: int) -> list[dict]:
    """Load all messages after the Nth user message."""
    if not cfg.session_file.exists():
        return []
    messages = []
    user_count = 0
    collecting = False
    for line in cfg.session_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("role") == "user":
            user_count += 1
        if user_count > since_user_msg:
            collecting = True
        if collecting:
            msg.pop("ts", None)
            messages.append(msg)
    return messages


# ---------------------------------------------------------------------------
# Episode segmentation (prompt 01)
# ---------------------------------------------------------------------------

SEGMENTATION_PROMPT = """You are a conversation analyst. Group the following numbered messages into topically coherent episodes.

An episode is a set of messages about the same topic or task. Messages within an episode may not be consecutive.

Group by TOPICAL COHERENCE, not by chronological order. Within each group, preserve the original message order.

Split when you detect:
- Topic change (different subjects, events, or tasks)
- Intent transition (from asking to commanding, from browsing to editing)
- Structural signal ("by the way", "another thing", "also")

When in doubt, split. Target 3-10 messages per episode.

MESSAGES:
{numbered_transcript}

Return JSON only, no other text:
{{"episodes": [{{"indices": [1, 2, 5], "topic": "short description", "domain_hint": "uncategorized"}}]}}"""


def _format_transcript(messages: list[dict]) -> str:
    """Format messages as numbered transcript for the segmenter."""
    lines = []
    for i, msg in enumerate(messages, 1):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if not content:
            # Tool call messages — summarize
            if msg.get("tool_calls"):
                names = [tc["function"]["name"] for tc in msg["tool_calls"]]
                content = f"[called tools: {', '.join(names)}]"
            else:
                content = "[no content]"
        # Truncate long messages
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"{i}. [{role}] {content}")
    return "\n".join(lines)


def _segment_episodes(messages: list[dict], client: LLMClient, model: str) -> list[dict]:
    """Call LLM to segment messages into episodes. Returns list of episode dicts."""
    if len(messages) < 2:
        # Too few messages, treat as single episode
        return [{"indices": list(range(1, len(messages) + 1)), "topic": "conversation", "domain_hint": "uncategorized"}]

    transcript = _format_transcript(messages)
    prompt = SEGMENTATION_PROMPT.format(numbered_transcript=transcript)

    try:
        response = client.call(
            [{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
        )
    except Exception as e:
        _info(f"segmentation failed: {e}")
        return [{"indices": list(range(1, len(messages) + 1)), "topic": "conversation", "domain_hint": "uncategorized"}]

    record_and_print(response.model, response.input_tokens, response.output_tokens, response.cached_tokens)

    # Parse JSON from response
    text = response.content or ""
    try:
        # Try to extract JSON from the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            return data.get("episodes", [])
    except (json.JSONDecodeError, KeyError):
        pass

    _info(f"segmentation parse failed, treating as single episode")
    return [{"indices": list(range(1, len(messages) + 1)), "topic": "conversation", "domain_hint": "uncategorized"}]


# ---------------------------------------------------------------------------
# Predict-calibrate extraction (prompt 02)
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT_COLD = """Extract the 1-3 MOST SIGNIFICANT insights from this conversation about "{topic}".

You are building a long-term memory. Be very selective - only knowledge that changes
how the agent approaches future work. If an episode has nothing truly significant,
return an empty list. Quality over quantity.

Express as Python whenever possible: dicts/lists for structured facts, comments for
insights with source file paths, functions for genuinely reusable project-specific
operations. Prefer Python over English.

MESSAGES:
{episode_messages}

WHAT TO EXTRACT:
- User identity and preferences (name, working style, what they care about)
- Project-specific facts (counts, categories, structure, unique features)
- Domain insights discovered (patterns, taxonomies, surprising findings)
- Gaps and TODOs found (things that are missing, searches that failed)
- Tool quirks and limitations encountered (what worked, what did not)
- Non-obvious relationships between concepts
- SOURCE FILE PATHS: when knowledge comes from a specific file, ALWAYS include the path.
  This lets the agent go directly to that file next time instead of searching from scratch.
  Paths from research docs (research/products/letta/02-memory.md), source code (r/letta/src/...),
  external surveys (research/external/...), etc.

WHAT TO SKIP:
- Generic utility functions any programmer could write
- Tool usage patterns (how to call list_dir, get_file, etc.)
- Trivial 2-line functions that restate built-in capabilities
- Temporary discussion, greetings, acknowledgments

Return JSON only:
{{"observations": [{{"content": "python data structure, insight comment, or project-specific function", "confidence": 0.8, "tags": ["tag1"]}}]}}

Example good observations (Python-first, with sources):
- "project_stats = {{'products': 38, 'categories': 7, 'concepts': 25}}\\n# Source: AGENTS.md"
- "memory_patterns = ['memory-first', 'consolidation', 'file-based', 'replay', 'code-as-memory', 'libraries']\\n# Source: research/concepts/persistent-memory/_index.md\\n# Key finding: most coding agents have NO persistent memory"
- "agentic_loop_types = {{'direct': ['Cline', 'Codex CLI', 'Goose'], 'event-driven': ['OpenHands', 'Letta'], 'delegated': ['n8n', 'CrewAI'], 'edit-driven': ['Aider'], 'research': ['PaperQA2', 'ODR'], 'tree-search': ['Moatless'], 'evolutionary': ['DGM', 'OpenEvolve']}}\\n# Source: research/concepts/agentic-loop/_index.md"
- "# GAP: cross-agent edit format comparison table does not exist\\n# Closest: research/concepts/tool-calling/_index.md\\n# 6 transport mechanisms, 33 projects x 12 dimensions"
- "def get_product_docs(product_name):\\n    \\\"\\\"\\\"Get all doc files for a studied product.\\\"\\\"\\\"\\n    base = f'research/products/{{product_name}}'\\n    return list_dir(base)"

Maximum 3 observations per episode. If nothing significant, return: {{"observations": []}}"""

EXTRACTION_PROMPT_WARM = """You have the following knowledge about "{topic}":

EXISTING KNOWLEDGE:
{existing_knowledge}

New conversation:

MESSAGES:
{episode_messages}

Extract ONLY insights that are MISSING or DIFFERENT from existing knowledge.
Focus on project-specific facts, user preferences, domain discoveries, and gaps found.
Skip generic utility functions and tool usage patterns.

Return JSON only:
{{"observations": [{{"content": "python data structure, insight, or project-specific function", "confidence": 0.8, "tags": ["tag1"]}}]}}

If existing knowledge covers everything, return: {{"observations": []}}"""


def _extract_from_episode(
    episode_messages: str,
    topic: str,
    domain: str,
    store: KnowledgeStore,
    client: LLMClient,
    model: str,
) -> list[dict]:
    """Extract observations from one episode using predict-calibrate."""
    # Check for existing knowledge on this topic
    existing = store.search(topic, limit=10)

    if existing:
        # Warm path: predict-calibrate
        existing_text = "\n".join(f"- {obs.content}" for obs in existing)
        prompt = EXTRACTION_PROMPT_WARM.format(
            topic=topic,
            existing_knowledge=existing_text,
            episode_messages=episode_messages,
        )
    else:
        # Cold path: direct extraction
        prompt = EXTRACTION_PROMPT_COLD.format(
            topic=topic,
            episode_messages=episode_messages,
        )

    try:
        response = client.call(
            [{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
        )
    except Exception as e:
        _info(f"extraction failed: {e}")
        return []

    record_and_print(response.model, response.input_tokens, response.output_tokens, response.cached_tokens)
    text = response.content or ""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            return data.get("observations", [])
    except (json.JSONDecodeError, KeyError):
        pass

    _info(f"extraction parse failed for topic: {topic}")
    return []


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------


def maybe_run_extraction(
    cfg: Config,
    client: LLMClient,
    store: KnowledgeStore,
) -> bool:
    """Check if extraction is due and run it. Returns True if extraction ran.

    Runs in foreground with visible output (D7 decision).
    """
    total_user_msgs = _count_user_messages(cfg)
    pointer = _read_pointer(cfg)
    pending = total_user_msgs - pointer

    if pending < EXTRACTION_EVERY_N_MESSAGES:
        return False

    _info(f"starting extraction ({pending} user messages since last)")

    # Load unprocessed messages
    messages = _load_messages_since(cfg, pointer)
    if not messages:
        _write_pointer(cfg, total_user_msgs)
        return False

    _info(f"loaded {len(messages)} messages for processing")

    # Use consolidation model for extraction - quality over cost
    model = cfg.llm.consolidation_model

    # Step 1: Segment into episodes
    _info("segmenting into episodes...")
    episodes = _segment_episodes(messages, client, model)
    _info(f"found {len(episodes)} episodes")

    # Step 2: Extract observations from each episode
    total_obs = 0
    for ep in episodes:
        indices = ep.get("indices", [])
        topic = ep.get("topic", "conversation")
        domain = ep.get("domain_hint", "uncategorized")

        # Gather episode messages
        ep_msgs = []
        for idx in indices:
            if 1 <= idx <= len(messages):
                ep_msgs.append(messages[idx - 1])

        if not ep_msgs:
            continue

        ep_text = _format_transcript(ep_msgs)
        _info(f"  episode: {topic} ({len(ep_msgs)} msgs)")

        # Extract
        raw_obs = _extract_from_episode(ep_text, topic, domain, store, client, model)

        # Store
        session_name = cfg.session_file.name
        for obs_data in raw_obs:
            content = obs_data.get("content", "")
            if not content:
                continue
            obs_id = store.add(
                content,
                confidence=obs_data.get("confidence", 0.8),
                tags=obs_data.get("tags", []),
                domain=domain,
                topic=topic,
                source_session=session_name,
            )
            _info(f"    + {obs_id}: {content[:80]}")
            total_obs += 1

    # Advance pointer
    _write_pointer(cfg, total_user_msgs)
    _info(f"extraction complete: {total_obs} observations from {len(episodes)} episodes")
    return True
