# Superagent Architecture Draft

## Reasoning: Why a Lego Architecture Is Possible

After studying 28 agent products across 7 architectural patterns, one observation stands out: every architecture can be decomposed into the same ~10 primitive blocks.
What varies is how they are wired together.

The evidence for this:

- **Direct loops** (Cline, Codex CLI, Goose, Claude Code) all do the same thing: assemble context, call LLM, parse tool calls, approve, dispatch, observe, check bounds, check stuck.
  The differences are in which sub-steps exist and how they are configured — not in the overall structure.
  See the [direct loops comparison](../research/concepts/agentic-loop/02-direct-loops.md) — Cline's 12 termination conditions vs Codex CLI's proactive compaction vs Goose's 3-inspector pipeline are all pluggable behaviors on the same skeleton.

- **Event-driven loops** (OpenHands) and **direct loops** differ only in who drives iteration: an explicit `while` vs a pub/sub subscriber reacting to events.
  The actual per-step logic (assemble, call LLM, parse, approve, dispatch) is identical.
  OpenHands' [EventStream architecture](../research/concepts/agentic-loop/04-event-driven-loops.md) is the most principled because it makes the event bus explicit — but every agent implicitly has one.

- **Research agent architectures** (Open Deep Research, PaperQA2, STORM) are compositions of smaller loops.
  Open Deep Research's [3-tier nested StateGraph](../research/concepts/deep-research/03-open-deep-research.md) is a supervisor loop that spawns sub-agent loops — the supervisor and each researcher are both standard direct loops, just with different tool sets and isolated state.
  The "3-tier" is not a new primitive — it is SubAgentSpawner + ArchitecturalIsolation + DirectLoop.

- **Tree search** (Moatless) replaces the linear loop body with Select-Expand-Simulate-Backpropagate, but the Simulate phase is just a standard direct loop step with per-node isolated state.
  See [tree search loops](../research/concepts/agentic-loop/07-tree-search-loops.md) — the `AgenticLoop` and `SearchTree` share the same Node/FileContext infrastructure.

- **Evolutionary loops** (DGM, OpenEvolve) replace the loop body with Select-Mutate-Evaluate-Archive.
  The Mutate step uses an LLM (inner coding agent for DGM, single-shot diff for OpenEvolve), but the selection, evaluation, and archiving are all non-LLM infrastructure.
  See [evolutionary loops](../research/concepts/agentic-loop/08-evolutionary-loops.md).

The common thread: **every architecture is a loop controller wiring together the same functional blocks**.
The blocks (context assembly, tool dispatch, approval, stuck detection, context bounding, value scoring) are the same across all 7 patterns.
Only the loop controller differs.

A second key observation from the [context management comparison](../research/concepts/context-management/05-comparison.md): the bounding strategies (no management, count-window, token-threshold, architectural isolation, agent-initiated) are orthogonal to the loop type.
Any bounding strategy can be plugged into any loop controller.
This confirms the Lego property: blocks compose independently.

---

## Layer 0 — Infrastructure

Three foundational pieces that every block reads from or writes to.

### EventBus

Typed pub/sub message bus.
Every interaction flows through it: user messages, LLM responses, tool calls, tool results, observations, errors, state transitions.

Inspired by:
- [OpenHands EventStream](../research/concepts/agentic-loop/04-event-driven-loops.md) — the most explicit implementation: append-only stream with monotonic IDs, three independent subscribers (Controller, Runtime, Memory)
- [n8n EngineRequest/Response protocol](../research/concepts/agentic-loop/03-delegated-loops.md) — typed messages between two independent execution layers
- [Goose message metadata](../research/concepts/context-management/03-coding-agents.md) — dual-audience visibility tags (`user_visible`, `agent_visible`) on every message

### Store

Pluggable state persistence.
In-memory, file, SQLite, Redis, S3.
All blocks read/write state through the Store, never through direct mutation of shared variables.

