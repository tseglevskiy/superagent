"""Sandboxed Python executor.

Uses smolagents' LocalPythonExecutor (AST-based sandbox).
Functions are injected from integration modules discovered at startup.
The LLM cannot import os, subprocess, pathlib, etc. — it can only use
the controlled functions provided by integrations.
"""

from __future__ import annotations

import logging
from typing import Any

from smolagents.local_python_executor import LocalPythonExecutor

log = logging.getLogger(__name__)


def make_executor(functions: dict[str, Any]) -> LocalPythonExecutor:
    """Create a sandboxed executor with the given functions injected.

    Args:
        functions: name -> callable mapping from integration modules.
    """
    executor = LocalPythonExecutor(
        additional_authorized_imports=["json", "csv", "re", "collections", "itertools", "math", "statistics"],
        additional_functions=functions,
        max_print_outputs_length=10_000,
        timeout_seconds=30,
    )
    executor.send_tools({})  # initializes static_tools with base + our functions
    log.info("sandbox executor created with %d functions", len(functions))
    return executor
