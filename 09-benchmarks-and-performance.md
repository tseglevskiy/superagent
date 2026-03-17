# Benchmarks and Performance — What Growth Looks Like

## The Right Definition of Performance

Absolute performance on a benchmark is not our metric.

Our metric is **delta** — how much better the agent becomes over time on the same types of tasks.
A system that starts at 60% and reaches 85% after three months of operation is more valuable than a system that starts at 80% and stays at 80%.

The first demonstrates learning.
The second demonstrates capability.
We want both, but we MEASURE the first.

### Why Delta Matters More Than Absolute Score

In a traditional coding benchmark (SWE-bench, HumanEval), the agent starts fresh for every task.
No history, no learning, no accumulated knowledge.
The score reflects what the model can do out of the box.

Our agent operates differently.
The same human works with the same agent on the same project for months.
The context is super-long — not a single question, but an ongoing collaboration.
The agent accumulates knowledge: how this specific codebase works, what SQL schemas look like, which marketing tone the user prefers, what testing patterns succeed.

The right comparison is not "our agent vs Claude Code on SWE-bench today."
The right comparison is "our agent in month 1 vs our agent in month 3 on the same task types."

### Two Performance Requirements

1. **Baseline competence** — on day one, the agent must not be embarrassingly worse than existing systems.
   "Not complete garbage" is the bar.
   The user should not feel that we broke everything to enable self-improvement.

2. **Measurable growth** — over weeks and months, the scorecard metrics (from [doc 04](04-measurement.md)) should trend in the right direction.
   Fewer steps per task.
   Lower cost per task.
   Fewer errors and retries.
   Higher user acceptance rate.
   Faster wall time.

The growth curve is the product.

### What "Growth" Means Concretely

Growth manifests differently per artifact type:

**Strategy growth** — the agent's system prompts become more effective over time.
GEPA optimizes them.
Fewer instructions that are ignored (AGENTIF: <30% compliance → higher density → better compliance).
Shorter prompts that produce better results (GEPA produces 33% shorter prompts).

**Tool growth** — the agent accumulates domain-specific tools.
A web scraper fine-tuned for THIS project's API.
SQL patterns for THIS database schema.
Test scripts for THIS build system.
Voyager showed 3.3x more capabilities over time; we should show something analogous for coding/research.

**Composition growth** — the agent discovers better architectures for recurring task types.
First time researching: flat ReAct loop.
Fifth time: supervisor with parallel researchers.
Tenth time: the same, but with domain-specific query patterns.

**Domain growth** — the agent becomes specialized.
Month 1: generic responses.
Month 3: "when you ask about statistics, I use the SQL patterns that worked last 20 times."

---

## Using Human Feedback

### Two Feedback Channels

**Implicit feedback** — the 8-metric scorecard from [doc 04](04-measurement.md).
Did the user accept the result? How many retries were needed?
Available on every task, no user effort required.

**Explicit feedback** — presenting two options and asking which is better.
This is what ChatGPT does (left or right answer preference).
This is what our shadow/race modes from [doc 05](05-parallel-evaluation.md) enable.

When two lockfile configurations produce different results, the user can be shown both:
"Here are two approaches to this task. Which do you prefer?"
The preference directly calibrates the LLM-as-judge and the promotion pipeline.

### When Explicit Feedback Is Possible

Not always.
For coding tasks where the agent writes code in the background, there is no natural point to show two options — the code either works or it does not.
For research tasks, writing tasks, and analysis tasks, presenting two summaries or two approaches is natural.

The system should detect when A/B comparison is feasible and offer it opportunistically, not force it.
The promotion pipeline from doc 05 already supports this: shadow mode (automatic, no user involvement) when comparison is not feasible, race mode (user picks the better result) when it is.

---

## Temporal Decay and Profiling

### The Profiling Idea

Since our Knowledge Store artifacts are Python modules, we can profile them.
Every time a Tool artifact is invoked, the ToolRegistry records the call.
Over time, we build a usage profile per artifact:
- Last used: 3 months ago
- Usage count in last 30 days: 0
- Usage trend: declining

Artifacts that have not been used in N days are candidates for:
1. **Deprioritization** — lower ranking in semantic search results
2. **Review** — the agent asks itself "is this still relevant?"
3. **Retirement** — removed from the active lockfile (still on disk for rollback)
4. **Evolution** — maybe the artifact is unused because it is bad. The evolution pipeline diagnoses and improves it.

This is analogous to GitHub Copilot's 28-day auto-expiry, but richer — we do not just expire, we diagnose WHY an artifact stopped being useful.

### AMV-L Utility Scores (arXiv:2603.04443)

The most rigorous approach: continuously updated utility scores based on access patterns, task success correlation, and freshness.
Value-driven promotion/demotion/eviction achieves 3.1x throughput improvement and 4.2x latency reduction.
TTL alone causes retrieval latency to grow unboundedly as the store gets larger.