Inspired by:
- [OpenHands FileStore](../research/concepts/agentic-loop/04-event-driven-loops.md) — events persisted to local disk, S3, or GCS
- [Letta memory blocks](../research/concepts/context-management/03-coding-agents.md) — memory blocks in database, rendered into system prompt each turn
- [Moatless per-node FileContext](../research/concepts/agentic-loop/07-tree-search-loops.md) — deep-copied state per tree node
- [n8n external database history](../research/concepts/context-management/03-coding-agents.md) — Postgres, Redis, MongoDB for conversation persistence

### LLMClient

Provider-normalized abstraction.
Takes messages + tool schemas, returns text and/or tool calls.
Handles streaming, retries, rate limits, prompt caching.

Inspired by:
- [Agentic loop foundation — wire format normalization](../research/concepts/agentic-loop/01-the-react-foundation.md) — Anthropic, OpenAI Chat, OpenAI Responses, Gemini all described
- [Codex CLI — WebSocket + SSE transport](../research/concepts/agentic-loop/02-direct-loops.md) — OpenAI Responses API with sticky routing
- [PaperQA2 multi-LLM roles](../research/concepts/deep-research/02-paperqa2.md) — 4 separate LLM roles independently configurable
- [Ouroboros model fallback chains](../research/concepts/agentic-loop/02-direct-loops.md) — Claude to Gemini to GPT failover

---

## Layer 1 — Core Blocks

### ContextAssembler

Builds the prompt for each LLM call from pluggable segments.
Each segment is a function that reads from Store and returns messages.
Order is configurable.
Cache breakpoints at segment boundaries.

Inspired by:
- [Aider 8-segment ChatChunks](../research/concepts/context-management/03-coding-agents.md) — `system, examples, readonly_files, repo, done, chat_files, cur, reminder` in fixed order with cache breakpoints
- [Ouroboros 3-block prompt caching](../research/concepts/context-management/03-coding-agents.md) — static block (1h TTL), semi-stable (ephemeral), dynamic (no cache)
- [Cline dynamic system prompt](../research/concepts/context-management/01-what-the-llm-sees.md) — rebuilt every turn with ~15 dynamic sections
- [OpenClaw XML-structured system prompt](../research/concepts/context-management/01-what-the-llm-sees.md) — sections for identity, tools, runtime, skills, workspace, memory
- [Letta compile_system_message](../research/concepts/context-management/03-coding-agents.md) — memory blocks rendered into system prompt via template variable, changes every turn
- [Moatless span-based FileContext](../research/concepts/agentic-loop/07-tree-search-loops.md) — only selected code spans shown, outcommented placeholders for hidden code

### ToolRegistry

Register, discover, dispatch tools.
Supports local functions, MCP servers, code-as-tool, node-as-tool.
Each tool has: schema, handler, concurrency flag, approval requirement, result-as-answer flag.
Discovery modes: static list, deferred search, dynamic enable/disable.

Inspired by:
- [Goose MCP-native dispatch](../research/concepts/agentic-loop/02-direct-loops.md) — all tools via MCP extensions, dispatched through ExtensionManager
- [n8n node-as-tool via $fromAI](../research/concepts/agentic-loop/03-delegated-loops.md) — 400+ integration nodes become AI tools without modification
- [Ouroboros two-tier tool system](../research/concepts/agentic-loop/02-direct-loops.md) — 29 core always loaded, 23+ extended discoverable via `list_available_tools` / `enable_tools`
- [Claude Code MCPSearch meta-tool](../research/concepts/context-management/03-coding-agents.md) — deferred MCP tool descriptions when they exceed 10% of context
- [smolagents code-as-tool](../research/concepts/agentic-loop/09-comparison.md) — LLM writes arbitrary Python, tools are callable functions
- [Tool calling concept](../research/concepts/tool-calling/_index.md) — 6 transport mechanisms, 5 definition patterns, 5 discovery modes

### ContextBoundary

Pluggable bounding strategies, composable in pipelines.
Each strategy is a function: `(messages, config) -> (messages, metadata)`.
Strategies compose: `pipeline([ObservationMasking, TokenThreshold, LLMSummary])`.

