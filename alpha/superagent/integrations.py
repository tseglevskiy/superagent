"""Auto-discovery integration loader.

Scans the integration/ directory for Python files, imports each one,
calls its register(workspace) function, and collects functions, prompts,
and lifecycle hooks.

Protocol: each .py file in integration/ must define:

    def register(workspace: Path) -> dict:
        return {
            "name": "my_integration",
            "functions": {"func_name": callable, ...},
            "system_prompt": "...",              # optional
            "cleanup_step": callable_or_None,    # optional
            "reset_session": callable_or_None,   # optional
        }

Drop a file, restart, done.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class Integration:
    """One loaded integration module."""

    name: str
    functions: dict[str, Any] = field(default_factory=dict)
    system_prompt: str = ""
    cleanup_step: Callable | None = None
    reset_session: Callable | None = None


class IntegrationManager:
    """Holds all loaded integrations and provides aggregated access."""

    def __init__(self) -> None:
        self._integrations: list[Integration] = []

    def add(self, integration: Integration) -> None:
        self._integrations.append(integration)
        log.info("loaded integration: %s (%d functions)", integration.name, len(integration.functions))

    @property
    def integrations(self) -> list[Integration]:
        return list(self._integrations)

    def all_functions(self) -> dict[str, Any]:
        """Merge all integration functions into one dict."""
        merged: dict[str, Any] = {}
        for integ in self._integrations:
            for name, func in integ.functions.items():
                if name in merged:
                    log.warning(
                        "function %r from %s overrides previous definition",
                        name, integ.name,
                    )
                merged[name] = func
        return merged

    def all_system_prompts(self) -> str:
        """Concatenate all integration system prompts."""
        parts = []
        for integ in self._integrations:
            if integ.system_prompt:
                parts.append(integ.system_prompt.strip())
        return "\n\n".join(parts)

    def cleanup_all(self) -> None:
        """Call cleanup_step on all integrations that define it."""
        for integ in self._integrations:
            if integ.cleanup_step:
                try:
                    integ.cleanup_step()
                except Exception:
                    log.exception("cleanup_step failed for %s", integ.name)

    def reset_all(self) -> None:
        """Call reset_session on all integrations that define it."""
        for integ in self._integrations:
            if integ.reset_session:
                try:
                    integ.reset_session()
                except Exception:
                    log.exception("reset_session failed for %s", integ.name)


def discover(integration_dir: Path, workspace: Path) -> IntegrationManager:
    """Scan integration_dir for .py files, import each, call register().

    Returns an IntegrationManager with all successfully loaded integrations.
    Files that fail to load are logged and skipped.
    """
    manager = IntegrationManager()

    if not integration_dir.exists():
        log.warning("integration directory does not exist: %s", integration_dir)
        return manager

    for py_file in sorted(integration_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"_integration_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                log.warning("cannot load %s: no spec", py_file)
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
        except Exception:
            log.exception("failed to import integration %s", py_file.name)
            continue

        register_fn = getattr(mod, "register", None)
        if register_fn is None:
            log.warning("integration %s has no register() function, skipping", py_file.name)
            continue

        try:
            result = register_fn(workspace)
        except Exception:
            log.exception("register() failed for %s", py_file.name)
            continue

        if not isinstance(result, dict):
            log.warning("register() in %s did not return a dict, skipping", py_file.name)
            continue

        integ = Integration(
            name=result.get("name", py_file.stem),
            functions=result.get("functions", {}),
            system_prompt=result.get("system_prompt", ""),
            cleanup_step=result.get("cleanup_step"),
            reset_session=result.get("reset_session"),
        )
        manager.add(integ)

    return manager
