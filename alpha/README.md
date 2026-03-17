# Superagent Alpha

A knowledge-processing file workspace assistant.  Day 1: the shell.

## Setup

```bash
cd superagent/alpha
conda env create -f environment.yml
conda activate sandbox
```

## Run

```bash
# With OpenRouter (needs OPENROUTER_API_KEY env var)
python -m superagent --workspace /path/to/your/files

# With Ollama (local)
python -m superagent --provider ollama --workspace /path/to/your/files

# Override model
python -m superagent -m anthropic/claude-sonnet-4 -w ~/Documents

# Verbose logging
python -m superagent -v -w ~/Documents
```

## Data

Everything lives in `superagent/alpha/sandbox/` (inside the project, not hidden):

```
superagent/alpha/sandbox/
  config.yaml              # optional config overrides
  memory/
    persona.md             # agent identity
    workspace_info.md      # learned workspace structure
    user_preferences.md    # learned user preferences
    current_domain.md      # auto-detected domain
  sessions/
    current.jsonl          # conversation history (append-only)
  knowledge/               # (future) accumulated knowledge
  lockfiles/               # (future) versioned configurations
```

Kill the process, restart — conversation continues from the JSONL.

## Commands

- `/new`    — archive current session, start fresh
- `/status` — show config and session stats
- `/quit`   — exit

## Architecture

Stateless disk-first design. Every LLM call:

1. Read memory blocks from disk files
2. Read conversation history from session JSONL
3. Compile system prompt with memory blocks as XML
4. Call LLM via OpenRouter or Ollama
5. Write response to session JSONL
6. Display to user

No in-memory state survives between turns. The disk IS the state.