Strategy families (from [bounding strategies](../research/concepts/context-management/02-bounding-strategies.md)):
- NoOp — smolagents, Godel Agent
- CountWindow — n8n `contextWindowLength`, SWE-Agent `LastNObservations`
- TokenThreshold — Codex CLI proactive, Goose 80%, Cline 75%
- ArchitecturalIsolation — Open Deep Research 3-tier, PaperQA2, STORM per-perspective, Voyager per-call fresh
- AgentInitiated — OpenHands `condensation_request`, Ouroboros `compact_context`

Inspired by:
- [OpenHands 11 pluggable condensers](../research/concepts/context-management/03-coding-agents.md) — filter + rolling condensers in arbitrary pipeline
- [OpenHands StructuredSummaryCondenser](../research/concepts/agentic-loop/04-event-driven-loops.md) — typed StateSummary with 17 fields instead of lossy prose
- [Codex CLI proactive compaction](../research/concepts/agentic-loop/02-direct-loops.md) — before every turn, not after overflow
- [Codex CLI model-switch pre-compaction](../research/concepts/context-management/03-coding-agents.md) — compact against previous model limits when switching
- [OpenClaw 4-layer fallback chain](../research/concepts/context-management/03-coding-agents.md) — Pi SDK auto, safeguard, cache-TTL pruning, tool truncation
- [Autocompressing concept](../research/concepts/autocompressing/_index.md) — detailed compression algorithms per product

### ApprovalGate

Intercepts tool calls before execution.
Pluggable policies.
Returns: Allow, Deny with reason, AskHuman with prompt.

Policy types:
- Always / Never
- PatternMatch — glob on tool name + args
- SmartApprove — LLM classifies read-only
- RiskBased — LOW/MEDIUM/HIGH
- PostLoop — review after agent finishes

Inspired by:
- [Cline ask method](../research/concepts/agentic-loop/02-direct-loops.md) — pWaitFor polling every 100ms, YOLO mode bypass
- [Codex CLI 5 approval policies](../research/concepts/agentic-loop/02-direct-loops.md) — never, on-request, unless-allow-listed, always-ask, unless-trusted
- [Goose LLM-based smart_approve](../research/concepts/agentic-loop/02-direct-loops.md) — calls LLM to classify read-only, caches results per tool name
- [OpenHands 3 pluggable security analyzers](../research/concepts/agentic-loop/04-event-driven-loops.md) — LLMRisk, Invariant, GraySwan
- [CrewAI post-loop human review](../research/concepts/agentic-loop/03-delegated-loops.md) — review gate after final answer, not per-tool
- [Security concept](../research/concepts/security/_index.md) — sandboxing, authorization, approval flows across all products

### InspectorPipeline

Chain of pre-execution checks.
Each inspector: `(tool_call, context) -> Allow | Block(reason) | Modify(new_call)`.

Inspired by:
- [Goose 3-inspector pipeline](../research/concepts/agentic-loop/02-direct-loops.md) — SecurityInspector, PermissionInspector, RepetitionInspector in order
- [EloPhanto injection guarding](../research/concepts/agentic-loop/02-direct-loops.md) — `[UNTRUSTED_CONTENT]` markers on tool output
- [LLM Guard scanner pipeline](../research/products/llm-guard/_index.md) — 16 input + 22 output scanners, composable

### StuckDetector

Pluggable pattern matchers run after each step.
Returns: Continue | Intervene with strategy.

Patterns from the study:
- Repeated action+observation (4x) — [OpenHands](../research/concepts/agentic-loop/04-event-driven-loops.md)
- Repeated action+error (3x) — [OpenHands](../research/concepts/agentic-loop/04-event-driven-loops.md)
- Monologue (3x) — [OpenHands](../research/concepts/agentic-loop/04-event-driven-loops.md)
- Alternating oscillation — [OpenHands](../research/concepts/agentic-loop/04-event-driven-loops.md)
- Context window loop (10x) — [OpenHands](../research/concepts/agentic-loop/04-event-driven-loops.md)
- Consecutive mistake count — [Cline](../research/concepts/agentic-loop/02-direct-loops.md)
- RepetitionInspector sliding window — [Goose](../research/concepts/agentic-loop/02-direct-loops.md)
- 5-layer stagnation — [EloPhanto](../research/concepts/agentic-loop/02-direct-loops.md)
- Self-check checkpoints every N rounds — [Ouroboros](../research/concepts/agentic-loop/02-direct-loops.md)
- Doom loop detector (3 identical consecutive) — [OpenCode](../research/concepts/agentic-loop/02-direct-loops.md)

