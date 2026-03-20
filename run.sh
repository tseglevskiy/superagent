#!/usr/bin/env bash
# Run the superagent.
# Activates conda, sets PYTHONPATH, uses .superagent/ at project root as data dir.
#
# Usage:
#   ./superagent/run.sh           # normal
#   ./superagent/run.sh -v        # verbose
#   ./superagent/run.sh -m model  # override model

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ALPHA_DIR="$SCRIPT_DIR/alpha"

CONDA_ENV="sandbox"

# Agent working directory at project root
AGENT_DIR="$PROJECT_ROOT/.superagent"
mkdir -p "$AGENT_DIR"

# Activate conda (not active by default in non-interactive shells)
eval "$(conda shell.bash hook 2>/dev/null)"
conda activate "$CONDA_ENV"

export PYTHONPATH="$ALPHA_DIR:${PYTHONPATH:-}"

cd "$PROJECT_ROOT"
# Use `python` not `python3` — conda activate sets `python` to the env's
# interpreter, but `python3` may still resolve to Homebrew's system Python.
exec python -m superagent --workspace "$PROJECT_ROOT" --data-dir "$AGENT_DIR" "$@"
