# MVP Logbook and Decisions

Design decisions made during implementation. Open questions at the bottom.

## Architecture Decisions

### D1: Code-as-action, not JSON tools (Day 2)
File operations are Python functions inside the sandbox, not separate API tools.
Inspired by smolagents. Only "life operations" (memory_update, knowledge_search, python_exec)
are native API tools. Workspace functions (get_file, list_dir, etc.) are callable inside python_exec.

### D2: smolagents LocalPythonExecutor for sandboxing (Day 2)
AST-based interpreter blocks os, subprocess, pathlib, open(), eval, exec.
Our workspace functions are injected as allowed callables.
Apache 2.0 license, pip-installable.

### D3: YAML key-value memory blocks (Day 3)
Memory blocks are YAML files with named keys, not plain text.
Agent updates individual keys by name - no line counting needed.
Empty value = delete. Surgical updates without touching other keys.

### D4: Observations have topic field (Day 4)
Each observation YAML stores a `topic` field from the episode it was extracted from.
Not visible to the agent, not searchable - kept for history and research purposes only.

### D5: Explicit retire_observation function (Day 4)
The LLM can retire outdated observations immediately via a tool call.
Retired observations get `retired: true` flag, excluded from search, stay on disk.
Cleaner than relying on the LLM to resolve conflicts at inference time.

### D6: Observations visible with IDs and timestamps (Day 4)
knowledge_search results show observation IDs and timestamps.
Sorted newest to oldest. System prompt explains this ordering.
Agent uses IDs to retire outdated observations.

### D7: Consolidation is foreground, not background (Day 7)
Consolidation switches the state machine to a consolidation state.
Logs interesting details visibly to the same output stream.
Finishes in the state waiting for user input.
This is a research project - everything should be visible to the user.

### D8: Consolidation model (Day 7)
Use claude-opus-4.6 via OpenRouter for consolidation. 1M context window.
Separate from the chat model (haiku) - consolidation needs deep reasoning.

### D9: Consolidation frequency is a tunable constant
Easy to change, not overengineered. Just a constant somewhere in config.
Currently: EXTRACTION_EVERY_N_MESSAGES = 10, CONSOLIDATION_OBSERVATION_CAP = 20.

### D10: Data directory inside project (Day 1)
sandbox/ folder at superagent/alpha/sandbox/, not ~/.superagent-sandbox.
No hidden folders. Gitignored.

### D11: Default chat model: anthropic/claude-3.5-haiku (Day 2)
Cheap, fast, stable, good tool calling via OpenRouter.

## LLM Model Assignments

- Chat: anthropic/claude-3.5-haiku (fast, cheap)
- Extraction/segmentation: anthropic/claude-3.5-haiku (fast, cheap)
- Consolidation: anthropic/claude-opus-4.6 (deep reasoning, 1M context)

## Day 4 Pre-Implementation Discussion

### What are observations?

Observations are Layer 0 of the knowledge hierarchy from doc 10.
They are self-contained factual statements extracted from conversations. Examples:
- "User stores photos in ~/media/photos/{year}/ organized by month"
- "When looking for duplicates, content hash SHA-256 is more reliable than filename matching"
- "User prefers Python scripts over shell commands for file operations"

Each observation is a YAML file with content, confidence, tags, domain, topic, timestamps.

Quality filters from prompt 02 (predict-calibrate):
- Persistence: Will this still be true in 6 months?
- Specificity: Does it contain concrete, searchable information?
- Utility: Can this help with future similar tasks?
- Independence: Can it be understood without the conversation context?

Not observations: temporary emotions, acknowledgments, vague statements, information already known.

### What is the relationship between observations and topics?

Episodes (topics) are the intermediate step. The flow is:
Raw messages -> Episode segmentation -> Episodes -> Extraction -> Observations

Episodes = groups of messages about the same topic. A conversation where you ask about files,
then switch to a script question, then back to files produces 2 episodes: one about files
(messages 1,2,5,8) and one about scripting (messages 3,4,6,7). Messages can be non-consecutive -
the segmenter groups by topic coherence, not chronological order (Nemori pattern).

Observations = distilled knowledge extracted from each episode. One episode might produce
zero observations (nothing worth remembering) or several.