### ValueFunction

Scores actions, trajectories, or variants.
Interface: `(trajectory, criteria) -> score + explanation`.

Used by:
- Tree search — [Moatless per-node LLM scoring](../research/concepts/agentic-loop/07-tree-search-loops.md), UCT with 14 score components
- Evolutionary loops — [DGM SWE-bench fitness](../research/concepts/agentic-loop/08-evolutionary-loops.md)
- Coverage assessment — [Open Deep Research think_tool reflection](../research/concepts/deep-research/03-open-deep-research.md)
- Best-of-N — [SWE-Agent RetryAgent with reviewer/chooser](../research/concepts/agentic-loop/02-direct-loops.md)
- [LLM-as-Judge concept](../research/concepts/llm-as-judge/_index.md) — per-action, per-trajectory, per-session, per-variant evaluation

### ErrorHandler

Retry with backoff, model fallback chain, compaction-on-overflow, abort.
Configurable per error type.

Inspired by:
- [OpenClaw 4-layer recovery](../research/concepts/agentic-loop/03-delegated-loops.md) — auth rotation, model failover, compaction, tool truncation, up to 160 iterations
- [Ouroboros fallback model chains](../research/concepts/agentic-loop/02-direct-loops.md) — Claude to Gemini to GPT
- [Cline first-chunk vs mid-stream error handling](../research/concepts/agentic-loop/02-direct-loops.md) — different strategies for different failure points
- [Codex CLI model-switch pre-compaction](../research/concepts/context-management/03-coding-agents.md) — preemptive compaction when switching to smaller model
- [Goose progressive tool response removal](../research/concepts/agentic-loop/02-direct-loops.md) — 0% to 10% to 20% to 50% to 100% escalation

---

## Layer 2 — Loop Controllers

Six patterns, all assembled from Layer 1 blocks.

### A. DirectLoop

```
while(true) {
  ContextAssembler.build()
  LLMClient.call()
  parse response
  ApprovalGate.check()
  InspectorPipeline.run()
  ToolRegistry.dispatch()
  ContextBoundary.check()
  StuckDetector.check()
}
```

Covers: [Cline](../research/concepts/agentic-loop/02-direct-loops.md), [Codex CLI](../research/concepts/agentic-loop/02-direct-loops.md), [Goose](../research/concepts/agentic-loop/02-direct-loops.md), [Ouroboros](../research/concepts/agentic-loop/02-direct-loops.md), [EloPhanto](../research/concepts/agentic-loop/02-direct-loops.md), [Claude Code](../research/concepts/agentic-loop/02-direct-loops.md), [OpenCode](../research/products/opencode/_index.md)

### B. EventReactiveLoop

Subscribe to EventBus.
On observation: `should_step()` then `step()` then publish Action.
On action: Runtime executes then publishes Observation.

Covers: [OpenHands](../research/concepts/agentic-loop/04-event-driven-loops.md), [Letta with heartbeat variant](../research/concepts/agentic-loop/04-event-driven-loops.md)

### C. DelegatedLoop

Setup (system prompt, tools, hooks) then delegate to external SDK/framework then receive streaming events then teardown.
The inner loop is opaque.

Covers: [OpenClaw via Pi SDK](../research/concepts/agentic-loop/03-delegated-loops.md), [n8n via LangChain + EngineRequest](../research/concepts/agentic-loop/03-delegated-loops.md), [CrewAI dual-mode](../research/concepts/agentic-loop/03-delegated-loops.md)

