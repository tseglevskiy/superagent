# Context Flow — How Knowledge Moves When Attention Splits

## The Problem

Every interesting agent interaction eventually needs to split.
You discuss a business problem, then want the agent to code while you keep talking.
You build up a rich understanding, then want a deep research dive that uses all of it.
You work through a multi-step plan, and older subtask details crowd out current thinking.

The universal failure mode across all studied projects: **when the agent splits, the child starts with empty or impoverished context**.
Claude Code's Task tool gives the subagent only the Task input — no parent conversation.
OpenHands' AgentDelegateAction scopes the EventStream by position, not by relevance.
Open Deep Research gives each researcher only its specific `ResearchQuestion`, deliberately discarding the supervisor's full picture.

This is acceptable for some tasks (a researcher does not need to know about other researchers' findings until the merge step).
It is catastrophic for others (a coding agent that does not know the business context produces technically correct but strategically wrong code).

The five scenarios below describe different modes of context flow that an agent must be able to choose between.
The agent — not the human, not the framework — decides which mode to use based on the situation.

### How This Connects to the Other Docs

- [Doc 01](01-architecture-draft.md) — SubAgentSpawner and ContextBoundary are the blocks that implement these strategies
- [Doc 02](02-knowledge-as-code.md) — Knowledge Store artifacts are domain-scoped and namespaced
- [Doc 03](03-evolution-and-safety.md) — lockfile overlays enable per-domain block configurations
- [Doc 04](04-measurement.md) — task categorization and per-block x task-category metrics feed domain discovery
- [Doc 05](05-parallel-evaluation.md) — shadow/race modes are a special case of agent cloning with shared context
- [Doc 06](06-testing-platform.md) — integration replay tests capture traces per domain for regression testing

---

## Scenario 1: Context-Rich Subagent Spawning

You discuss a business problem with the agent.
You agree on what needs to be coded.
The agent forks: one branch starts coding, you continue the conversation about business.
The coding branch MUST know the business context — otherwise it writes technically correct but strategically wrong code.

### What Exists Today

**Claude Code Task tool** — spawns subagents with only the Task input text.
The parent's conversation is NOT passed.
The child has zero awareness of WHY the code is being written, what the user cares about, or what was already discussed.
This is the empty context catastrophe.
See [Claude Code subagent spawning](../research/concepts/agentic-loop/02-direct-loops.md).

**OpenHands AgentDelegateAction** — better.
The delegate gets a scoped view of the EventStream starting from its `start_id`.
But scoping is by event position, not semantic relevance.
If the business context was discussed 50 events ago and the delegation starts at event 100, the child misses it.
See [OpenHands delegation](../research/concepts/agentic-loop/04-event-driven-loops.md).

**Letta shared memory blocks** — the closest to what we need.
When a sleeptime group is created, all agents share the same memory blocks.
The child agent sees the parent's core memory (persona, business context, project knowledge) because they read from the same blocks.
But this is shared WORKING memory, not shared conversation history — the child sees the distilled knowledge but not the reasoning that produced it.
See [Letta shared blocks](../research/products/letta/02-memory-architecture.md).

**Open Deep Research** — each researcher gets only its specific `ResearchQuestion`, not the supervisor's full context.
Architectural isolation is deliberate — the researcher does not need the full picture.
The supervisor handles the big picture.
See [Open Deep Research context isolation](../research/concepts/deep-research/03-open-deep-research.md).

### What We Need

A **context inheritance mode** on SubAgentSpawner.
When spawning, the parent chooses:

| Mode | What the child sees | Cost | Use case |
|---|---|---|---|
| `inherit: none` | Only the task prompt | Zero | Stateless tasks: run 10 commands, check results |
| `inherit: summary` | LLM-compressed summary of parent's conversation | 1 LLM call | Background coding: needs context but not every detail |
| `inherit: full` | Full conversation history copied | Token cost of full context | Deep research clone: precision requires full trajectory |
| `inherit: blocks` | Shared memory blocks (Letta pattern) | Near-zero | Long-running collaboration: structured knowledge shared, conversations separate |
| `inherit: selective` | LLM selects which parts to pass | 1 LLM call | Mixed: the LLM decides what the child needs |

The Letta `inherit: blocks` mode is particularly elegant for the business context problem.
The business context lives in a labeled memory block (e.g., `"project_goals"`, `"business_requirements"`).
The coding subagent shares those blocks.
When the parent updates the business context during the ongoing conversation, the coding subagent sees the update on its next turn — live synchronization through shared mutable state.
See [Letta Memory.compile()](../research/products/letta/02-memory-architecture.md) — blocks are rendered into the system prompt with XML tags, metadata, and character limits visible to the agent.

The implementation in our Lego: SubAgentSpawner receives an `inherit` parameter.
ContextBoundary is invoked not just for compression, but for PREPARING context for a new scope.
This is a new role for ContextBoundary — it becomes a bidirectional component: compress for staying within the current scope, AND prepare for entering a new scope.

---

## Scenario 2: Agent Cloning for Deep Research

You have been building a rich, nuanced understanding through a long conversation.
Now you need a deep research dive on a specific aspect.
A fresh subagent with an empty context would research too superficially — it does not know what you already know, what angle matters, or what depth you need.

You want a **clone**: a copy of the current agent with full context, sent off to research, that returns a precisely targeted report.

### What Exists Today

**No studied project does this well.**

The closest precedents:

**GCC — Git-Context-Controller** (arXiv:2508.00031) — the strongest research precedent.
Structures agent context as a version-controlled system with BRANCH, MERGE, and CONTEXT commands.
BRANCH creates an isolated copy of the agent's context for exploration.
MERGE brings results back.
Starting from raw Claude-4-Sonnet at 67.2%, the full system achieves 80.2% on SWE benchmarks.
BRANCH and MERGE operations provide the biggest gains by enabling isolated exploration of alternative reasoning paths.
See [prompt research 1.13](../research/external/2026-03-15-prompt-research.md).

**Moatless MCTS per-node FileContext** — each child node inherits a deep copy of the parent's FileContext.
This IS cloning — but for code state, not conversation state.
Modifications in one branch do not affect siblings.
See [Moatless tree search](../research/concepts/agentic-loop/07-tree-search-loops.md).

**Letta Conversations API** — concurrent sessions against a single agent, sharing memory blocks but isolated conversation contexts.
The inverse of what we want: Letta shares state but isolates conversations.
We want to share the conversation but isolate the execution.
See [Letta persistence](../research/products/letta/08-persistence.md).

### What We Need

An **agent clone operation**: fork the current state (system prompt + conversation history + memory blocks) into a new agent instance.
The clone executes independently, produces a result (the report), and returns it to the parent as a tool response.

The architecture: `SubAgentSpawner(inherit: full)` + the clone runs a DirectLoop (or SupervisorPattern for deep research) + the clone's final output is compressed into a structured report + the report enters the parent's context as a tool result.

Why this is different from Scenario 1: in context-rich spawning, the child needs BACKGROUND context (the business picture).
In cloning, the child needs EVERYTHING — the full conversational trajectory, because the precision of the research depends on understanding the chain of reasoning that led to the question.
The report produced by the clone is precisely targeted because the clone understands not just WHAT to research, but WHY and at what depth.

The GCC paper proves the BRANCH/MERGE pattern works.
Our implementation: BRANCH = `SubAgentSpawner(inherit: full)`.
MERGE = the clone's report becomes a tool result in the parent's context.

### Connection to A/B Testing (Doc 05)

Shadow mode and race mode from [doc 05](05-parallel-evaluation.md) ARE agent cloning applied to evaluation.
When you fork the conversation to test two lockfile configurations in parallel, both branches must have the same context for the comparison to be valid.
This is `SubAgentSpawner(inherit: full)` with two children — identical context, different configurations — and a judge that compares the outputs.

The promotion pipeline from doc 05 needs cloning because A/B tests typically start mid-conversation, not at the beginning.
Both branches see the same history up to the fork point, then diverge based on their lockfile configurations.

---

## Scenario 3: Tree-Structured Context Compression

The standard approach to context overflow: kill the oldest messages.
The problem: the oldest messages are often the MOST important — they contain the goal, the business task, the high-level requirements.
Everything that matters is at the beginning.
By killing old messages first, the agent forgets WHY it is working while remembering the details of WHAT it last did.

The alternative: compress from the leaves, not from the root.

### The Idea

The agent maintains a hierarchical plan:
```
1. Business analysis
   1.1. Gather requirements
   1.2. Implement changes
      1.2.1. Refactor authentication module
      1.2.2. Add new API endpoints
      1.2.3. Update database schema
   1.3. Test and deploy
```

Context compression follows the plan tree:
1. Execute 1.2.1 — detailed working context (file edits, test runs, debugging) accumulates
2. Complete 1.2.1 — compress all working context for 1.2.1 into a structured summary: "Refactored auth module: replaced JWT validation, updated 3 files, all tests pass"
3. Execute 1.2.2 — the summary of 1.2.1 stays, new detailed context for 1.2.2 accumulates
4. Complete 1.2.2 — compress working context for 1.2.2 into its summary
5. All children of 1.2 complete — compress all child summaries into a parent summary: "Implementation complete: auth refactored, 5 new endpoints, schema updated"
6. The ROOT (goals, business context, high-level requirements) is NEVER compressed

The context does not just shrink — it becomes **richer at higher levels** while staying bounded in total size.
At any point, the agent sees: full root context + parent-level summaries + current subtask details.

### What Exists Today

**IterResearch** (arXiv:2511.07327, Alibaba Group) — the closest research precedent.
Their "cognitive workspace suffocation" concept: accumulated data progressively dominates the context window, squeezing out the agent's "thinking space."
Their solution: reformulate long-horizon work as a Markov Decision Process with workspace reconstruction.
At each cycle, the workspace is rebuilt with only the updated report and new task context.
+14.5 percentage points improvement across six benchmarks.
See [prompt research 1.14](../research/external/2026-03-15-prompt-research.md).
IterResearch is flat (reconstruct workspace each cycle), not tree-structured, but the core insight is the same: old working details should be compressed, not the goal.

**Moatless per-node FileContext** — each tree node carries its own code visibility state.
The LLM sees the trajectory from root to current node: root context + ancestor summaries + current node's working state.
This IS tree-structured context, applied to code states rather than conversation.
See [Moatless tree search](../research/concepts/agentic-loop/07-tree-search-loops.md).

**Open Deep Research compress_research** — after each researcher completes, its full message history passes through a compression node.
Only the compressed summary crosses the tier boundary.
This is one-level tree compression: researcher work → summary → supervisor.
See [Open Deep Research compression](../research/concepts/deep-research/03-open-deep-research.md).

**Anthropic's multi-context-window harness** — the Initializer Agent creates a JSON feature list, then each subsequent Coding Agent reads it on a fresh context window.
The feature list IS the persistent root, surviving across context resets.
See [prompt research 1.13](../research/external/2026-03-15-prompt-research.md).

**No studied project does recursive tree-structured compression.**

### Why Tree Compression Requires a Plan

Standard agents operate in flat ReAct loops — there is no tree structure to compress along.
Tree compression REQUIRES:
1. A hierarchical plan that the agent maintains and updates (the FocusChain)
2. Clear boundaries between subtasks (start/complete signals)
3. A compression strategy tied to plan structure, not to message age

This means **FocusChain must become a first-class Layer 1 block** in [doc 01](01-architecture-draft.md).
Currently, plan tracking is mentioned in passing (Cline's FocusChainManager, Goose's MOIM, Codex CLI's `update_plan`).
For tree compression, it must be a block with:
- A tree-structured plan with per-node state
- Start/complete signals for subtasks
- Compression hooks that fire on subtask completion
- The root node is protected — never compressed

### The Potential Side-Effect

**Inter-branch references**: if subtask 1.2.2 needs a specific detail from 1.2.1, and 1.2.1 has already been compressed, the detail might be lost.

Mitigation: the compression prompt for each subtask explicitly asks: "what from this subtask might be needed by sibling subtasks that have not yet executed?"
Cross-references are preserved in the summary.
This is the same principle as [Moatless FeedbackGenerator](../research/concepts/agentic-loop/07-tree-search-loops.md) — analyzing sibling nodes to preserve information that future branches might need.

### Connection to Moatless MCTS

Moatless is tree-structured EXPLORATION — branching to try different solution approaches, with backtracking on failure.
Tree compression is tree-structured EXECUTION — branching to work through different plan steps, with summarization on completion.

| Dimension | Moatless MCTS | Tree Compression |
|---|---|---|
| Purpose | Explore alternative approaches | Execute a hierarchical plan |
| Branching | Multiple children try different solutions | Children are sequential subtasks |
| Per-node state | Deep-copied FileContext | Working context for that subtask |
| What the LLM sees | Root → ancestors → current node | Root → ancestor summaries → current subtask |
| On completion | Score propagates up (backpropagation) | Summary propagates up (compression) |
| On failure | Try sibling branch | The summary captures the failure for the parent to handle |

The per-node isolated state property is identical.
The data structure (tree with per-node context) is identical.
The difference is the tree's semantics: exploration vs execution.

---

## Scenario 4: LLM-Driven Context Strategy Selection

The agent itself decides which context strategy to use.
Sometimes it clones itself.
Sometimes it spawns a blank subagent.
Sometimes it compresses from the leaves.
Sometimes it does flat compression.
The human does not tell the agent which mode to use — the agent picks the right mode based on the situation.

### What Exists Today

Only 2 of 36 projects give the agent any control over its own context:

**OpenHands** — `condensation_request` tool.
The agent asks for compression but does not control HOW it happens.
The configured condenser pipeline runs.
See [OpenHands condensation](../research/concepts/context-management/02-bounding-strategies.md).

**Ouroboros** — `compact_context(keep_last_n)` tool.
The agent controls one parameter (how many recent rounds to keep) but not the strategy.
See [Ouroboros agent-initiated compression](../research/concepts/context-management/02-bounding-strategies.md).

**Letta** — the agent manages its own core memory via `core_memory_append`/`core_memory_replace` tools, actively deciding what to remember.
But it does not control compaction strategy — that is configured server-side.
See [Letta memory tools](../research/products/letta/03-memory-tools.md).

No studied project gives the agent a choice BETWEEN context strategies.

### What We Need

Context management tools in the ToolRegistry, available alongside other tools:

- **`spawn_subagent(task, inherit)`** — fork with configurable context inheritance (none/summary/full/blocks/selective)
- **`clone_self(task)`** — full context copy, the GCC BRANCH operation
- **`compress_completed_subtask(subtask_id)`** — tree compression, fires on FocusChain node completion
- **`compact_context(strategy, keep_last_n)`** — flat compression (existing OpenHands/Ouroboros pattern)
- **`save_to_domain(content, domain)`** — write knowledge to a specific domain namespace

The agent picks the right tool based on reasoning:
- "The user wants me to code this while we keep talking" → `spawn_subagent(task, inherit: blocks)` — shared memory blocks, separate conversation
- "I need precise research on this topic we've been discussing for 20 minutes" → `clone_self(research_task)` — full context copy
- "Subtask 1.2.1 is done, I should compress before starting 1.2.2" → `compress_completed_subtask("1.2.1")`
- "I'm running 10 build commands, no context needed" → `spawn_subagent(task, inherit: none)`
- "Context is getting long and I don't have a plan tree" → `compact_context(strategy: sliding_window, keep_last_n: 10)`

This is just... more tools.
The agent already decides which tools to call based on reasoning.
Adding context management tools is the same pattern.
Letta already proved this: giving the agent memory management tools is the defining feature that makes MemGPT work.
We are extending the same principle from memory management to context management.

---

## Scenario 5: Domain-Aware Knowledge Partitioning

An agent that runs for months accumulates knowledge across many different domains: product coding, statistics, marketing materials, research papers, infrastructure operations.
All of this knowledge should not live in one flat pile.

### The Problem

The Knowledge Store from [doc 02](02-knowledge-as-code.md) indexes artifacts by semantic description.
If a marketing tool and a coding tool have similar descriptions ("generate content from a template"), the semantic index might retrieve the wrong one.
More importantly, each domain develops its own expertise over time:
- The coding domain learns how to test and deploy THIS specific product
- The statistics domain learns the SQL schema and common query patterns
- The research domain discovers that deep research with parallel sub-agents works best

These domain-specific learnings should not interfere with each other.
A better SQL query tool for the statistics domain should not replace the SQL tool used in product coding (where the queries are different).
When evolution (doc 03) improves a block, it should improve it for the domain where it was measured, not globally.

### What Exists Today

**Letta labeled memory blocks** — the closest mechanism.
Blocks have labels (`"persona"`, `"human"`, `"project"`) and can be shared across agents.
You could have blocks labeled `"domain:statistics"`, `"domain:marketing"`, each accumulating domain-specific knowledge.
The agent sees all of them and knows which domain it is currently working in.
See [Letta block rendering](../research/products/letta/02-memory-architecture.md) — blocks rendered with metadata including `chars_current`/`chars_limit`, so the agent manages its knowledge budget per domain.

**Letta archival memory tags** — archival entries can have tags, and searches can filter by tag.
Domain namespacing IS tags: `archival_memory_search(query, tags=["statistics"])`.
The agent's `<memory_metadata>` shows available tags, so it knows which domains exist.
See [Letta archival memory](../research/products/letta/02-memory-architecture.md).

**Factory Signals autonomous category discovery** — generates embeddings for session summaries, clusters similar sessions, and proposes new categories when clusters do not fit existing dimensions.
Applied to knowledge items rather than sessions, this discovers domain boundaries automatically.
See [doc 04 task categorization](04-measurement.md).

**Voicetree graph nodes** — knowledge organized spatially in a graph, with hybrid semantic search (BM25 + ChromaDB + RRF) pulling in nearby nodes.
Domains would be clusters in the graph — naturally forming neighborhoods of related knowledge.
See [Voicetree context assembly](../research/concepts/multi-agent/06-shared-state-coordination.md).

**ChatGPT Projects** — user-created project containers with separate conversations.
The user manually organizes domains.
We want the agent to discover and organize them autonomously.

### What We Need: Domain Profiles

A **DomainProfile** is a configuration bundle stored in the Knowledge Store:

```yaml
name: "statistics"
discovered: 2026-03-15           # auto-discovered via clustering or manually created
lockfile_overlay:                  # overrides on top of the base lockfile
  sql_query_tool: 3.2.0           # domain-specific tool version
  data_context_boundary: 1.0.0    # domain-specific strategy
default_composition: direct_loop_with_sql_tools  # what kind of agent to spawn
knowledge_namespace: "statistics"  # scope for Knowledge Store queries
memory_blocks:                     # Letta-style blocks for this domain
  - label: "schema_knowledge"
    value: "Table users has columns id, email, created_at..."
  - label: "query_patterns"
    value: "For daily stats, always GROUP BY date..."
```

When spawning a subagent for a domain task, the SubAgentSpawner:
1. Resolves the DomainProfile for the identified domain
2. Applies the lockfile overlay (domain-specific block versions)
3. Loads domain-specific memory blocks
4. Retrieves from the domain's knowledge namespace
5. Uses the domain's default composition

When results return:
1. The scorecard is tagged with the domain
2. Block evolution happens within the domain's namespace
3. New knowledge is stored with the domain's namespace tag

### Is This a New Lego Entity?

The DomainProfile is NOT a runtime block — it does not execute inside the loop.
It is a **configuration artifact** in the Knowledge Store, similar to a Composition artifact from [doc 02](02-knowledge-as-code.md) but enriched with:
- A `lockfile_overlay` (doc 03 concept)
- A `knowledge_namespace` (doc 02 concept)
- Domain-specific `memory_blocks` (Letta concept)

It might just be an extension of the Composition artifact: a composition already declares which blocks to use (lockfile subset) and how to wire them (the loop controller).
Adding `knowledge_namespace` and `memory_blocks` to the composition manifest makes a DomainProfile a Composition artifact with domain context.

Alternatively, it is a separate artifact type — Type 4 alongside Tools, Strategies, and Compositions from doc 02.
The argument for separation: a DomainProfile does not define WIRING (that is what compositions do).
It defines CONTEXT — which knowledge, which block versions, which accumulated expertise.
A single Domain can use different Compositions for different tasks (DirectLoop for simple queries, SupervisorPattern for complex analysis).

I lean toward making it a separate concept because it serves a different purpose: Compositions define HOW blocks connect.
DomainProfiles define WHAT THE AGENT KNOWS in a particular area.

### Domain Discovery

The agent discovers domains through the same clustering mechanism described in [doc 04](04-measurement.md):

1. Every task is categorized (type, domain, complexity) by a lightweight LLM call
2. Over time, tasks cluster into natural domains
3. When a cluster becomes stable (N+ tasks with similar categorization), a DomainProfile is auto-created
4. The agent can also create domains explicitly: "I notice we keep discussing marketing — let me create a marketing domain to organize this knowledge"

This is [Factory Signals autonomous facet discovery](../research/concepts/self-improving/03-self-evaluation.md) applied to knowledge organization instead of friction categorization.

### Per-Domain Evolution

The evolution pipeline from [doc 03](03-evolution-and-safety.md) operates per-domain:

When a block version improves in the statistics domain, it improves WITHIN that domain's lockfile overlay.
The base lockfile (shared across domains) stays unchanged unless the improvement is proven across multiple domains.

This is the A/B testing pattern from [doc 05](05-parallel-evaluation.md) applied to domains: the shadow configuration runs the new block version within one domain, and promotion happens within that domain's overlay first, then optionally to the base lockfile.

---

## The FocusChain Block

All five scenarios rely on the agent maintaining structured awareness of what it is doing, at what level, and in which domain.
This requires a **FocusChain** as a first-class Layer 1 block in [doc 01](01-architecture-draft.md).

### What Exists Today

**Cline FocusChainManager** — aggressive prompt-pressure approach.
`task_progress` parameter on every tool call, periodic re-injection, history accumulation.
See [focus chain concept](../research/concepts/focus-chain/_index.md).

**Goose MOIM (Message of Injected Memory)** — clean architecture: fresh environmental context injected every turn at a fixed position, zero history accumulation.
See [Goose MOIM](../research/concepts/agentic-loop/02-direct-loops.md).

**Codex CLI `update_plan` tool** — the agent calls a tool to update its plan.
Minimalist: just a text field, no tree structure.
See [Codex CLI focus chain](../research/concepts/focus-chain/_index.md).

None of these support tree-structured plans with per-node state.

### What We Need

FocusChain as a Layer 1 block:
- Tree-structured plan (not flat text)
- Per-node state: status (pending/active/complete), summary (compressed after completion)
- Domain tag per node (which domain does this subtask belong to?)
- The root node is protected — never compressed
- Compression hooks: when a node completes, ContextBoundary fires tree compression
- Visible to the LLM: the agent sees the plan tree and can update it

The agent manages its FocusChain via tools (like Letta manages its memory via tools):
- `plan_update(node_id, action: add/complete/reorder)` — modify the plan tree
- `compress_completed_subtask(node_id)` — trigger tree compression for a completed node

### Why This Matters for All Five Scenarios

| Scenario | How FocusChain Helps |
|---|---|
| Context-rich spawning | The plan tree shows what subtask the child should work on, giving it structured purpose |
| Agent cloning | The clone sees the full plan tree, knows exactly where it fits and what it should bring back |
| Tree compression | The plan tree defines WHAT to compress and WHEN — compression follows plan structure |
| LLM-driven strategy | The agent sees the plan tree and decides: "this subtask needs cloning, that one needs a blank agent" |
| Domain partitioning | Domain tags on plan nodes route knowledge and scorecard data to the right DomainProfile |

---

## Software Engineering Ancestors

| Pattern | Source | How It Applies |
|---|---|---|
| **fork() + copy-on-write** | Unix process model | Agent cloning: fork the context, each branch writes independently, only copy what changes |
| **git branch / merge** | Git | GCC paper proves BRANCH/MERGE for agent context: +13pp on SWE-bench |
| **shared memory segments** | POSIX shmget/shmat | Letta shared blocks: multiple agents read/write the same memory region |
| **hierarchical task decomposition (HTN)** | AI planning (1975) | Tree-structured plans with subtask decomposition and per-level abstraction |
| **scope inheritance** | Programming languages (lexical scoping) | Child scopes inherit parent bindings but can shadow them: `inherit: blocks` pattern |
| **copy-on-write B-trees** | Databases (LMDB, CockroachDB) | Tree nodes share structure until modified, then diverge: per-node FileContext isolation |
| **namespace isolation** | Kubernetes, Python packages | Domain namespaces: knowledge is isolated per domain but cross-searchable |
| **Markov workspace reconstruction** | IterResearch (arXiv:2511.07327) | Periodic synthesis with context reset: +14.5pp over standard ReAct |
| **recursive summarization** | NLP (hierarchical summarization) | Tree compression: summarize leaves, then summarize summaries, preserving roots |
| **feature flags per tenant** | LaunchDarkly | Domain-specific lockfile overlays: different block versions for different domains |
| **event sourcing with projections** | CQRS pattern | The same event history projected differently for different consumers (parent vs child agents) |
