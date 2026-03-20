"""Consolidation — merge observations into patterns when capacity exceeded.

Runs in foreground (D7): visible output, triggered after extraction.
When a domain has more than CONSOLIDATION_OBSERVATION_CAP observations,
call Opus to merge them into fewer, more general patterns.

Patterns are stored as .py files (same format as observations) in patterns/ dir.
Consumed observations are retired.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .budget import record_and_print
from .config import Config, CONSOLIDATION_OBSERVATION_CAP
from .knowledge import KnowledgeStore, Observation, sanitize_name
from .llm import LLMClient

MAGENTA = "\033[35m"
DIM = "\033[2m"
RESET = "\033[0m"


def _info(text: str) -> None:
    print(f"{MAGENTA}[consolidation]{RESET} {text}")


# ---------------------------------------------------------------------------
# Consolidation prompt — adapted for Python-first format
# ---------------------------------------------------------------------------

CONSOLIDATION_PROMPT = """You are a knowledge analyst. You have {count} observations from the "{domain}" domain.
The capacity limit is {limit}. You need to consolidate these into fewer, more general patterns.

OBSERVATIONS:
{observations_text}

Your task:
1. Identify groups of observations that describe the same underlying pattern
2. For each group, write ONE consolidated Python observation that captures the pattern
3. The consolidation must be MORE useful than any individual observation
4. Express as Python: data structures, comments with source paths, functions if applicable
5. Merge related functions into more general ones, merge related data into richer structures

Rules:
- Each pattern must cover at least 2 source observations
- Observations that do not fit any group should be kept as-is
- The total count of patterns + kept observations must be under {limit}
- Include source file paths from the original observations
- Keep the Python-first style: dicts, lists, comments, functions

Return JSON only:
{{"patterns": [{{"content": "consolidated python code", "source_ids": ["obs-001", "obs-002"], "confidence": 0.9, "tags": ["tag1"]}}], "kept_ids": ["obs-007"], "retired_ids": ["obs-001", "obs-002"]}}

If nothing can be meaningfully consolidated, return:
{{"patterns": [], "kept_ids": [all observation ids], "retired_ids": []}}"""


def _format_observations(observations: list[Observation]) -> str:
    """Format observations for the consolidation prompt."""
    parts = []
    for obs in observations:
        parts.append(f"--- {obs.id} (domain={obs.domain}, topic={obs.topic}) ---")
        parts.append(obs.content.strip())
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main consolidation function
# ---------------------------------------------------------------------------


def maybe_run_consolidation(
    cfg: Config,
    client: LLMClient,
    store: KnowledgeStore,
) -> bool:
    """Check if any domain exceeds capacity and consolidate. Returns True if ran."""
    # Check each domain
    domains_dir = cfg.knowledge_dir / "domains"
    if not domains_dir.exists():
        return False

    ran = False
    for domain_dir in sorted(domains_dir.iterdir()):
        if not domain_dir.is_dir():
            continue
        domain_name = domain_dir.name
        count = store.count(domain=domain_name)

        if count <= CONSOLIDATION_OBSERVATION_CAP:
            continue

        _info(f"domain '{domain_name}' has {count} observations (cap={CONSOLIDATION_OBSERVATION_CAP})")
        _info("starting consolidation...")

        # Load all active observations for this domain
        all_obs = store.load_all_active()
        domain_obs = [o for o in all_obs if o.domain == domain_name]

        if len(domain_obs) <= CONSOLIDATION_OBSERVATION_CAP:
            continue

        obs_text = _format_observations(domain_obs)
        prompt = CONSOLIDATION_PROMPT.format(
            count=len(domain_obs),
            domain=domain_name,
            limit=CONSOLIDATION_OBSERVATION_CAP,
            observations_text=obs_text,
        )

        # Call Opus for consolidation
        model = cfg.llm.consolidation_model
        _info(f"calling {model} with {len(domain_obs)} observations...")

        try:
            response = client.call(
                [{"role": "user", "content": prompt}],
                model=model,
                temperature=0.3,
            )
        except Exception as e:
            _info(f"consolidation failed: {e}")
            continue

        record_and_print(response.model, response.input_tokens, response.output_tokens, response.cached_tokens)

        # Parse response
        text = response.content or ""
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start < 0 or end <= start:
                _info("consolidation parse failed - no JSON found")
                continue
            data = json.loads(text[start:end])
        except json.JSONDecodeError as e:
            _info(f"consolidation parse failed: {e}")
            continue

        patterns = data.get("patterns", [])
        retired_ids = set(data.get("retired_ids", []))
        kept_ids = set(data.get("kept_ids", []))

        _info(f"result: {len(patterns)} patterns, {len(kept_ids)} kept, {len(retired_ids)} retired")

        # Store patterns as new observations with higher confidence
        for pat in patterns:
            content = pat.get("content", "")
            if not content:
                continue
            source_ids = pat.get("source_ids", [])
            tags = pat.get("tags", [])
            tags.append("consolidated")

            obs_id = store.add(
                content,
                confidence=pat.get("confidence", 0.9),
                tags=tags,
                domain=domain_name,
                topic=f"consolidated from {len(source_ids)} observations",
                source_session="consolidation",
            )
            _info(f"  + pattern {obs_id}: {content[:80]}")

        # Retire consumed observations
        for obs_id in retired_ids:
            result = store.retire(obs_id)
            _info(f"  - retired {obs_id}")

        _info(f"consolidation complete for '{domain_name}'")
        ran = True

    return ran