### D. PipelineLoop

`stage1 | stage2 | ... | stageN` with no feedback between stages.
Parallelism via fan-out at specific stages.

Covers: [GPT-Researcher standard mode](../research/concepts/deep-research/04-gpt-researcher.md), [STORM 4-module pipeline](../research/concepts/deep-research/05-storm.md), [Aider edit-lint-test-reflect](../research/concepts/agentic-loop/05-edit-driven-loops.md)

### E. TreeSearchLoop

```
while(budget) {
  Select(UCB scoring)
  Expand(+ feedback from siblings)
  Simulate(execute action against repo)
  Backpropagate(ValueFunction scores up the tree)
}
```

Per-node isolated State.

Covers: [Moatless MCTS](../research/concepts/agentic-loop/07-tree-search-loops.md).
SWE-Agent Best-of-N is a degenerate tree with depth=1.

### F. EvolutionaryLoop

```
while(budget) {
  SelectParent(archive, fitness)
  Mutate(LLM generates diff)
  Evaluate(sandbox + benchmark)
  UpdateArchive(selection criteria)
}
```

Covers: [DGM](../research/concepts/agentic-loop/08-evolutionary-loops.md), [OpenEvolve](../research/concepts/agentic-loop/08-evolutionary-loops.md), [Godel Agent](../research/concepts/agentic-loop/08-evolutionary-loops.md), [EvoAgentX](../research/concepts/agentic-loop/08-evolutionary-loops.md)

---

## Layer 3 — Compositions

Higher-order patterns built by combining loop controllers.

### SubAgentSpawner

Creates a new Agent (any loop type) with isolated State scope.
The parent communicates via EventBus or a return value.

Inspired by:
- [Claude Code Task tool](../research/concepts/agentic-loop/02-direct-loops.md) — subagents with context isolation, recursive spawning
- [OpenHands AgentDelegateAction](../research/concepts/agentic-loop/04-event-driven-loops.md) — scoped EventStream view, cost propagation
- [Open Deep Research supervisor spawning researchers](../research/concepts/deep-research/03-open-deep-research.md) — up to 5 concurrent via asyncio.gather
- [OpenCode TaskTool](../research/concepts/agentic-loop/02-direct-loops.md) — child sessions with restricted permissions
- [Multi-agent concept](../research/concepts/multi-agent/_index.md) — 5 architectural patterns across 19 products

### SupervisorPattern

think then delegate (spawn sub-agents) then collect compressed results then reflect then repeat or complete.
Assembled from: DirectLoop + SubAgentSpawner + ContextBoundary(ArchitecturalIsolation) + ValueFunction(coverage).

Inspired by:
- [Open Deep Research supervisor](../research/concepts/deep-research/03-open-deep-research.md) — think_tool, ConductResearch, ResearchComplete
- [Coverage assessment concept](../research/concepts/coverage-assessment/_index.md) — how agents decide when to stop

### HookSystem

Lifecycle events that fire shell commands, LLM prompts, or programmatic handlers.
Each hook receives JSON context and returns Allow/Block/InjectContext.

Inspired by:
- [Claude Code 14 lifecycle events](../research/products/claude-code/_index.md) — PreToolUse, PostToolUse, Stop, PreCompact, etc.
- [Hooks concept](../research/concepts/hooks/_index.md) — 8 products with hook systems, 3 handler types, JSON I/O protocol
- [ECC hook consumer](../research/products/ecc/_index.md) — continuous learning pipeline built on hooks

### PeerGroupOrchestrator

Multiple agents as conversational equals with pluggable turn-taking.
No parent-child hierarchy — agents have their own persistent identities, and a routing layer manages who speaks next.

Orchestration types (from [peer agent groups](../research/concepts/multi-agent/03-peer-agent-groups.md)):
- RoundRobin — fixed rotation, agents speak in order
- Dynamic — LLM-based manager selects next speaker based on conversation
- Supervisor — supervisor agent broadcasts to all, collects responses
- Sleeptime — main agent handles conversation, background agents process transcripts asynchronously

