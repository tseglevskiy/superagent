# Cline SDK vs Superagent — Convergence and Divergence

**Date:** 2026-03-21
**Cline SDK commit:** [`dda2942`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef) (2026-03-20)
**Superagent docs:** 01-architecture-draft through 14-micro-mvp
**Research writeup:** [research/products/cline-sdk](../research/products/cline-sdk/_index.md)

## Purpose

This document maps specific Cline SDK design decisions to our superagent architecture concepts (docs 01-14), identifying where the teams converge as kindred spirits and where fundamental divergence defines our unique contribution.
Written for ongoing collaboration discussions — includes source file references so reasoning can be verified without re-reading the full codebase.

---

## Part 1: Where We Converge

### 1.1 Lego Architecture — Composable Packages with Strict Boundaries

**Our concept:** [Doc 01](01-architecture-draft.md) — "every architecture can be decomposed into the same ~10 primitive blocks. What varies is how they are wired together." The central design principle: every block communicates through the EventBus and reads/writes state through the Store. No block directly calls another block.

**Cline SDK:** Six packages with enforced import boundaries:
- [`@clinebot/shared`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/shared/) — base primitives (our Layer 0)
- [`@clinebot/llms`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/llms/) — provider abstraction (our LLMClient)
- [`@clinebot/agents`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/) — stateless runtime (our Layer 1 blocks + loop controllers)
- [`@clinebot/scheduler`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/scheduler/) — cron execution (no direct equivalent in our architecture)
- [`@clinebot/rpc`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/rpc/) — transport layer (no direct equivalent — we run in-process)
- [`@clinebot/core`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/core/) — stateful orchestration (our Store + session management)

Lint rules enforce no deep imports (`@clinebot/llms/*` is forbidden, only top-level `@clinebot/llms`).
See [ARCHITECTURE.md](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/ARCHITECTURE.md) "Dependency Direction" section.

**Degree of convergence:** High. Same principle, different language (TypeScript packages vs Python modules). Their enforcement via lint is more rigorous than our current plan.

### 1.2 Stateless Agent Core

**Our concept:** [Doc 13](13-application-architecture.md) — the reducer is a pure function: `(state, event) -> (new_state, effects)`. State is ~100 bytes. History is an append-only log on disk. The agent itself holds no mutable state.

**Cline SDK:** `@clinebot/agents` is explicitly declared stateless and runtime-agnostic.
The `Agent` class owns a `ConversationStore` (the canonical in-memory message array) but no persistent state.
State is decomposed into three classes:
- [`LifecycleOrchestrator`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/runtime/lifecycle-orchestrator.ts) — fires hooks, emits events via `AgentRuntimeBus`, tracks IDs
- [`TurnProcessor`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/runtime/turn-processor.ts) — single LLM turn: build messages → stream → parse → return `ProcessedTurn`
- [`ToolOrchestrator`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/runtime/tool-orchestrator.ts) — look up tools, check policies, execute, record results

All persistence (SQLite sessions, file artifacts) lives in `@clinebot/core`, not `@clinebot/agents`.
See [DOC.md](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/DOC.md) "Execution model and state" section.

**Degree of convergence:** Very high. The difference is form: our reducer is a single function, their separation is across three classes. The principle — stateless core, state externalized — is identical.

### 1.3 Event Bus

**Our concept:** [Doc 01](01-architecture-draft.md) Layer 0 — typed pub/sub. Every interaction flows through it. Inspired by OpenHands EventStream.

**Cline SDK:** [`AgentRuntimeBus`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/runtime/agent-runtime-bus.ts) — the `Agent` emits `AgentEvent` via `onEvent` callback:
- `iteration_start` / `iteration_end`
- `content_start` / `content_end` (for text, reasoning, or tool content)
- `usage` (token counts and cost)
- `done` (with finishReason)
- `error`

External consumers use `agent.subscribeEvents()` for non-polling observation.
Lifecycle transitions are emitted through `AgentRuntimeBus`, and dispatch is owned by `LifecycleOrchestrator`.

**Degree of convergence:** High. Same pattern. Their event types are less granular than ours (no separate events for context overflow, consolidation, block updates), but that is because they have no context management or knowledge processing.

### 1.4 Hook System — The Strongest Convergence

**Our concept:** [Doc 01](01-architecture-draft.md) Layer 3 `HookSystem` — lifecycle events that fire shell commands, LLM prompts, or programmatic handlers. Each hook receives JSON context and returns Allow/Block/InjectContext. Inspired by Claude Code's 14 lifecycle events.

