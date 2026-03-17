# Memory Architecture — Three Modes, Five Operations, One Hierarchy

## Overview

The memory architecture unifies everything from the previous documents into a concrete design.
It falls out naturally from four insights developed across docs 07 and 10:

1. Context compression and knowledge consolidation are the same pattern at different time scales
2. Domains are the horizontal dimension of a knowledge hierarchy — specialized at the bottom, converging at the top
3. Every return in a hierarchy is context folding — child compresses, parent receives summary
4. Bounded capacity at every layer forces consolidation — without pressure, there is no reason to generalize

The architecture has three operational modes (working memory, session history, knowledge store), five operations (add, consolidate, retrieve, update, retire), and one hierarchical structure that grows organically as the agent accumulates experience.

---

## Three Operational Modes

### Mode 1: Working Memory (In-Context, Per-Session)

Letta-style labeled blocks compiled into the system prompt on every turn.
The agent reads and writes them via tools.
Each block shows `chars_current/chars_limit` — the agent manages its own budget.

**Standard blocks:**
- `task_goals` — the root of the current task. NEVER compressed. Contains goals, business context, high-level requirements.
- `current_domain` — which DomainProfile is active. Loaded from the Knowledge Store when a domain is detected.
- `plan_tree` — the FocusChain. Tree-structured plan with per-node state (pending/active/complete/summary).
- `persona` — the agent's identity and behavioral guidelines.

**Domain-specific blocks** loaded from the active DomainProfile:
- `schema_knowledge` — for statistics domain, the database schema
- `query_patterns` — learned SQL patterns for this database
- `test_commands` — for coding domain, how to run tests for this project

**Shared blocks between agents** via the `inherit: blocks` mode from [doc 07](07-context-flow.md).
When a parent spawns a child, both read from the same blocks.
The child who shares the parent's `task_goals` block understands WHY the task matters.
When the parent updates `task_goals` during the ongoing conversation, the child sees the update on its next turn.

**What working memory is NOT:**
- It is not the conversation history (that is session history)
- It is not the accumulated knowledge (that is the Knowledge Store)
- It is the agent's CURRENT FOCUS — what it needs to see right now to do its job

This is Letta's Tier 1 — always visible, zero latency.

### Mode 2: Session History (Searchable, Per-User)

Every message ever exchanged, persisted to database.
Even after messages are evicted from the context window by the ContextBoundary, they remain permanently searchable.