This is distinct from SubAgentSpawner: in parent-child, one agent is in charge.
In peer groups, agents are equals — the orchestrator routes messages but has no agency of its own (or if it does, it is a separate manager agent, not a participant).

Inspired by:
- [CrewAI role-based Crews](../research/concepts/multi-agent/03-peer-agent-groups.md) — sequential/hierarchical processes with DelegateWorkTool/AskQuestionTool for inter-agent delegation
- [Letta 4 group orchestration types](../research/concepts/multi-agent/03-peer-agent-groups.md) — round-robin, dynamic (LLM manager picks speaker), supervisor (broadcast+collect), sleeptime (background transcript processing)
- [Letta agent-to-agent messaging tools](../research/concepts/multi-agent/03-peer-agent-groups.md) — send_message_to_agent_and_wait_for_reply, broadcast by tags, fire-and-forget async
- [EvoAgentX Multi-Agent Debate](../research/concepts/multi-agent/07-cross-project-comparison.md) — N debaters + judge in peer group

### EnvironmentMultiplexer

Multiple complete agent instances running in isolated environments with no inter-agent communication.
A human or script decides which agents to launch.
Each gets its own workspace.
Coordination via merge strategies, human review, or shared filesystem artifacts.

The key property: adding an agent requires no changes to any existing agent.
No communication protocol, no awareness of other agents.
Most extensible pattern — any agent CLI can participate.

Inspired by:
- [dmux — the canonical multiplexer](../research/concepts/multi-agent/05-environment-multiplexing.md) — 11 coding agent CLIs in git worktrees via tmux, LLM-based terminal analysis for agent-agnostic status detection, autopilot mode, two-phase merge with AI conflict resolution
- [Voicetree agent-agnostic terminal spawning](../research/concepts/multi-agent/05-environment-multiplexing.md) — when used without MCP communication tools

### SharedStateStore

Agents coordinate through persistent shared artifacts rather than direct message passing.
Cross-cutting mechanism — always combines with another pattern.
Enables implicit coordination where agents do not need to know about each other.

Artifact types:
- Shared memory blocks — multiple agents read/write the same data
- Graph nodes — agents discover each other's work via spatial/semantic search
- Files on disk — agents coordinate through a shared filesystem

Inspired by:
- [Letta shared memory blocks](../research/concepts/multi-agent/06-shared-state-coordination.md) — multiple agents in a group read/write the same Block objects; sleeptime agents consolidate memory in background
- [Voicetree graph nodes](../research/concepts/multi-agent/06-shared-state-coordination.md) — agents see each other's work via search_nodes, get_unseen_nodes, and spatial proximity on the graph
- [dmux git repository](../research/concepts/multi-agent/05-environment-multiplexing.md) — agents in separate worktrees, merge reconciles their changes

### AgentLifecycleManager

Full lifecycle management for spawned agents: spawn, message, wait, resume, kill, steer.
Goes beyond simple SubAgentSpawner — supports bidirectional communication with running agents, not just fire-and-collect.

Inspired by:
- [Codex CLI 5 lifecycle tools](../research/concepts/multi-agent/02-parent-child-delegation.md) — spawn_agent, send_input (with interrupt), wait (with timeout), resume_agent (from persistence), close_agent; typed roles (default/explorer/worker/monitor); agent_max_depth and agent_max_threads limits
- [OpenClaw subagent management](../research/concepts/multi-agent/02-parent-child-delegation.md) — list/kill/steer active subagents, maxSpawnDepth, maxChildrenPerAgent, lifecycle hooks (subagent_spawning/spawned/ended)
- [Voicetree MCP tools](../research/concepts/multi-agent/02-parent-child-delegation.md) — spawn_agent, wait_for_agents, send_message, list_agents, close_agent on visible graph

---

## The Central Design Principle

The Lego property comes from one rule: **every block communicates through the EventBus and reads/writes state through the Store**.
No block directly calls another block.

