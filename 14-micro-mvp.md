# Micro-MVP — A Knowledge Processing Sandbox

## Goal

A chatbot that does REAL WORK on a user's file storage.
The file storage is the user's working environment — not a corpus, not training data.
The agent lists files, finds duplicates, edits content, creates scripts, answers questions about the storage.

Knowledge comes from the EXPERIENCE of doing this work — learning patterns about the user's file organization, common requests, which approaches work, what the user prefers.
Artificial conversations about nothing will not produce meaningful knowledge to consolidate.
We need real tasks that generate real observations.

The agent part is simple — a chatbot with file tools and Python execution.
The KNOWLEDGE PROCESSING part is what we are testing.

---

## What We Build

### The Environment: A Large Read-Mostly File Storage

A real NFS mount or a local directory with thousands of files.
Photos, documents, code, archives, logs — whatever the user actually has.
The agent can read freely, write when asked.
This is not a test dataset — it is real stuff the user works with daily.

### The Agent: A File Assistant

A CLI chatbot that helps the user work with their files.
Real tasks, real output, real value from day one.

```
$ python -m superagent --workspace /mnt/storage
> List all PDF files larger than 10MB sorted by date
Found 47 PDF files >10MB:
  2026-03-15  128MB  reports/q1-analysis.pdf
  2026-03-12   45MB  presentations/board-deck.pdf
  ...

> Find duplicate photos in the vacation-2025 folder
Scanning... found 23 potential duplicates (by hash):
  IMG_4521.jpg == IMG_4521 (1).jpg (identical, 4.2MB)
  ...

> Write a script that renames all files in downloads/ to lowercase
```

### The Experiment: Does Knowledge Accumulate?

After 50 real tasks:
- Does the agent learn the user's file organization? ("photos are in ~/media/photos/{year}/")
- Does it learn common request patterns? ("when user says duplicates, check by content hash first")
- Does it learn tool preferences? ("user prefers Python one-liners over shell scripts")
- Do domains emerge? ("file organization", "data cleanup", "scripting")
- Does consolidation produce useful generalizations?

---

## Scope: What's In, What's Out

### IN (build this)

| Component | Doc 13 Reference | Notes |
|---|---|---|
| `engine.py` | Stateless — rebuild context from disk per LLM call | No in-memory state. Read files, call LLM, write results to disk. Restart = free. |
| `memory.py` | WorkingMemory with blocks | Persona, workspace_info, current_domain |
| `memory.py` | KnowledgeStore skeleton | Observations, patterns, domain dirs, SQLite index |
| `tools.py` | File tools + Python exec | get_file, get_lines, replace_lines, create_file, python_exec |
| `llm.py` | AnthropicClient | Claude Sonnet for chat, Haiku for background |
| `bus.py` | EventBus, all three tiers | Instant (utility), fast (domain detection), background (consolidation) |
| Lockfile | `current.lock` | Hardcoded, not evolved |
| CLI | stdin/stdout | readline loop |

### OUT (not in this MVP)

- SubAgent spawning / context inheritance
- Shadow mode / A/B testing
- Admission pipeline / lockfile evolution
- FocusChain / tree compression
- Reflection processes (consistency, validity, gap detection)
- GEPA optimization
- Any form of self-modification
- Code-as-action (agent writes Python as its action modality) — we use traditional tool calls for now

---

## The Tools

### File Operations

```python
async def get_file(path: str) -> str:
    """Read a file. Returns content as string."""

async def get_lines(path: str, start: int, end: int) -> str:
    """Read specific lines from a file."""

async def replace_lines(path: str, start: int, end: int, content: str) -> str:
    """Replace specific lines in a file."""

async def replace_file(path: str, content: str) -> str:
    """Overwrite a file with new content."""

async def create_file(path: str, content: str) -> str:
    """Create a new file."""

async def list_dir(path: str, pattern: str = "*", recursive: bool = False) -> str:
    """List directory contents with optional glob pattern."""
```

### Python Execution

```python
async def python_exec(code: str) -> str:
    """Execute a Python snippet. Has access to os, pathlib, hashlib, etc.
    Workspace root is available as WORKSPACE variable."""
```

This is the key tool — the agent writes small Python scripts to handle complex file tasks (find duplicates by hash, batch rename, analyze directory sizes, generate reports).
The scripts the agent writes become candidates for Knowledge Store patterns.

### Knowledge Tools

```python
async def memory_update(label: str, old_content: str, new_content: str) -> str:
    """Update a working memory block."""

async def knowledge_search(query: str, domain: str | None = None) -> str:
    """Search the agent's accumulated knowledge."""
```

---

## Background Operations

### Episode Segmentation

After each conversation, group messages by topic:
- "finding duplicate files" = one episode
- "renaming convention discussion" = another episode
- Non-consecutive messages about the same topic get grouped together (Nemori pattern)

### Predict-Calibrate Extraction

After episode creation:
- Retrieve relevant existing knowledge
- Predict what the episode should contain based on existing knowledge
- Extract only genuinely new observations
- Examples of real observations:
  - "User stores photos in ~/media/photos/{year}/ organized by month"
  - "When looking for duplicates, content hash (SHA-256) is more reliable than filename matching"
  - "User prefers Python scripts over shell commands for file operations"
  - "The downloads/ folder accumulates duplicates from browser re-downloads"

### Domain Detection

Classify tasks into domains that emerge from actual usage:
- "file-organization" — listing, sorting, finding, moving files
- "data-cleanup" — duplicates, temp files, empty dirs, broken links
- "scripting" — writing automation scripts for batch operations
- "content-search" — grep-like operations, finding specific content