The episode is thrown away after extraction - it is just a grouping mechanism.
The observations are what persist. Think of episodes as "what happened" and observations
as "what we learned from what happened."

### What is the input to the extraction pipeline?

When the next 10 messages happen, only those 10 messages go to segmentation.
But extraction sees existing observations too.

1. Buffer fills - 10 new messages accumulate
2. Segment - only those 10 messages are grouped into episodes (maybe 2-3 topics)
3. For each episode, predict-calibrate:
   - Predict: retrieve existing observations matching this topic from the knowledge store.
     Ask LLM "given what we already know, what should this conversation contain?"
   - Calibrate: compare prediction vs actual episode.
     Extract ONLY the delta (genuinely new stuff).

So the input to extraction is: existing observations + the 10 new messages. Not the whole history.
Not the 10 messages in isolation.

The existing observations provide the "what we already know" baseline.
The new messages provide "what just happened."
The delta is "what we learned that we didn't know before."

This is why predict-calibrate prevents redundant accumulation - if the agent already has an
observation "user prefers Python over shell", and the next 10 messages confirm this again,
the prediction covers it and no duplicate is created.

After processing, the 10-message pointer advances. Those messages are never re-processed.

### Is the knowledge store organized per topic?

Per domain, not per topic. Domains are broader:
- Topic/episode = one conversation fragment: "finding duplicate photos" (temporary, thrown away)
- Domain = recurring category of work: "data-cleanup" (persists, accumulates observations)

Many topics feed into the same domain. "Finding duplicate photos," "removing empty directories,"
"cleaning temp files" - all different topics, all produce observations in the "data-cleanup" domain.

For Day 4, everything goes to "uncategorized/". Day 6 adds domain detection and starts routing
observations to the right domain folder.

### Should segmentation use known topics from existing observations?

Open question (Q1). Currently segmentation is blind - groups only by coherence within the 10
messages. It does not consult existing observations or their topics. Decision: deferred.

### What about retiring outdated observations?

If new knowledge contradicts existing knowledge (e.g., user shifted from Python to TypeScript),
we need explicit retirement. Decision: add a `retire_observation(id)` tool that sets
`retired: true` on the YAML file. Retired observations are excluded from search but stay on disk.
The LLM can clean up immediately when it notices a contradiction - looks sharper for the user.

### Is the knowledge store visible only by request, or auto-injected?

Both, by design. Two paths:

By request (Day 4): The agent calls knowledge_search("SQL patterns") and gets matching
observations back as a tool result.

Auto-injected (Day 6-7): When a domain is detected, its top patterns get loaded into
the <domain_knowledge> section of the system prompt - always visible, no search needed.

Observations (Layer 0) are raw and numerous - you search them when you need them.
Patterns (Layer 1, consolidated from observations) are distilled and few - they ride in
the system prompt for the active domain because they are high-value enough to always see.

### Is session history searchable?

The full design (doc 11) includes session history search - "hybrid text + semantic search,
role filtering, date range filtering" - like Letta's recall memory. But the MVP does NOT
include it. The MVP relies on:
- Working memory (always visible) - for things worth remembering now
- Knowledge store (searchable) - for distilled observations from past work
- Session JSONL - only used for replay within the current session, and as raw input for extraction

The idea is: useful knowledge gets extracted from sessions into observations.
The agent searches observations, not raw chat history.

### Three memory modes explained

1. Working memory (always in prompt) - the YAML blocks: persona, workspace_info, user_preferences.
   Agent edits these with memory_update. Always visible, never searched - they ARE the context.

2. Session history (the JSONL) - raw conversation log. Used to rebuild context on restart.
   Not searched by the agent.

3. Knowledge store - observations extracted from past conversations. This is what
   knowledge_search queries. Distilled from session history via predict-calibrate pipeline.

## Day 5 Discussion: Python-First Knowledge Format

### Should code knowledge be separate from text knowledge?

Original MVP plan from doc 02 (Knowledge as Executable Code) envisioned Python as the knowledge
format - inspired by Voyager (NeurIPS 2023) where skills are JS functions. The Day 4 implementation
stored observations as YAML with English text. The user pointed out this misses the core thesis:
code and text should be unified, not separated.

Decision: no kind field, no separation. An observation IS a Python file. Text knowledge goes
in comments and docstrings. Code knowledge goes in functions. Both in one file.