This means:
- Swap ContextBoundary strategies without touching the loop controller
- Add InspectorPipeline to any loop type
- Nest any loop type inside SubAgentSpawner
- Attach HookSystem to any lifecycle event from any loop
- Add ValueFunction to any loop for scoring, coverage, or fitness
- Combine loop controllers: a SupervisorPattern with TreeSearchLoop researchers, or an EvolutionaryLoop whose inner agent is a DirectLoop

The EventBus + Store pattern is what [OpenHands already does](../research/concepts/agentic-loop/04-event-driven-loops.md) — and it is the most architecturally principled system in the study for exactly this reason.

---

## Mapping Studied Architectures to This Framework

- **Cline** — DirectLoop + ContextAssembler(XML parse) + ApprovalGate(AskHuman) + StuckDetector(mistake count) + ErrorHandler(truncation) + SubAgentSpawner(read-only research) + Store(mutable array with deleted range mask)
- **Codex CLI** — DirectLoop + ContextBoundary(proactive token-threshold) + ApprovalGate(5 policies) + AgentLifecycleManager(spawn/send/wait/resume/close with typed roles) + ErrorHandler(model-switch pre-compaction) + Store(ContextManager Vec)
- **OpenHands** — EventReactiveLoop + ContextBoundary(pipeline of 11) + StuckDetector(5 patterns) + ApprovalGate(RiskBased) + SubAgentSpawner(single delegation pair) + Store(append-only EventStream + View)
- **n8n** — DelegatedLoop + ToolRegistry(n8n nodes via $fromAI) + ContextBoundary(CountWindow) + ApprovalGate(HITL gating) + Store(external DB + EngineRequest protocol)
- **Aider** — PipelineLoop + ContextAssembler(8-segment ChatChunks) + ContextBoundary(background summarization) + Store(done_messages + cur_messages), no ToolRegistry
- **CrewAI** — DelegatedLoop(dual-mode) + PeerGroupOrchestrator(sequential/hierarchical Crews) + SubAgentSpawner(DelegateWorkTool) + ContextBoundary(reactive 85% summarization) + Store(accumulated messages + long-term memory)
- **Letta** — EventReactiveLoop(heartbeat) + PeerGroupOrchestrator(round-robin/dynamic/supervisor/sleeptime) + SharedStateStore(shared memory blocks) + ContextBoundary(5 summarization modes) + Store(memory blocks in DB, rendered into system prompt)
- **Open Deep Research** — SupervisorPattern with DirectLoop researchers + ContextBoundary(ArchitecturalIsolation) + ValueFunction(coverage via think_tool) + Store(3 isolated TypedDicts)
- **Moatless** — TreeSearchLoop + ValueFunction(per-node LLM scoring + 14 UCT components) + StuckDetector(duplicate detection) + Store(per-node deep-copied FileContext)
- **DGM** — EvolutionaryLoop + ValueFunction(SWE-bench fitness) + ErrorHandler(Docker isolation) + Store(archive with lineage chains of patch files)
- **PaperQA2** — DirectLoop + ContextBoundary(ArchitecturalIsolation via short conversations) + [RCS compression pipeline](../research/concepts/progressive-compression/_index.md) + ValueFunction(status-string coverage)
- **STORM** — PipelineLoop + SubAgentSpawner(parallel conversations per persona) + ContextBoundary(per-perspective isolation, 2500 word cap) + Store(StormInformationTable)
- **dmux** — EnvironmentMultiplexer(11 agent CLIs in git worktrees) + SharedStateStore(git repo as shared artifact) + ValueFunction(LLM-based terminal status detection)
- **Voicetree** — SubAgentSpawner(MCP-driven graph spawning) + EnvironmentMultiplexer(agent-agnostic terminals) + SharedStateStore(graph nodes with semantic search) + AgentLifecycleManager(spawn/wait/send/list/close via MCP)
- **OpenClaw** — DelegatedLoop(Pi SDK) + AgentLifecycleManager(list/kill/steer subagents) + ErrorHandler(4-layer recovery) + HookSystem(lifecycle hooks) + Store(mutable JSONL transcript)