Our Knowledge Store should use utility-based lifecycle:
- Every artifact gets a utility score updated on every access
- High-utility artifacts: promoted to frequently-searched tier
- Declining-utility artifacts: flagged for review
- Zero-utility artifacts: candidates for retirement
- Negative-utility artifacts (caused errors): flagged for fix or removal

---

## Consolidation During Idle

This is Letta's sleep-time compute pattern applied to our architecture.
Between user interactions, the agent runs background work:

1. **Knowledge extraction** — process recent task recordings, extract new Tool/Strategy/Composition artifacts via the Learning Loop (doc 02)
2. **GEPA optimization** — run reflective prompt evolution on Strategy artifacts using accumulated scorecard data
3. **Domain discovery** — cluster recent tasks to update DomainProfiles (doc 07)
4. **Integration replay** — run Tier 2 tests from doc 06 against any new artifacts
5. **Consolidation** — apply Nemori's Predict-Calibrate: retrieve existing knowledge, predict what new sessions add, extract only the delta

Letta's Sleep-Time Compute achieves 5x test-time compute reduction.
LightMem achieves 117x token reduction and 159x fewer API calls.
Our consolidation mode should target similar efficiencies.

The user interacts → the agent responds → idle time → background consolidation fires → next interaction benefits from consolidated knowledge.

---

## The Six Memory Patterns in Detail

These six patterns from the reworked [persistent-memory concept](../research/concepts/persistent-memory/_index.md) map to specific components of our architecture.
Each pattern addresses a different operating context, and our Knowledge Store must support all six.

### Pattern 1: Memory-First (Letta)

**What it is**: Memory management is the defining design principle.
The agent's system prompt changes every turn as it edits its own memory blocks.
Core memory blocks are always in context.
The agent has tools to read, write, and search its own memory.

**Letta specifics**: Three-tier hierarchy (core blocks always visible, recall memory as searchable history, archival memory as unlimited vector store).
Shared blocks between agents.
Sleep-time consolidation.
All state in PostgreSQL.

**How it maps to our architecture**: This is our `inherit: blocks` mode from [doc 07](07-context-flow.md).
When a parent agent spawns a child, they share memory blocks — the child sees the parent's business context because they read from the same labeled blocks.
Our ContextAssembler (doc 01) renders these blocks into the system prompt with metadata (chars_current/chars_limit) so the agent manages its own memory budget.

**When to use**: Long-running stateful agents that accumulate knowledge over months of interaction.
This is our primary operating mode.

### Pattern 2: Consolidation Pipeline (Codex CLI, Claude Code)

**What it is**: A background process extracts knowledge from completed sessions, consolidates it into structured files, and injects those files at the start of future sessions.
The agent never explicitly "remembers" during a session.

**Codex CLI specifics**: Two-phase pipeline.
Phase 1: extraction from past rollouts via a fast model.
Phase 2: a full consolidation agent rewrites structured memory files (MEMORY.md, memory_summary.md, skills/).
Up to 16 rollouts processed per startup, 8 in parallel.

**How it maps**: This is our consolidation-during-idle mode.
Between interactions, a background process runs the Learning Loop to extract knowledge from recent sessions and consolidate it into the Knowledge Store.
Our lockfile resolution ensures the consolidated artifacts are versioned and testable before activation.

**When to use**: Session-based tools where background processing is acceptable.
Good for overnight operation.

### Pattern 3: File-Based Memory with Search (OpenClaw, Goose, Ouroboros, EloPhanto)

**What it is**: The agent writes markdown files and retrieves them via various search mechanisms.
Ranges from no search (Goose — plain file reading) to sophisticated hybrid search (OpenClaw — vector + FTS5 + MMR + temporal decay).

**OpenClaw specifics**: Two competing backends.
memory-core: SQLite with vector embeddings and FTS5 hybrid search, MMR diversity, temporal decay.
memory-lancedb: auto-capture via pattern matching, auto-recall via context injection.

**How it maps**: This is our Knowledge Store's persistence layer.
Artifacts are Python files on disk (human-readable, git-trackable).
The index uses hybrid semantic + keyword search.
DomainProfiles scope search to the relevant domain namespace.

**When to use**: Any deployment where inspection and version control of knowledge matters.

### Pattern 4: Conversation Replay (n8n, CrewAI)

**What it is**: Past messages or task outputs are stored in a database and replayed into context.
No knowledge extraction — just raw replay.

**n8n specifics**: Seven backend options (Postgres, Redis, MongoDB, Zep, Xata, Motorhead, in-memory).
Session-ID-keyed.
Windowed replay of last k pairs.

**How it maps**: This is our recorded session traces from [doc 06](06-testing-platform.md) Tier 2.
Successful task recordings serve as both regression tests AND retrievable examples.
When the agent encounters a similar task, a past recording can be retrieved and its approach replayed or adapted.

**When to use**: Short-lived agent interactions where knowledge extraction is overkill.

### Pattern 5: Code as Memory (Voyager, BabyAGI)