### What format for observations on disk?

Pure Python files (.py), not YAML. Metadata in the module docstring:

```python
"""
id: obs-g7h8i9j0
domain: data-cleanup
topic: duplicate detection strategy
"""
# Text knowledge as comments
# User prefers content-based comparison over filename matching.
# Pre-filter by size for large files to save hashing time.

def find_duplicates(directory="."):
    """Find duplicate files by SHA-256 hash."""
    import hashlib
    hashes = {}
    for line in list_dir(directory, recursive=True).splitlines():
        path = line.split("  (")[0]
        h = hashlib.sha256(get_file(path).encode()).hexdigest()[:16]
        hashes.setdefault(h, []).append(path)
    return {h: ps for h, ps in hashes.items() if len(ps) > 1}
```

Text-only observations (no function) are just comments:

```python
"""
id: obs-abc123
domain: uncategorized
topic: workspace structure
"""
# This workspace is a research repo studying 36 AI agent projects.
# Top-level dirs: research/, scripts/, snapshots/, superagent/
```

### Should observations be auto-injected into context or searched on demand?

All active observations are always in context as system messages. No knowledge_search needed.

Reasoning: with CONSOLIDATION_OBSERVATION_CAP = 20 per domain, the total active observations
at any time is bounded. Even with 5 domains thats 100 observations. At ~100-200 tokens each,
thats 2K-10K tokens - acceptable for 200K-1M context models.

The knowledge_search tool is removed - simplification, not addition. The LLM already sees
all observations and can use them directly.

### How to avoid function name collisions?

Multiple observations might define functions with the same name (e.g., find_duplicates).
On disk, keep the clean name (find_duplicates.py). When rendering to context and loading into
the sandbox, use the ID suffix: find_duplicates_obs123(). The LLM doesnt care that its ugly.
This avoids collisions without consolidation as a prerequisite.

### Should observation functions be immediately callable?

Yes - first class citizen from scratch. When an observation .py file defines functions, those
functions are:
1. Shown in the context (as system messages) so the LLM knows they exist
2. Loaded into the sandbox namespace with ID suffix so the LLM can call them directly

No need to wait for consolidation. At the scale of 20-50 observations, loading everything
is trivial. The agent can immediately reuse learned functions.

On load: parse with ast.parse(). If it has FunctionDef nodes, load into sandbox with ID suffix.
If its just comments/assignments, inject into context only. No dummy empty functions.

### Function call metrics

When the sandbox calls a function from an observation, account it in the observation's statistics.
Two counters: success and failed calls. Written immediately to the observation file on disk -
no caching, we dont care about execution speed for this MVP.

This gives profiling for free - which observations are actually used, which ones never get called.

### Atomic writes

All file writes across the system should use atomic writes - write to temp file, then rename.
Prevents corruption if the process crashes mid-write. Implement as a small atomicfile.py module
used everywhere.

### What if we eventually have hundreds of observations?

CONSOLIDATION_OBSERVATION_CAP = 20 per domain with forced consolidation means hundreds are
technically impossible. The design prevents unbounded growth. But if we ever relax the cap,
an LRU-cache approach for observations in context and bringing back knowledge_search are
fallback options. Noted as future concern.

### Extraction trigger counts USER messages, not all messages

A single user question can produce 5+ messages (assistant thinking + tool calls + tool results).
Counting all messages would trigger extraction after just 2-3 user turns. So we count user
messages to decide WHEN to trigger, but send all messages (including tool calls and results)
to the segmenter to decide HOW to segment.

## Open Questions

### Q1: Topic-aware segmentation?
Should episode segmentation receive known topics from existing observations,
so it can group new messages into existing topic categories?
Currently segmentation is blind - groups only by coherence within the 10 messages.
Decision: deferred.

### Q2: Topic-based retrieval for predict-calibrate?
Should predict-calibrate retrieve existing observations by matching topic,
in addition to semantic search on content?
Decision: deferred.

### Q3: LRU cache for observations in context?
If observation count grows beyond what fits comfortably in context, implement an LRU
eviction policy and bring back knowledge_search for evicted observations.
Not needed now due to CONSOLIDATION_OBSERVATION_CAP bound.
Decision: deferred.