**Search capabilities:**
- Hybrid text + semantic search (like Letta's recall memory)
- Role filtering (user/assistant/tool messages)
- Date range filtering
- Domain tagging (which domain was active when this message was exchanged)

**Dual purpose:**
1. **Recall** — the agent can search past conversations to find relevant context ("what did we discuss about the auth module last week?")
2. **Testing** — successful session traces become Tier 2 integration replay tests from [doc 06](06-testing-platform.md). When a block version changes, past recordings are replayed against the new lockfile.

Session history is the raw material from which the Learning Loop extracts knowledge.
Observations (Layer 0 of the knowledge hierarchy) come from analyzing session history during background consolidation.

This is Letta's Tier 2 — slower than working memory (requires a tool call and database query), but unlimited in size and never loses data.

### Mode 3: Knowledge Store (The Hierarchy)

The persistent, versioned, hierarchical store of everything the agent has learned.
This is where all the new ideas from [doc 10](10-continuous-learning.md) live.

**Per-domain hierarchy with arbitrary depth:**

```
knowledge/
  shared/                               ← cross-domain (Level N)
    principles/                         ← "validate assumptions before acting"
    cross_domain_patterns/              ← patterns that emerged from domain convergence
  domains/
    statistics/
      profile.yaml                      ← DomainProfile: lockfile overlay, default composition,
                                           knowledge namespace, domain-specific blocks
      observations/                     ← Layer 0: raw signals
        2026-03-sql-error-001.yaml      ← time-bounded, max 100 per domain
        2026-03-user-pref-002.yaml
      patterns/                         ← Layer 1: Strategy + Tool artifacts
        sql_date_filter/
          1.0.0/tool.py                 ← versioned, immutable
          1.1.0/tool.py
        always_check_schema/
          0.1.0/strategy.py
      concepts/                         ← Layer 2+: Composition artifacts
        temporal_query_strategy/
          1.0.0/composition.py
      meta/
        utility_scores.db               ← per-artifact utility, trust, usage, last_accessed
        consolidation_log.jsonl         ← what was consolidated when and why
        provenance.db                   ← who created each artifact, from what source
    coding/
      profile.yaml
      observations/
      patterns/
      concepts/
    research/
      profile.yaml
      observations/
      patterns/
      concepts/
  index.db                              ← unified: semantic vectors + keyword BM25 + link graph
  lockfiles/
    current.lock                        ← the active configuration
    2026-03-17T08-00.lock               ← previous (instant rollback)
    2026-03-16T22-00.lock               ← older
```

**Capacity limits at every layer:**
- Observations: time-bounded (default 30 days) + count cap (default 100 per domain)
- Patterns: per-domain cap (default 20 per domain)
- Concepts: per-domain cap (default 5 per domain)
- Cross-domain principles: implicitly small (generalizations get more abstract and fewer)

When a layer exceeds its cap, consolidation is triggered (see Operations below).

**Retrieval scoping:**
- Bottom levels (observations, patterns): DOMAIN-SCOPED search. "Find SQL patterns" searches only within `statistics/patterns/`.
- Top levels (concepts, principles): CROSS-DOMAIN search. Principles apply everywhere.
- Link graph traversal: A-MEM-style — retrieved artifacts bring their linked neighbors into the result set.

---

## How the Three Modes Interact

### Downward Flow (Delegation)

```
Knowledge Store
  → domain patterns and concepts loaded into
Working Memory (blocks in system prompt)
  → shared via inherit:blocks with
Child Agent's Working Memory
  → child has full business context without seeing parent's conversation details
```

The parent's `task_goals` and domain-specific blocks flow down to the child.
The child starts with understanding, not from scratch.
The more context flows down, the fewer questions the child asks, the more relevant its output.

### Upward Flow (Return + Consolidation)

```
Child completes subtask
  → returns compressed result (context folding)
Parent's Working Memory receives the summary as a tool result
  → session continues

After session (idle time):
Session History (full trace persisted)
  → background consolidation via Nemori Predict-Calibrate
Knowledge Store Layer 0 (observations)
  → when Layer 0 is full, GEPA consolidates into
Knowledge Store Layer 1 (patterns)
  → when Layer 1 is full, consolidate into
Knowledge Store Layer 2+ (concepts)
  → when similar patterns appear across domains, consolidate into
shared/cross_domain_patterns/ and shared/principles/
```

Every upward transition is context folding: detailed work → compressed summary.
The manager sees "auth refactored, 3 files, tests pass" — not the code diffs.
The knowledge hierarchy sees "always check date ranges" — not the 15 individual SQL errors.

---

## Five Operations

### 1. ADD — New Observation Enters Layer 0

**When:** After task completion, tool failure, user feedback, or any signal from the three learning speeds (doc 10).

**Quality gate:** Nemori Predict-Calibrate.
Before adding:
1. Retrieve relevant existing knowledge from the domain
2. Predict what the observation should contain based on existing knowledge
3. Extract only the genuinely NEW information — the delta between prediction and reality

This prevents indiscriminate memory accumulation (the primary cause of memory degradation per Xiong et al.).

**What gets stored:** A YAML file in the domain's `observations/` directory with:
- Content: the raw observation
- Source: which task, which tool, which user interaction
- Domain: auto-classified
- Provenance: who created it, from what source
- Trust score: initial score based on source trustworthiness
- Timestamp: for temporal decay

### 2. CONSOLIDATE — Upward Compression Under Pressure

**When:** A layer exceeds its capacity cap OR background idle time triggers consolidation.

**How it works at each boundary:**

**Observations → Patterns (Layer 0 → Layer 1):**
- Cluster similar observations (embedding similarity)
- For each cluster, ask the LLM: "what pattern do these observations share?"
- The generalization becomes a candidate Strategy or Tool artifact
- The candidate enters the admission pipeline (doc 03): syntax → security → tests → regression → review
- If accepted: enters shadow mode. If shadow wins: promoted via lockfile swap.
- The observations that were generalized get their utility scores reduced (they are now subsumed)

**Patterns → Concepts (Layer 1 → Layer 2+):**
- When the patterns layer is full, GEPA runs optimization over the patterns
- Related patterns are merged into fewer, more powerful compositions
- Same admission pipeline: candidate → gates → shadow → promotion

**Cross-domain consolidation:**
- During background idle time, compare patterns across domains
- When similar patterns appear in different domains (embedding similarity above threshold), ask the LLM: "are these the same insight?"
- If yes: create a shared concept in `knowledge/shared/` that both domains reference
- This is the rarest and most valuable form of learning

### 3. RETRIEVE — Find Relevant Knowledge

**What the agent needs for the current task:**
1. Domain detection: classify the current task's domain (LLM call or embedding match against DomainProfiles)
2. Load domain blocks into working memory
3. Search the domain's knowledge hierarchy:
   - Patterns and tools: semantic search within the domain namespace
   - Concepts: semantic search within the domain + shared namespaces
   - Principles: always available (cross-domain)
4. Link traversal: retrieved artifacts bring their linked neighbors (A-MEM pattern)

**Budget-aware retrieval:**
- Inject token usage counters into the system prompt (BATS pattern: 40% cost reduction)
- Limit retrieved artifacts to fit within the remaining context budget
- Prefer higher-level artifacts (concepts > patterns > observations) — they are more information-dense

### 4. UPDATE — Refine a Generalization

**When:** Attribution from doc 04 traces a task failure back to a specific artifact.

**How:**
1. The attribution model identifies: "research_context_boundary@0.2.1 encoded the generalization 'compress at 50%', but this task needed 80%"
2. A candidate new version is created: `research_context_boundary@0.3.0` with a conditional rule
3. The candidate enters the admission pipeline
4. If accepted: shadow mode tests whether the conditional version outperforms the old one
5. If shadow wins: lockfile swap promotes the new version

**The old version stays on disk** (immutable). If the new version causes regressions, instant rollback to the old one.

### 5. RETIRE — Remove or Demote an Artifact

**When:**
- Utility score below threshold (not accessed in N days, not correlated with task success)
- Attribution identifies the artifact as harmful (correlated with failures)
- Temporal decay: old observations with no consolidation

**How:**
- A candidate lockfile WITHOUT the artifact is created
- Contract tests run (if anything depends on it, the candidate is rejected immediately)
- If no dependencies: shadow mode compares agent with and without the artifact
- If equivalent or better without: promote the candidate lockfile
- The retired artifact stays on disk (for diagnosis and potential rollback) but is removed from the active index

---

## Metadata on Every Artifact

Every artifact in the Knowledge Store carries:

| Field | Purpose |
|---|---|
| `utility_score` | Continuously updated: access count, last-used, success correlation. Drives promotion/demotion. |
| `trust_score` | Based on source: high for user-accepted results, low for web scraping. Influences search ranking. |
| `provenance` | Who created it, from what source, via what process. Immutable. For security audit. |
| `domain` | Which domain this artifact belongs to. For scoped retrieval. |
| `level` | Which hierarchy level (observation/pattern/concept). For consolidation. |
| `version` | SemVer. Multiple versions coexist. Lockfile selects the active one. |
| `parent_artifacts` | What observations/patterns this was consolidated FROM. For attribution tracing. |
| `child_artifacts` | What concepts this was consolidated INTO. For upward tracking. |
| `created_at` | Timestamp. For temporal decay. |
| `last_validated` | When was this last confirmed to be useful (via task success). Refreshes decay timer. |

---

## Connection to Existing Docs

| Doc | What This Document Adds |
|---|---|
| [01 Architecture](01-architecture-draft.md) | Working memory blocks are a ContextAssembler segment. The Knowledge Store is accessed via the Store layer. |
| [02 Knowledge as Code](02-knowledge-as-code.md) | The three artifact types (Tool, Strategy, Composition) are layers 1 and 2 of the hierarchy. Observations are Layer 0. |
| [03 Evolution and Safety](03-evolution-and-safety.md) | Every consolidation and update creates versioned candidates that pass through admission gates. Memory security protections apply to all artifacts. |
| [04 Measurement](04-measurement.md) | The scorecard provides signals for ADD. Attribution provides signals for UPDATE and RETIRE. |
| [05 Parallel Evaluation](05-parallel-evaluation.md) | Shadow mode validates every consolidation, update, and retirement before it takes effect. |
| [06 Testing Platform](06-testing-platform.md) | Session history provides Tier 2 replay tests. Contract tests protect against breaking dependency chains on RETIRE. |
| [07 Context Flow](07-context-flow.md) | Working memory sharing (inherit:blocks) is the downward delegation. Context folding is the upward return. DomainProfiles scope the Knowledge Store. |
| [09 Benchmarks](09-benchmarks-and-performance.md) | The growth curve (month 1 → month 3) is measured by how the hierarchy deepens and performance improves. |
| [10 Continuous Learning](10-continuous-learning.md) | Three learning speeds drive the five operations. Hierarchical consolidation is the organizing principle. |

---

## What We Take from Existing Research

| Component | Source | What We Use |
|---|---|---|
| Working memory blocks with metadata | Letta `Memory.compile()` | XML rendering, chars_current/chars_limit, three rendering modes |
| Block sharing between agents | Letta `AgentBlockRelationship` | The `inherit: blocks` mode for context inheritance |
| Quality gate for observations | Nemori Predict-Calibrate | Extract only the delta between prediction and reality |
| Link graph in retrieval | A-MEM `search_agentic` | Embedding similarity + one-hop link traversal |
| Episode boundary detection | Nemori `BatchSegmenter` | Non-consecutive topic grouping for conversation segmentation |
| Pattern optimization | GEPA reflective mutation | Pareto selection over Strategy artifacts |
| Context folding | FoldAgent `branch`/`return` | Learned compression at subtask boundaries |
| Versioned artifacts | npm/cargo lockfile model | Immutable versions with SemVer and dependency resolution |
| Utility scoring | AMV-L (arXiv:2603.04443) | Value-driven promotion/demotion/eviction |
| Background consolidation | Letta sleep-time compute | Idle-time processing with 5x compute reduction |
| Capacity limits per layer | H-MEM four-layer hierarchy | Configurable caps with forced consolidation |
| Trust and provenance | GitHub Copilot citation-validated memory | 28-day expiry, source tracking |
| Temporal decay | AMV-L + Copilot model | Utility decays without validation; refreshed on access |

## What Is New

No existing system combines:
1. Bounded capacity at every layer (forces consolidation — nobody does this)
2. Arbitrary-depth hierarchy (not fixed at 2-4 levels)
3. Domain convergence at top levels (cross-domain principle formation)
4. Every mutation as a versioned candidate tested via shadow mode
5. Provenance + trust + utility as first-class metadata
6. Continuous learning at three speeds (instant/fast/background) feeding five operations
7. Context inheritance (downward delegation) and context folding (upward return) as two halves of one pattern