**Cline SDK:** [`HookEngine`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/hooks/engine.ts) — 14 stages with priority-ordered handlers, timeout/retry policies, and control merge semantics.

**14 hook stages in dispatch order:**
1. `input` — extensions transform user input
2. `session_start` — once per conversation
3. `run_start` — beginning of each user-initiated run
4. `iteration_start` — start of each loop iteration
5. `turn_start` — before LLM call
6. `before_agent_start` — just before model stream
7. `tool_call_before` — before each tool execution (can request approval)
8. `tool_call_after` — after each tool execution with full `ToolCallRecord`
9. `turn_end` — after `ProcessedTurn` assembled
10. `iteration_end` — after all tool results persisted
11. `run_end` — when loop exits
12. `runtime_event` — extension-level observation
13. `session_shutdown` — when host calls `agent.shutdown()`
14. `error` — on loop failure

**Control merge semantics (the most sophisticated part):**
When multiple hooks return `AgentHookControl` for the same stage:
- `cancel`: logical OR (any hook cancels the run)
- `context`: newline-joined (all hooks contribute context)
- `overrideInput`: last writer wins
- `systemPrompt`: last writer wins
- `appendMessages`: concatenated in handler order

**Performance guardrails:** bounded timeout/retry per stage, async stages use bounded queue limits with per-stage concurrency budgets, hook routing is stage-indexed (dispatch does not scan unrelated handlers).

**Degree of convergence:** Very high — and they are AHEAD of us on implementation detail. Our doc 01 HookSystem describes the concept but does not specify merge semantics, priority ordering, or performance guardrails. We should adopt their control merge model.

### 1.5 Three-Level Multi-Agent = Our Weight Spectrum

**Our concept:** [Doc 13](13-application-architecture.md) "The Subagent Weight Spectrum" — four levels from `ask()` (single LLM call) to `spawn_subagent()` (full agent with own state machine).

**Cline SDK:** Three levels in [`packages/agents/src/teams/`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/teams/):

| Cline SDK Level | Our Level | Description |
|---|---|---|
| [`createSpawnAgentTool()`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/teams/spawn-agent-tool.ts) — dynamic sub-agent | Level 2-3: `MiniAgent` / `spawn_subagent` | Creates new `Agent` with `parentAgentId`, runs `agent.run(task)`, returns result |
| [`AgentTeam`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/teams/multi-agent.ts) — lightweight routing | No direct equivalent | Fixed agent roster with `routeTo`, `runParallel`, `runSequential`, `runPipeline`, `createWorkerReviewerTeam` |
| [`AgentTeamsRuntime`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/teams/multi-agent.ts) — full orchestration | Level 3 with team features | Task dependency graphs, mailbox, mission log, outcomes with review gates, priority run queues with retry/backoff |

**Key difference:** Their spectrum is about MULTI-AGENT coordination complexity. Our spectrum is about DELEGATION weight (from a single LLM call to a full agent). We have `ask("haiku", prompt)` and `pipeline()` which have NO equivalent in Cline SDK — every sub-agent in their system is a full `Agent` with `ConversationStore`, hooks, and tools.

**Degree of convergence:** Same principle (progressive complexity), different axis (their: coordination patterns, ours: computational weight). We should combine both axes.

### 1.6 Three-Layer Tool Permissions

**Our concept:** [Doc 01](01-architecture-draft.md) — `ToolRegistry` (register, discover, dispatch), `ApprovalGate` (pluggable policies: Always/Never/PatternMatch/SmartApprove/RiskBased), `InspectorPipeline` (chain of pre-execution checks).

**Cline SDK:** Three layers defined across [`packages/agents/src/tools/`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/tools/) and [`packages/core/src/tools/`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/core/src/tools/):

| Cline SDK Layer | Our Block | Description |
|---|---|---|
| `ToolPolicy` (static, per-tool): `enabled` + `autoApprove` | ToolRegistry | What tools exist and what their defaults are. Presets: "default", "yolo". Model-based routing in [`model-tool-routing.ts`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/core/src/tools/model-tool-routing.ts). |
| `ToolExecutionAuthorizer` (dynamic, per-call): returns `{ allowed, reason }` | InspectorPipeline | Runtime check before each tool call. Denial reason fed back to LLM. |
| `tool_call_before` hook: can `cancel` or `requestApproval` | ApprovalGate | Hook-based intervention. Approval flow: request → client decides → approve/deny. |

**Degree of convergence:** Near-identical decomposition. Three layers, same responsibilities, same separation of concerns.

### 1.7 Plugin Sandbox — Safety by Isolation

