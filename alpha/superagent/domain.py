"""Domain detection — auto-classify the current task into a domain.

Runs after each user turn using the fast model. Updates the current_domain
memory block, which the agent sees but cannot edit (read-only for the agent,
written by the system).

A new domain is NOT created on first mention — requires 3+ observations
with the same domain_hint before a DomainProfile is created.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import yaml

from .atomicfile import atomic_write
from .budget import record_and_print
from .config import Config
from .knowledge import KnowledgeStore, sanitize_name
from .llm import LLMClient

log = logging.getLogger(__name__)

MAGENTA = "\033[35m"
DIM = "\033[2m"
RESET = "\033[0m"


def _info(text: str) -> None:
    print(f"{DIM}[domain]{RESET} {text}")


# ---------------------------------------------------------------------------
# Domain detection prompt
# ---------------------------------------------------------------------------

DOMAIN_PROMPT = """Classify this user request into one of the existing domains, or suggest a new domain.

EXISTING DOMAINS:
{domain_list}

USER REQUEST:
{user_message}

RECENT CONTEXT (last 3 messages):
{recent_context}

Return JSON only:
{{"domain": "existing-domain-name-or-new", "confidence": 0.0-1.0, "new_description": "one sentence if new domain"}}

Rules:
- Use an existing domain if the request clearly fits (confidence > 0.7)
- Domain names are lowercase-hyphenated: file-organization, data-cleanup, project-overview
- If unsure, use the most general existing domain
- Suggest a new domain only if it clearly does not fit any existing one"""


def _get_existing_domains(knowledge_dir: Path) -> list[dict]:
    """Scan disk for existing domains with observation counts."""
    domains = []
    domains_dir = knowledge_dir / "domains"
    if not domains_dir.exists():
        return domains
    for d in sorted(domains_dir.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        obs_dir = d / "observations"
        count = 0
        if obs_dir.exists():
            count = len([f for f in obs_dir.glob("*.py") if f.is_file()])
        domains.append({"name": name, "observations": count})
    return domains


def _get_recent_messages(cfg: Config, n: int = 3) -> str:
    """Get the last N user messages for context."""
    if not cfg.session_file.exists():
        return "(no history)"
    messages = []
    for line in cfg.session_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("role") == "user":
                messages.append(msg.get("content", "")[:200])
        except json.JSONDecodeError:
            continue
    return "\n".join(messages[-n:]) if messages else "(no history)"


async def detect_domain(
    cfg: Config,
    client: LLMClient,
    user_message: str,
) -> str | None:
    """Detect the domain for the current user message. Returns domain name or None."""
    domains = _get_existing_domains(cfg.knowledge_dir)

    if not domains:
        domain_list = "(no domains yet — all observations are uncategorized)"
    else:
        lines = []
        for d in domains:
            lines.append(f"- {d['name']} ({d['observations']} observations)")
        domain_list = "\n".join(lines)

    recent = _get_recent_messages(cfg, n=3)

    prompt = DOMAIN_PROMPT.format(
        domain_list=domain_list,
        user_message=user_message[:500],
        recent_context=recent,
    )

    try:
        response = await client.call(
            [{"role": "user", "content": prompt}],
            model=cfg.llm.fast_model,
            temperature=0.0,
        )
    except Exception as e:
        log.warning("domain detection failed: %s", e)
        return None

    record_and_print(response.model, response.input_tokens, response.output_tokens, response.cached_tokens)
    text = response.content or ""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            domain = sanitize_name(data.get("domain", "uncategorized"))
            confidence = float(data.get("confidence", 0.0))
            if confidence >= 0.5:
                return domain
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    return None


def update_current_domain(cfg: Config, domain: str | None) -> None:
    """Write the detected domain to the current_domain memory block.

    This block is read-only for the agent — only the system writes to it.
    """
    domain_file = cfg.memory_dir / "current_domain.yaml"
    if domain:
        # Get domain stats
        domains = _get_existing_domains(cfg.knowledge_dir)
        domain_info = next((d for d in domains if d["name"] == domain), None)
        obs_count = domain_info["observations"] if domain_info else 0
        entries = {
            "active_domain": domain,
            "observations_in_domain": str(obs_count),
        }
    else:
        entries = {}
    atomic_write(domain_file, yaml.dump(entries, default_flow_style=False, allow_unicode=True))


# Tracks new domain suggestions before they become real domains (3+ threshold)
_NEW_DOMAIN_FILE = "pending_domains.yaml"


def _read_pending(cfg: Config) -> dict[str, int]:
    """Read pending domain counts from disk."""
    path = cfg.data_dir / _NEW_DOMAIN_FILE
    if path.exists():
        try:
            return yaml.safe_load(path.read_text()) or {}
        except Exception:
            return {}
    return {}


def _write_pending(cfg: Config, pending: dict[str, int]) -> None:
    atomic_write(cfg.data_dir / _NEW_DOMAIN_FILE,
                 yaml.dump(pending, default_flow_style=False))


async def maybe_detect_domain(
    cfg: Config,
    client: LLMClient,
    user_message: str,
) -> str | None:
    """Detect domain and update the memory block. Returns detected domain.

    New domains require 3+ mentions before being created. Until then,
    they accumulate in pending_domains.yaml and map to 'uncategorized'.
    """
    domain = await detect_domain(cfg, client, user_message)
    if not domain:
        _info("domain: (not detected)")
        return None

    # Check if this domain already exists on disk
    existing = _get_existing_domains(cfg.knowledge_dir)
    existing_names = {d["name"] for d in existing}

    if domain in existing_names:
        # Known domain — use it
        _info(f"domain: {domain}")
        update_current_domain(cfg, domain)
        return domain

    # New domain — check 3+ threshold
    pending = _read_pending(cfg)
    pending[domain] = pending.get(domain, 0) + 1
    _write_pending(cfg, pending)

    if pending[domain] >= 3:
        # Threshold met — create the domain
        _info(f"domain: {domain} (NEW - threshold met after {pending[domain]} mentions)")
        # Create domain directory
        (cfg.knowledge_dir / "domains" / domain / "observations").mkdir(parents=True, exist_ok=True)
        update_current_domain(cfg, domain)
        return domain
    else:
        _info(f"domain: {domain} (pending {pending[domain]}/3)")
        update_current_domain(cfg, "uncategorized")
        return "uncategorized"