**What it is**: The agent's persistent knowledge is executable code, not text.
Functions are described, embedded, and retrieved by semantic similarity.

**Voyager specifics**: Every successful Minecraft task produces a JavaScript function.
Descriptions embedded in ChromaDB.
New skills compose on previously learned ones.
3.3x more capabilities over time.

**How it maps**: This is our Tool artifacts from [doc 02](02-knowledge-as-code.md).
The core thesis: knowledge as executable code scales differently from knowledge as prompts.
10,000 functions on disk, but only the 5 most relevant enter the prompt via search.
Compositions compose tools just as Voyager's skills compose earlier skills.

**When to use**: Whenever the agent discovers reusable procedures.
The Learning Loop should prefer extracting executable functions over storing prose descriptions.

### Pattern 6: Memory Libraries (A-MEM, Nemori)

**What it is**: Standalone Python libraries that give any LLM agent self-organizing persistent memory.
Not agents themselves — infrastructure components.

**A-MEM specifics**: Zettelkasten-inspired.
Two LLM calls per memory (metadata extraction + linking/evolution).
Explicit link graph alongside embedding similarity.
Neighbor memories evolve when new memories arrive.

**Nemori specifics**: Cognitive pipeline.
Episode segmentation → narrative generation → Predict-Calibrate semantic extraction.
Dual episodic + semantic store.
Hybrid ChromaDB + BM25 search.

**How it maps**: These are candidate implementations for our Knowledge Store index.
A-MEM's link graph enriches our artifact retrieval (follow links, not just similarity).
Nemori's Predict-Calibrate is the quality gate for our Learning Loop (extract only genuinely new knowledge).

**When to use**: As building blocks integrated into our Knowledge Store layer.

---

## Benchmarks: What to Measure Against

### The Problem with Existing Benchmarks

Eight new benchmarks from 2024-2026 expose fundamental gaps:
- **MemoryAgentBench** (ICLR 2026) — no system masters conflict resolution (overwriting outdated facts)
- **BEAM** (ICLR 2026) — scales to 10M tokens, even 1M-context models degrade substantially
- **AMA-Bench** (2026) — first benchmark for agentic task execution, not just dialogue
- **Mem2ActBench** (2026) — tests proactive application of memory, not passive recall
- **MemBench** (ACL 2025) — reflective memory (implicit preferences) much harder than factual
- **MemoryBench** (2025) — agents fail to utilize user feedback for continual improvement
- **MemGUI-Bench** (2026) — agents without memory show near-zero failure recovery
- **Evo-Memory** (2025) — streaming task streams testing self-evolving memory

Key finding: **strong performance on long-context benchmarks does NOT predict strong performance in agentic interactive settings** (MemoryArena, arXiv:2602.16313).

### What We Should Measure

Two benchmark categories:

**Category 1: Baseline Competence (Day 1)**
- SWE-bench Verified — coding tasks, establishes we are not terrible
- HotpotQA / LoCoMo — retrieval and reasoning, establishes memory works
- The score itself matters less than being "in the same ballpark" as existing agents

**Category 2: Growth Over Time (Month 1 vs Month 3)**
This is our unique contribution.
No existing benchmark measures this.
We need to design our own evaluation:

- **Task efficiency delta** — same task category, fewer steps over time
- **Cost delta** — same task quality, lower token cost over time
- **Error rate delta** — same task complexity, fewer failures over time
- **Domain expertise delta** — tasks in established domains succeed at higher rates than novel domains
- **Knowledge reuse rate** — what percentage of tasks use previously learned artifacts
- **Artifact quality delta** — newer artifact versions score better on the scorecard than older ones

**Category 3: Long-Horizon Interaction (Months)**
- Evo-Memory — streaming task sequences testing evolving memory
- MemoryArena — interdependent multi-session tasks
- Custom: same-project task sequences over simulated weeks of interaction

### Publications to Compare Against

For baseline competence:
- FoldAgent (58% SWE-Bench Verified) — comparable agent with RL-trained context management
- HiAgent (2x success rate on long-horizon tasks) — comparable plan-driven compression
- Agent S S3 (72.6% OSWorld) — state-of-the-art GUI automation

For memory quality:
- Nemori (0.744 LoCoMo, 88% token reduction) — our memory library baseline
- A-MEM (2x multi-hop reasoning, 85-93% fewer tokens) — our link-graph baseline
- Memory-R1 (outperforms with 152 training examples) — our RL-trained management baseline

For growth measurement:
- No direct comparison exists.
  This is our unique contribution.
  We define the evaluation protocol.

---

## What to Do Next

1. Define the growth evaluation protocol — what tasks, what cadence, what metrics
2. Establish baseline competence scores on SWE-bench and LoCoMo before any evolution
3. Run the agent for simulated weeks, recording all scorecards
4. Plot the delta curves — this IS the result
5. Publish the evaluation protocol so others can measure growth, not just performance