### Consolidation (on idle)

When the user has not typed for 30 seconds:
- Cluster observations within domains
- Generalize into patterns:
  - Observation: "used SHA-256 hash for photo duplicates" + "used SHA-256 for document duplicates" + "used file size + hash for video duplicates"
  - Pattern: "For duplicate detection: hash-based comparison (SHA-256). For large files (>100MB), pre-filter by size before hashing."

---

## The Knowledge Store

```
~/.superagent-sandbox/
  config.yaml
  lockfiles/
    current.lock
  knowledge/
    domains/
      file-organization/
        profile.yaml
        observations/*.yaml
        patterns/
      data-cleanup/
        profile.yaml
        observations/*.yaml
        patterns/
      scripting/
        profile.yaml
        observations/*.yaml
        patterns/
    index.db
  sessions/
    *.jsonl
```

---

## The Tasks We Run

### Phase 1: Cold Start (tasks 1-10)

Simple file operations.
The agent uses tools, gets results, the user reacts.
Observations accumulate.

- "How much space does each top-level folder use?"
- "Find all files modified in the last week"
- "List the 20 largest files"
- "Are there any empty directories?"
- "Show me the file type distribution in downloads/"

### Phase 2: Domain Formation (tasks 11-25)

Repeated task types build domain depth.
Background consolidation should form patterns.

- "Find duplicate files in photos/" (data-cleanup domain deepens)
- "Rename all screenshots to include the date" (scripting domain forms)
- "Organize downloads/ by file type" (file-organization domain forms)
- "Find all TODO comments in the code/ directory" (content-search domain forms)

### Phase 3: Knowledge Reuse (tasks 26-50)

Ask tasks similar to earlier ones.
Does the agent approach them faster, using learned patterns?

- "Find duplicates in videos/" — should use the duplicate detection pattern learned from photos
- "Organize another folder" — should use the organization approach that worked before
- "Write a cleanup script" — should use scripting patterns from earlier tasks

### Measurement

| Metric | How |
|---|---|
| Task completion | Did the agent complete the task? (binary) |
| Steps per task | How many tool calls to complete similar tasks over time (should decrease) |
| Token cost per task | Total tokens (should decrease as patterns replace raw reasoning) |
| Knowledge Store size | Observations and patterns per domain |
| Domain count | How many domains auto-discovered |
| Pattern reuse | Did the agent use knowledge_search before a task? (learning indicator) |
| User corrections | How often did the user correct the agent? (should decrease) |

---

## What We Learn

1. **Do real tasks produce extractable knowledge?** Unlike artificial conversations, real file operations have concrete outcomes — does the pipeline capture useful patterns from them?
2. **Does predict-calibrate filter noise?** File operations produce lots of tool output — does the extraction focus on the useful parts?
3. **Do domains emerge from real usage?** Does the agent discover natural task categories without being told?
4. **Does the agent get faster?** Same type of task, fewer steps over time — the growth delta from doc 09.
5. **Do Python scripts become reusable patterns?** When the agent writes a duplicate-finder script, does it become a Tool artifact that gets reused?
6. **What breaks?** Where does the pipeline produce garbage?

---

## Implementation Plan

### Day 1: The Shell

- `engine.py` — stateless: read disk → build context → call LLM → write results to disk
- `llm.py` — AnthropicClient
- CLI readline loop that appends user messages to session JSONL
- Working memory blocks as text files on disk (persona.md, workspace_info.md)
- No in-memory state — kill the process, restart, everything is on disk
- Result: a chatbot that talks but cannot do anything. Restart continues the conversation.

### Day 2: File Tools + Python Exec

- File operation tools (get_file, list_dir, create_file, etc.)
- Python execution with workspace access
- Workspace path from --workspace CLI arg
- Result: a chatbot that can do real file work

### Day 3: Working Memory

- WorkingMemory with blocks: persona, workspace_info, current_domain
- memory_update tool
- Block rendering in system prompt (XML with metadata)
- Result: agent remembers things within a session

### Day 4: Knowledge Store + Observations

- KnowledgeStore with domain dirs and SQLite index
- Episode segmentation on message buffer threshold
- Observation storage in YAML
- knowledge_search tool
- Result: observations accumulate from real tasks

### Day 5: Predict-Calibrate

- Retrieve existing knowledge before extraction
- Predict → compare → extract delta
- Deduplication via embedding similarity
- Result: only genuinely new observations stored

### Day 6: Domain Detection

- Auto-classify tasks into domains
- Create domain profiles when patterns stabilize
- Load domain blocks into working memory
- Result: domains form from task types

### Day 7: Background Consolidation

- Idle detection (30-second timer)
- Observation clustering within domains
- Pattern generation via LLM
- Capacity limits triggering consolidation
- Result: patterns form from accumulated observations

### Day 8-10: Run Experiments

- Execute 50 real file tasks across 3 phases
- Measure all metrics
- Inspect the Knowledge Store
- Document what works and what breaks

---

## Success Criteria

**Minimum:** Pipeline runs for 50 tasks. Observations accumulate. At least 2 domains discovered. No crashes.

**Good:** Patterns form that correctly describe the user's file organization and preferred approaches. Agent uses knowledge_search by task 30+. Steps per similar task measurably decrease.

**Great:** Python scripts written for one task become reusable patterns for similar tasks. Cross-domain patterns emerge. The Knowledge Store is something the user would look at and say "yes, it understands how I work."