**Our concept:** [Doc 03](03-evolution-and-safety.md) "Protected Core" — Layer 0 infrastructure cannot be self-modified. Plugin code never runs in the host process.

**Cline SDK:** [`SubprocessSandbox`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/core/) — spawns Node.js child process with IPC:
- Parent → child: `{ type: "call", id, method, args }`
- Child → parent: `{ type: "response", id, ok, result, error }`
- Per-call timeouts, kill on timeout, all pending requests rejected
- `loadSandboxedPlugins()` loads plugins in child, returns proxy `AgentExtension` objects
- "Plugin code never runs in the host process — crashes, infinite loops, or malicious code in plugins cannot affect the core runtime"

**Degree of convergence:** Same principle, same implementation pattern. Their sandbox is simpler than our full Protected Core (which also includes the versioning system and the protection list), but the mechanism is identical.

### 1.8 Autonomous Idle Loop = Background Tier

**Our concept:** [Doc 10](10-continuous-learning.md) "Three Learning Speeds" — Background tier runs during idle: GEPA optimization, predict-calibrate, domain discovery, integration replay. Letta's sleep-time compute pattern.

**Cline SDK:** [`SchedulerService`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/scheduler/) with autonomous mode:
1. Cron trigger starts a session
2. Initial prompt augmented with "remain available, check team mailboxes and task lists"
3. After first turn, `runAutonomousIdleLoop()` begins
4. Polls every `pollIntervalSeconds` (default 5s)
5. Agent replies `<idle-noop/>` when no work → idle deadline NOT reset
6. Agent does real work → idle deadline resets
7. Loop exits when idle timeout expires

See scheduler source for `autonomous.enabled`, `pollIntervalSeconds`, `idleTimeoutSeconds` in schedule metadata.

**Degree of convergence:** Same pattern — agent stays alive during idle and does background work. Their version is about team task coordination; ours is about knowledge processing (consolidation, optimization, reflection). The mechanism is the same; the purpose is different.

### 1.9 Task Dependency Graphs = FocusChain Subtasks

**Our concept:** [Doc 07](07-context-flow.md) "FocusChain" — tree-structured plan with per-node state (pending/active/complete/summary). Compression hooks fire on subtask completion. The agent manages the plan via tools.

**Cline SDK:** `AgentTeamsRuntime` task system:
- `createTask(input)` with optional `dependsOn: string[]`
- `claimTask(taskId, agentId)` — validates all dependencies resolved
- `blockTask(taskId, reason)` / `completeTask(taskId, summary)`
- `listTaskItems({ readyOnly: true })` — returns only tasks with no unresolved dependencies
- `isReady` + `blockedBy` for dependency inspection

**Key difference:** Their tasks are for multi-agent coordination (who works on what). Our FocusChain is for single-agent context management (what to compress, what to keep). Same data structure (DAG with dependencies, status tracking), different purpose.

**Degree of convergence:** Moderate. Same data structure, different use case. We could potentially share the implementation.

### 1.10 Session Persistence = Our Session Traces

**Our concept:** [Doc 06](06-testing-platform.md) Tier 2 — auto-recorded session traces become integration replay tests. [Doc 11](11-memory-architecture.md) Mode 2 — session history is permanently searchable.

**Cline SDK:** Dual-level persistence:
- **File artifacts:** `<sessionId>.json` (manifest), `<sessionId>.log` (transcript), `<sessionId>.hooks.jsonl` (hook log), `<sessionId>.messages.json` (full LLM messages)
- **SQLite records:** `sessions` table with 25+ columns including `status_lock` for optimistic concurrency

