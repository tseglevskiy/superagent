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

DEFAULT_DATA_DIR_NAME = ".superagent"
DEFAULT_KNOWLEDGE_DIR_NAME = ".superknowledge"
DEFAULT_INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "integration"
DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_CHAT_MODEL = "anthropic/claude-opus-4.6"
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
class SandboxConfig:
    """Sandbox permission configuration."""

    # Extra paths the seatbelt sandbox is allowed to read (dotfiles, etc.)
    allowed_read_paths: list[str] = field(default_factory=list)
    # Extra paths the seatbelt sandbox is allowed to write (tool caches, etc.)
    allowed_write_paths: list[str] = field(default_factory=list)


@dataclass
class Config:
    """Top-level configuration resolved from disk + env."""

    data_dir: Path = field(default_factory=lambda: Path.cwd() / DEFAULT_DATA_DIR_NAME)
    workspace: Path = field(default_factory=lambda: Path.cwd())
    knowledge_dir: Path = field(default_factory=lambda: Path.cwd() / DEFAULT_KNOWLEDGE_DIR_NAME)
    llm: LLMConfig = field(default_factory=LLMConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    rules_files: list[str] = field(default_factory=list)

    # --- derived paths (set in __post_init__) ---
    memory_dir: Path = field(init=False)
    sessions_dir: Path = field(init=False)
    lockfile_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.memory_dir = self.data_dir / "memory"
        self.sessions_dir = self.data_dir / "sessions"
        self.lockfile_dir = self.data_dir / "lockfiles"

    # --- convenience ---

    def ensure_dirs(self) -> None:
        """Create all data directories if they do not exist."""
        for d in (
            self.data_dir,
            self.memory_dir,
            self.sessions_dir,
            self.lockfile_dir,
            self.knowledge_dir,
            self.knowledge_dir / "domains",
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
    knowledge_dir: Path | None = None,
    provider: str | None = None,
) -> Config:
    """Build a Config from disk file + env vars + CLI overrides.

    Priority (highest wins): CLI arg > env var > config.yaml > default.
    """
    resolved_workspace = workspace or Path.cwd()
    resolved_data = data_dir or Path(
        os.environ.get("SUPERAGENT_DATA_DIR", str(resolved_workspace / DEFAULT_DATA_DIR_NAME))
    )
    resolved_knowledge = knowledge_dir or Path(
        os.environ.get("SUPERAGENT_KNOWLEDGE_DIR", str(resolved_workspace / DEFAULT_KNOWLEDGE_DIR_NAME))
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

    # Rules files: list of paths relative to workspace
    rules_files = file_data.get("rules_files", [])
    if not isinstance(rules_files, list):
        rules_files = []

    # Sandbox config
    sandbox_section = file_data.get("sandbox", {})
    raw_paths = sandbox_section.get("allowed_read_paths", [])
    if not isinstance(raw_paths, list):
        raw_paths = []
    raw_write_paths = sandbox_section.get("allowed_write_paths", [])
    if not isinstance(raw_write_paths, list):
        raw_write_paths = []
    sandbox_cfg = SandboxConfig(
        allowed_read_paths=[str(p) for p in raw_paths],
        allowed_write_paths=[str(p) for p in raw_write_paths],
    )

    cfg = Config(
        data_dir=resolved_data,
        workspace=resolved_workspace,
        knowledge_dir=resolved_knowledge,
        llm=llm_cfg,
        sandbox=sandbox_cfg,
        rules_files=[str(r) for r in rules_files],
    )
    cfg.ensure_dirs()
    return cfg
