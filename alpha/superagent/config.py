"""Configuration and paths.

Everything the agent needs to know about where files live and how to connect to LLMs.
All paths are resolved once at startup. The rest of the system reads these.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "sandbox"
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_CHAT_MODEL = "anthropic/claude-3.5-haiku"
DEFAULT_FAST_MODEL = "openai/gpt-4.1-nano"
DEFAULT_CONSOLIDATION_MODEL = "anthropic/claude-opus-4.6"
DEFAULT_OLLAMA_BASE = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:14b"

# How many user messages trigger extraction (episode segmentation + predict-calibrate)
EXTRACTION_EVERY_N_MESSAGES = 10
# How many observations per domain before consolidation into patterns
CONSOLIDATION_OBSERVATION_CAP = 20


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = "openrouter"  # "openrouter" | "ollama"
    api_key: str = ""
    base_url: str = DEFAULT_OPENROUTER_BASE
    chat_model: str = DEFAULT_CHAT_MODEL
    fast_model: str = DEFAULT_FAST_MODEL
    consolidation_model: str = DEFAULT_CONSOLIDATION_MODEL
    # ollama-specific
    ollama_base: str = DEFAULT_OLLAMA_BASE
    ollama_model: str = DEFAULT_OLLAMA_MODEL


@dataclass
class Config:
    """Top-level configuration resolved from disk + env."""

    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    workspace: Path = field(default_factory=lambda: Path.cwd())
    llm: LLMConfig = field(default_factory=LLMConfig)

    # --- derived paths (set in __post_init__) ---
    memory_dir: Path = field(init=False)
    sessions_dir: Path = field(init=False)
    knowledge_dir: Path = field(init=False)
    lockfile_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.memory_dir = self.data_dir / "memory"
        self.sessions_dir = self.data_dir / "sessions"
        self.knowledge_dir = self.data_dir / "knowledge"
        self.lockfile_dir = self.data_dir / "lockfiles"

    # --- convenience ---

    def ensure_dirs(self) -> None:
        """Create all data directories if they do not exist."""
        for d in (
            self.data_dir,
            self.memory_dir,
            self.sessions_dir,
            self.knowledge_dir,
            self.knowledge_dir / "domains",
            self.lockfile_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def session_file(self) -> Path:
        return self.sessions_dir / "current.jsonl"

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.yaml"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_config(
    *,
    workspace: Path | None = None,
    data_dir: Path | None = None,
    provider: str | None = None,
) -> Config:
    """Build a Config from disk file + env vars + CLI overrides.

    Priority (highest wins): CLI arg > env var > config.yaml > default.
    """
    resolved_data = data_dir or Path(
        os.environ.get("SUPERAGENT_DATA_DIR", str(DEFAULT_DATA_DIR))
    )
    config_path = resolved_data / "config.yaml"

    # --- load YAML if present ---
    file_data: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            file_data = yaml.safe_load(f) or {}

    llm_section = file_data.get("llm", {})

    # Provider: CLI > env > yaml > default
    resolved_provider = (
        provider
        or os.environ.get("SUPERAGENT_PROVIDER")
        or llm_section.get("provider", "openrouter")
    )

    # API key: env > yaml
    api_key = os.environ.get("OPENROUTER_API_KEY", "") or llm_section.get(
        "api_key", ""
    )

    llm_cfg = LLMConfig(
        provider=resolved_provider,
        api_key=api_key,
        base_url=llm_section.get("base_url", DEFAULT_OPENROUTER_BASE),
        chat_model=llm_section.get("chat_model", DEFAULT_CHAT_MODEL),
        fast_model=llm_section.get("fast_model", DEFAULT_FAST_MODEL),
        ollama_base=os.environ.get(
            "OLLAMA_HOST",
            llm_section.get("ollama_base", DEFAULT_OLLAMA_BASE),
        ),
        ollama_model=llm_section.get("ollama_model", DEFAULT_OLLAMA_MODEL),
    )

    cfg = Config(
        data_dir=resolved_data,
        workspace=workspace or Path.cwd(),
        llm=llm_cfg,
    )
    cfg.ensure_dirs()
    return cfg