See [`UnifiedSessionPersistenceService`](https://github.com/cline/sdk-wip/tree/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/core/) for the routing logic.

**Degree of convergence:** Same persistence model. They record everything we need for Tier 2 replay tests (full message arrays, tool call records). They just don't USE it for testing — only for session resume.

---

## Part 2: Where We Diverge Fundamentally

### 2.1 Context Management — Their Biggest Gap

**Our concept:** Docs [07](07-context-flow.md), [10](10-continuous-learning.md), [13](13-application-architecture.md) — five context flow scenarios, tree-structured compression, FocusChain as Layer 1 block, ContextBoundary with pluggable strategies.

**Cline SDK:** Direct quote from the research writeup:

> "The SDK has no context management. The conversation grows unboundedly until the provider's API rejects it with a 400 error, at which point the agent terminates with `finishReason: "error"`. There is no compaction, sliding window, or summarization."

The `ProcessedTurn` interface has a `truncated: boolean` field, but no recovery logic is triggered.
Context-length errors from providers match 400 and are classified as non-recoverable by `isNonRecoverableApiError()`, causing immediate termination.

The [`MessageBuilder`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/message-builder.ts) can truncate oversized tool results to `maxToolResultChars`, but this is defensive truncation, not strategic context management.

**What this means for us:** Our entire docs 07 (5 context flow scenarios) and the context sections of doc 13 (ContextBoundary, tree compression, FocusChain) have NO counterpart in Cline SDK. This is a pure capability gap on their side — and our primary technical differentiator in the runtime layer.

### 2.2 Persistent Memory / Knowledge — No Equivalent

**Our concept:** Docs [02](02-knowledge-as-code.md) (Knowledge as Code), [11](11-memory-architecture.md) (Memory Architecture), [12](12-knowledge-reflection.md) (Knowledge Reflection) — three artifact types (tools, strategies, compositions), hierarchical knowledge store, five operations (ADD, CONSOLIDATE, RETRIEVE, UPDATE, RETIRE), five reflection processes.

**Cline SDK:** From the research writeup:

> "The SDK does not implement memory blocks, vector stores, or archival/semantic memory. Cross-session continuity is limited to: `initialMessages` (manual message replay), `parentSessionId` (sub-agent tree linkage), and team state persistence via `SqliteTeamStore`."

The only cross-session knowledge mechanism is:
- Manually passing `initialMessages` to `agent.restore(messages)` then `agent.continue(prompt)`
- Team state (tasks, mailbox, mission log, runs, outcomes) persisted in `SqliteTeamStore` keyed by `teamName`
- Session resume via `--session <id>` loading previous messages

There is no semantic retrieval, no knowledge extraction, no consolidation, no domain profiles, no predict-calibrate, no utility scoring.

**What this means for us:** Our entire knowledge hierarchy (docs 02, 11, 12) — the Voyager-inspired skill library, the A-MEM link graph, the Nemori predict-calibrate, the GEPA optimization pipeline — has no counterpart. This is our second primary differentiator.

### 2.3 Self-Improvement / Evolution — No Equivalent

**Our concept:** Docs [03](03-evolution-and-safety.md) (Evolution and Safety), [04](04-measurement.md) (Measurement), [05](05-parallel-evaluation.md) (Parallel Evaluation) — immutable versioned blocks with SemVer, lockfiles, admission pipeline (5 gates), canary deployment, shadow mode, 8-metric scorecard, three-cause attribution model.

**Cline SDK:** No versioning of agent configurations. No A/B testing. No scorecard. No attribution model. No shadow mode.

The closest mechanism is `AgentTeamsRuntime.exportState()` / `hydrateState(state)` for team state serialization, but this is operational persistence, not evolutionary versioning.

**What this means for us:** Our "performance as delta" vision (doc 09 — the agent improves over months) has no counterpart. Cline SDK agents start fresh every time. They have the same capability on day 1 and day 100.

### 2.4 Code-as-Action — No Equivalent

**Our concept:** [Doc 13](13-application-architecture.md) "Code-as-Action and Code-as-Knowledge" — the agent communicates via Python code (smolagents CodeAgent pattern). Knowledge stored as code means retrieval gives the agent functions it can call directly. Block-attached functions travel with their memory blocks.

**Cline SDK:** Traditional JSON tool calls. The agent calls `read_files`, `run_commands`, `edit_file`, etc. via structured tool call arguments parsed from the LLM stream by [`streaming.ts`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/streaming.ts) using `parseJsonStream`.

Tool arguments are buffered from stream chunks and finalized at end-of-turn, so tools execute against finalized payloads instead of partial JSON fragments.

**What this means for us:** Our `ask("haiku", prompt)` / `pipeline()` / `MiniAgent` primitives have no equivalent because they require code-as-action. In Cline SDK, the agent cannot write `for path in paths: score = await ask("haiku", ...)` — it can only call predefined tools. This limits the agent's ability to compose novel strategies at runtime.

### 2.5 Lightweight Delegation — No Equivalent

**Our concept:** [Doc 13](13-application-architecture.md) "The Subagent Weight Spectrum" — Level 0 (`ask()`: single LLM call, ~$0.001) and Level 1 (`pipeline()`: chained LLM calls) for trivial delegation that costs no more than a regex operation to create.

**Cline SDK:** Every sub-agent is a full `Agent` with `ConversationStore`, hooks, tools, and event emission. `createSpawnAgentTool()` in [`spawn-agent-tool.ts`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/teams/spawn-agent-tool.ts) creates a standard tool that spawns a new `Agent` instance — the same heavyweight object as the parent.

The document scanning use case from our doc 13 (scan 50 documents with Haiku for $0.05 instead of reading them all into Sonnet's context for $4.50) is simply impossible in Cline SDK's current architecture.

**What this means for us:** This is a practical capability gap that directly affects cost and context efficiency. Our lightweight delegation primitives enable strategies that are not expressible in Cline SDK's tool-call model.

---

## Part 3: What We Should Learn from Them

### 3.1 Hook Control Merge Semantics

Their `AgentHookControl` merge model is more developed than ours:
- `cancel`: logical OR (any hook cancels)
- `context`: newline-joined (all hooks contribute)
- `overrideInput`: last writer wins
- `systemPrompt`: last writer wins
- `appendMessages`: concatenated in handler order

**Action:** Adopt this merge model for our HookSystem. It is well-thought-out and handles the multi-handler case cleanly.

### 3.2 Performance Guardrails on Hooks

Their `HookEngine` has:
- Bounded timeout/retry per stage
- Async stages with bounded queue limits and per-stage concurrency budgets
- Stage-indexed routing (dispatch does not scan unrelated handlers)
- Priority-ordered deterministic execution (higher priority first, then handler name)

**Action:** Our doc 01 HookSystem should specify these guardrails.

### 3.3 Optimistic Status Locking

Their SQLite session persistence uses `status_lock` — an optimistic concurrency counter:
1. Read `status_lock`
2. `UPDATE ... WHERE session_id = ? AND status_lock = ?`
3. Increment on success
4. Retry on conflict

**Action:** If we use SQLite for session/knowledge persistence, this is a proven pattern for concurrent access.

### 3.4 Two-Layer Distributed Locking for Process Coordination

Their server spawn uses:
- Layer 1: directory lock (`mkdir` atomic) with 30s TTL and PID staleness check
- Layer 2: file-based spawn lease (`wx` exclusive flag) with 15s TTL

**Action:** If we ever need multi-process coordination (e.g., multiple agent instances sharing a knowledge store), this is a battle-tested approach.

### 3.5 The Team Tools Surface

Their 22 `team_*` tools expose the full `AgentTeamsRuntime` API to the agent:
`team_spawn_teammate`, `team_shutdown_teammate`, `team_create_task`, `team_list_tasks`, `team_claim_task`, `team_complete_task`, `team_block_task`, `team_run_task`, `team_cancel_run`, `team_list_runs`, `team_await_run`, `team_await_all_runs`, `team_send_message`, `team_broadcast`, `team_read_mailbox`, `team_log_update`, `team_create_outcome`, `team_attach_outcome_fragment`, `team_review_outcome_fragment`, `team_finalize_outcome`, `team_list_outcomes`, `team_cleanup`.

This is the "Letta approach" — giving the agent tools to manage its own runtime state — applied to team coordination. It validates our doc 07 approach of giving the agent tools to manage its own context (`plan_update`, `compress_completed_subtask`, `compact_context`).

### 3.6 MCP Tool Integration Pattern

[`createMcpTools()`](https://github.com/cline/sdk-wip/blob/dda2942a4c9ea1e90aec052c91e7ac207d21c2ef/packages/agents/src/mcp/tools.ts) wraps remote MCP tool descriptors into the standard `Tool` interface with optional name transforms, timeouts, and retry configuration. This is a clean adapter pattern that our ToolRegistry should support.

---

## Summary: The Three-Layer View

| Layer | Cline SDK | Superagent | Convergence |
|---|---|---|---|
| **Runtime** (event bus, hooks, tools, loop, multi-agent) | ✅ Production-grade, 6 packages, 14-stage hooks, 3-level multi-agent, 40 LLM providers, gRPC RPC, scheduler | ✅ Designed, not yet built. 5 files, reducer pattern, weight spectrum, code-as-action | 🟢 High — same principles, they are further in implementation |
| **Context Intelligence** (context management, compression, FocusChain, inheritance) | ❌ None. Context grows until 400 error. | ✅ 5 scenarios, tree compression, FocusChain, domain-aware partitioning, lightweight delegation | 🔴 Zero overlap — our unique contribution |
| **Knowledge & Evolution** (memory, learning, self-improvement, measurement) | ❌ None. No memory blocks, no knowledge store, no versioning, no scorecard. | ✅ Hierarchical knowledge store, 5 operations, 5 reflections, lockfile evolution, GEPA optimization, shadow mode | 🔴 Zero overlap — our unique contribution |

**The bottom line:** Cline SDK is an excellent runtime without a brain. We are building the brain. The runtime layers converge enough that integration is natural — the context intelligence and knowledge layers sit on top of the same kind of event-driven, hook-enabled, stateless-core architecture that both projects share.
