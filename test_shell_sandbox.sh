#!/usr/bin/env bash
# Test the shell sandbox module.
# Usage from project root:
#   bash superagent/test_shell_sandbox.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ALPHA_DIR="$SCRIPT_DIR/alpha"

CONDA_ENV="sandbox"

AGENT_DIR="$PROJECT_ROOT/.superagent"
mkdir -p "$AGENT_DIR"

# Activate conda (not active by default in non-interactive shells)
eval "$(conda shell.bash hook 2>/dev/null)"
conda activate "$CONDA_ENV"

export PYTHONPATH="$ALPHA_DIR:${PYTHONPATH:-}"

exec python "$SCRIPT_DIR/test_shell_sandbox.py" "$AGENT_DIR"
