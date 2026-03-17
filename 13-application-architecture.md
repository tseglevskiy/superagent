# Application Architecture — Lightweight Python Implementation

## Design Principles

1. **Functions over classes.** A block is a function with a typed signature, not an abstract base class with 15 methods.
2. **Protocols over inheritance.** Python's `typing.Protocol` for structural typing — if it has the right methods, it fits.
3. **Dataclasses over ORMs.** Plain `@dataclass` for state. YAML/JSON files on disk. SQLite when we need queries.
4. **asyncio for concurrency.** Background consolidation, parallel tool calls, shadow mode — all async.
5. **Zero frameworks.** No LangChain, no LangGraph, no FastAPI at the core. Plain Python. Frameworks as optional adapters on the edges.

The entire core should fit in ~2,000 lines. Everything beyond that is blocks, tools, and domain knowledge.

---

## The Core: Five Files

### 1. `engine.py` — State Machine with Reducer (~200 lines)

The heart.
NOT a while loop around an LLM call.
A reducer pattern: all events go through one queue, processed one at a time, with immutable state.

**State is small and immutable — a pointer, not a copy:**

```python
@dataclass(frozen=True)
class AgentState:
    """~100 bytes. A projection over the append-only log, not a copy of it."""
    phase: str              # IDLE, THINKING, EXECUTING, WAITING, CONSOLIDATING, etc.
    domain: str | None      # active domain
    plan_cursor: str | None # which FocusChain node is active
    history_offset: int     # pointer into the append-only log
    blocks_version: int     # which snapshot of working memory
    lockfile_hash: str      # which lockfile is active
    step_count: int
    token_usage: int
```

**The reducer — a pure function with no side effects:**

```python
def reduce(state: AgentState, event: Event) -> tuple[AgentState, list[Effect]]:
    """Pure function: old state + event → new state + deferred side effects.
    State is NEVER mutated. Effects are NEVER executed inside the reducer."""

    match event.type:
        case "user_message":
            return (
                replace(state, phase="THINKING", step_count=state.step_count + 1),
                [Effect("call_llm", compile_context(state, event.payload))]
            )

        case "llm_response" if event.payload.has_code:
            return (
                replace(state, phase="EXECUTING"),
                [Effect("execute_code", event.payload.code)]
            )

        case "llm_response":
            return (
                replace(state, phase="IDLE"),
                [Effect("display", event.payload.text),
                 Effect("emit", "step_complete")]
            )

        case "code_result":
            new_state = replace(state,
                phase="THINKING",
                history_offset=state.history_offset + 1,
                token_usage=state.token_usage + event.payload.tokens)
            if state.step_count >= MAX_STEPS:
                return (replace(new_state, phase="IDLE"), [Effect("emit", "session_complete")])
            return (new_state, [Effect("call_llm", compile_context_at(new_state))])

        case "tool_result":
            return (
                replace(state, history_offset=state.history_offset + 1, phase="THINKING"),
                [Effect("call_llm", compile_context_at(state))]
            )

        case "block_updated":
            return (replace(state, blocks_version=event.payload.version), [])

        case "timer_consolidation":
            return (replace(state, phase="CONSOLIDATING"),
                    [Effect("run_consolidation", state.domain)])

        case "child_returned":
            return (
                replace(state, history_offset=state.history_offset + 1, phase="THINKING"),
                [Effect("call_llm", compile_context_at(state))]
            )

        case "context_overflow":
            return (replace(state, phase="COMPRESSING"),
                    [Effect("compress_context", state)])

        case _:
            return (state, [])
```

**The queue consumer — executes effects, feeds results back as events:**

```python
async def run_agent(llm, executor, store, bus):
    queue: asyncio.Queue[Event] = asyncio.Queue()
    state = AgentState.initial()
    log = AppendLog("~/.superagent/sessions/current.jsonl")

    # Event sources push to the ONE queue
    asyncio.create_task(user_input_source(queue))
    asyncio.create_task(timer_source(queue))
    asyncio.create_task(child_result_source(queue))

    while True:
        event = await queue.get()
        log.append(event)                              # append-only, never modified
        new_state, effects = reduce(state, event)      # pure function, no I/O

        for effect in effects:
            match effect.type:
                case "call_llm":
                    resp = await llm.call(effect.payload)
                    queue.put_nowait(Event("llm_response", resp))
                case "execute_code":
                    result = await executor.run(effect.payload)
                    queue.put_nowait(Event("code_result", result))
                case "display":
                    print(effect.payload)
                case "emit":
                    bus.emit(effect.payload, new_state)
                case "run_consolidation":
                    asyncio.create_task(consolidate(effect.payload, queue))
                case "compress_context":
                    asyncio.create_task(compress(effect.payload, queue))

        state = new_state
```

**No races.** One queue, one consumer, events processed strictly sequentially.
State is immutable — the reducer creates a new one via `replace()`.

**No history copying.** State is ~100 bytes (ints and strings).
History is an append-only log on disk, referenced by offset.

**Pure reducer = trivially testable.** Feed events, check output states and effects.
No mocks needed for the reducer itself.

**"Loop types" are transition rules, not separate classes:**

A DirectLoop is: `user_message → THINKING → llm_response → EXECUTING → code_result → THINKING → ... → IDLE`
A SupervisorPattern is: `user_message → THINKING → llm_response → SPAWNING (x5) → child_returned (x5) → THINKING → IDLE`
A Pipeline is: `user_message → EXECUTING(stage1) → tool_result → EXECUTING(stage2) → ... → IDLE`

Same reducer, different match arms activated depending on the lockfile configuration.

### 2. `memory.py` — Working Memory + Knowledge Store (~400 lines)

```python
@dataclass
class Block:
    label: str
    value: str
    limit: int = 20_000
    description: str = ""
    read_only: bool = False

    @property
    def chars_remaining(self) -> int:
        return self.limit - len(self.value)

class WorkingMemory:
    """Letta-style blocks compiled into the system prompt."""
    blocks: dict[str, Block]

    def compile(self) -> list[Message]:
        """Render blocks as XML with metadata."""
        xml = "<memory_blocks>\n"
        for b in self.blocks.values():
            xml += f"<{b.label}>\n"
            xml += f"  <description>{b.description}</description>\n"
            xml += f"  <metadata>chars={len(b.value)}/{b.limit}</metadata>\n"
            xml += f"  <value>{b.value}</value>\n"
            xml += f"</{b.label}>\n"
        xml += "</memory_blocks>"
        return [system_message(xml)]

    def update_block(self, label: str, value: str):
        block = self.blocks[label]
        if len(value) > block.limit:
            raise CapacityError(label, len(value), block.limit)
        block.value = value


class KnowledgeStore:
    """The hierarchical persistent store. Files on disk + SQLite index."""

    def __init__(self, root: Path):
        self.root = root
        self.index = Index(root / "index.db")  # semantic + BM25 + links

    def add_observation(self, domain: str, obs: Observation) -> str:
        """ADD operation. Returns artifact ID."""
        domain_dir = self.root / "domains" / domain / "observations"
        domain_dir.mkdir(parents=True, exist_ok=True)
        path = domain_dir / f"{obs.timestamp}-{obs.slug}.yaml"
        path.write_text(yaml.dump(asdict(obs)))
        self.index.add(obs.id, obs.content, domain=domain, level="observation")
        self._check_capacity(domain, "observations")
        return obs.id

    def retrieve(self, query: str, domain: str | None, top_k: int = 5) -> list[Artifact]:
        """RETRIEVE operation. Domain-scoped at bottom, cross-domain at top."""
        results = self.index.search(query, domain=domain, top_k=top_k)
        # A-MEM style: follow links one hop
        expanded = []
        for r in results:
            expanded.append(r)
            for link_id in r.links:
                linked = self.index.get(link_id)
                if linked and linked not in expanded:
                    expanded.append(linked)
        return expanded[:top_k]

    def _check_capacity(self, domain: str, level: str):
        """Trigger consolidation when capacity exceeded."""
        count = self.index.count(domain=domain, level=level)
        cap = self.config.capacity(domain, level)
        if count > cap:
            self.bus.emit("consolidation_needed", ConsolidationSignal(domain, level))
```

### 3. `tools.py` — Tool Registry (~150 lines)

```python
@dataclass
class Tool:
    name: str
    description: str
    handler: Callable  # async (args, state, bus) -> result
    schema: dict       # JSON Schema for parameters
    parallel_safe: bool = False
    approval_required: bool = False

class ToolRegistry:
    """Register, discover, dispatch tools."""
    _tools: dict[str, Tool]
    _search_index: Index | None  # for deferred/retrieval-based discovery

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def available(self, state: LoopState) -> list[Tool]:
        """Return tools available for this step.
        Could be all tools, or retrieval-based subset."""
        if self._search_index and len(self._tools) > 20:
            # RAG-MCP pattern: retrieve relevant tools, not all
            return self._search_relevant(state.last_user_message)
        return list(self._tools.values())

    async def dispatch(self, action: ToolCall, state: LoopState, bus: EventBus) -> str:
        tool = self._tools[action.name]
        bus.emit("tool_start", ToolSignal(action))
        try:
            result = await tool.handler(action.args, state, bus)
            bus.emit("tool_success", ToolSignal(action, result))
            return result
        except Exception as e:
            bus.emit("tool_error", ToolSignal(action, error=e))
            return f"Error: {e}"
```

### 4. `bus.py` — Event Bus + Signals (~100 lines)

```python
class EventBus:
    """Typed pub/sub. The glue between everything."""
    _handlers: dict[str, list[Callable]]

    def on(self, event: str, handler: Callable):
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, data: Any):
        for handler in self._handlers.get(event, []):
            # Fire-and-forget for instant tier, queued for fast/background
            if getattr(handler, '_background', False):
                self._background_queue.put_nowait((handler, data))
            else:
                handler(data)

    async def run_background(self):
        """Process background tasks during idle."""
        while True:
            handler, data = await self._background_queue.get()
            await handler(data)
```

The event bus is how continuous learning works:

```python
# Instant tier: utility scores update on every tool call
bus.on("tool_success", lambda sig: store.index.bump_utility(sig.tool_name))
bus.on("tool_error", lambda sig: store.index.decay_utility(sig.tool_name))

# Fast tier: pattern detection within session
bus.on("step_complete", detect_stuck_patterns)
bus.on("step_complete", detect_context_pressure)

# Background tier: consolidation during idle
@background
async def consolidate_on_idle(sig):
    await run_predict_calibrate(store, sig.domain)
    await run_gepa_optimization(store, sig.domain)

bus.on("idle_detected", consolidate_on_idle)
bus.on("consolidation_needed", run_consolidation)
```

### 5. `llm.py` — LLM Client (~150 lines)

```python
class LLMClient(Protocol):
    """Provider-normalized interface. Implementations for Anthropic, OpenAI, Ollama."""

    async def call(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse: ...

class AnthropicClient:
    """Anthropic implementation with streaming + cache breakpoints."""
    async def call(self, messages, tools=None, temperature=0.0):
        response = await self.client.messages.create(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            stream=True,
        )
        return await self._collect_stream(response)

class OllamaClient:
    """Local Ollama for testing (Tier 3 E2E smoke)."""
    async def call(self, messages, tools=None, temperature=0.0):
        response = await aiohttp.post(f"{self.url}/api/chat", json={
            "model": self.model,
            "messages": messages,
            "tools": tools,
        })
        return LLMResponse.from_ollama(await response.json())
```

---

## Blocks as Functions

Every Layer 1 block from doc 01 is a FUNCTION, not a class:

```python
# Context boundary — a function: (state, memory) -> state
async def token_threshold(threshold: float = 0.75):
    async def boundary(state: LoopState, memory: WorkingMemory) -> LoopState:
        if state.token_usage / state.token_limit > threshold:
            summary = await summarize(state.history, memory)
            state.history = [summary] + state.history[-3:]
        return state
    return boundary

# Stuck detector — a function: (state) -> str | None
def repetition_detector(window: int = 5):
    def detect(state: LoopState) -> str | None:
        recent = state.history[-window:]
        if len(set(str(m) for m in recent)) < 2:
            return "You are repeating yourself. Try a different approach."
        return None
    return detect

# Approval gate — a function: (tool_call) -> Allow | Deny | AskHuman
def pattern_match_gate(patterns: dict[str, str]):
    def gate(call: ToolCall) -> ApprovalResult:
        for pattern, action in patterns.items():
            if fnmatch(call.name, pattern):
                return ApprovalResult(action)
        return ApprovalResult("allow")
    return gate
```

Blocks compose via `LoopConfig`:

```python
config = LoopConfig(
    context_boundary=token_threshold(0.75),
    stuck_detector=repetition_detector(window=5),
    approval_gate=pattern_match_gate({"write_*": "ask", "read_*": "allow"}),
    focus_chain=FocusChain(),
)
```

No inheritance.
No abstract base classes.
No registration.
If it has the right signature, it works.

---

## SubAgent Spawning

A child agent is a SEPARATE `run_agent` with its own queue, its own state, and its own reducer.
The parent emits a `spawn_child` effect; the effect executor starts the child as an async task.
When the child reaches IDLE with a final result, it pushes a `child_returned` event to the parent's queue.

```python
async def spawn_subagent(
    task: str,
    inherit: str,  # "none" | "summary" | "full" | "blocks" | "selective"
    parent_state: AgentState,
    parent_memory: WorkingMemory,
    parent_queue: asyncio.Queue,
) -> None:
    """Start a child agent. Result comes back as a child_returned event."""

    # Prepare child's context based on inheritance mode
    if inherit == "none":
        child_memory = WorkingMemory(blocks={"task": Block("task", task)})
        child_offset = 0
    elif inherit == "blocks":
        child_memory = parent_memory  # shared by reference
        child_offset = 0
    elif inherit == "full":
        child_memory = deepcopy(parent_memory)
        child_offset = parent_state.history_offset  # start from parent's position
    elif inherit == "summary":
        summary = await summarize_for_handoff(parent_state, task)
        child_memory = WorkingMemory(blocks={"context": Block("context", summary)})
        child_offset = 0

    # Child has its own queue, state, and reducer
    child_queue: asyncio.Queue = asyncio.Queue()
    child_queue.put_nowait(Event("user_message", task))

    async def child_loop():
        child_state = AgentState(phase="IDLE", history_offset=child_offset, ...)
        # ... same run_agent pattern but with child_queue
        # When child reaches IDLE with result:
        parent_queue.put_nowait(Event("child_returned", result))

    asyncio.create_task(child_loop())
```

Context folding happens naturally: the child's entire work (search results, code execution, debugging) stays in the child's queue.
The parent sees only the `child_returned` event with the compressed result.

---

## The Knowledge Store on Disk

```
~/.superagent/
  config.yaml                    # global config: LLM providers, capacity limits
  lockfiles/
    current.lock                 # active configuration
    *.lock                       # history for rollback
  knowledge/
    shared/
      principles/                # cross-domain (Level N)
    domains/
      statistics/
        profile.yaml             # DomainProfile
        observations/*.yaml      # Layer 0
        patterns/                # Layer 1 — versioned dirs
          sql_date_filter/
            1.0.0/
              tool.py
              manifest.yaml
        concepts/                # Layer 2+ — versioned dirs
      coding/
        ...
    index.db                     # SQLite: embeddings + BM25 + links + metadata
  sessions/
    *.jsonl                      # session history (one file per session)
  traces/
    *.yaml                       # recorded session traces for replay testing
```

Everything is human-readable files.
`git init` in `~/.superagent/` gives you version control for free.
`ls knowledge/domains/` shows you what the agent knows.
`cat knowledge/domains/statistics/patterns/sql_date_filter/1.0.0/tool.py` shows you a specific pattern.

---

## The Lockfile

```yaml
# current.lock — resolved 2026-03-17T08:00:00Z
# The running agent is completely defined by this file.

llm: claude-sonnet-4
embedding: text-embedding-3-small

blocks:
  context_boundary: token_threshold/0.2.0
  stuck_detector: repetition/1.0.0
  approval_gate: pattern_match/0.1.0
  focus_chain: tree_plan/0.3.0
  error_handler: retry_with_fallback/1.0.0

tools:
  - bash/1.0.0
  - file_edit/1.0.0
  - web_search/2.1.0
  - memory_tools/1.0.0    # core_memory_append, core_memory_replace, etc.
  - plan_tools/0.3.0      # plan_update, compress_subtask
  - context_tools/0.1.0   # spawn_subagent, clone_self, compact_context

domains:
  statistics:
    overlay:
      tools: [sql_query/3.2.0]
      context_boundary: research_boundary/0.2.0
    composition: direct_loop_with_sql
  coding:
    overlay:
      tools: [test_runner/1.0.0]
    composition: direct_loop
```

Change one line → new candidate lockfile → admission → shadow → promotion.

---

## Startup

```python
async def main():
    bus = EventBus()
    store = KnowledgeStore(Path("~/.superagent/knowledge"))
    lockfile = Lockfile.load("~/.superagent/lockfiles/current.lock")
    llm = AnthropicClient(lockfile.llm)
    executor = CodeExecutor(store, bus)

    # Wire continuous learning handlers to the bus
    wire_instant_tier(bus, store)       # utility scores, trust scores
    wire_fast_tier(bus, store)          # pattern detection, candidate creation
    wire_background_tier(bus, store)    # consolidation, GEPA, reflection

    # Start the agent — a single queue consumer, not a loop
    await run_agent(llm, executor, store, bus)
```

Everything is event-driven from this point.
`run_agent` consumes events from the queue.
User input, timer events, child results — all enter the same queue.
The reducer processes them one at a time.
No races.
No separate "main loop" and "background workers" — they are all just event sources pushing to the same queue.

---

## Code-as-Action and Code-as-Knowledge

The agent communicates via Python code, not JSON tool calls (smolagents CodeAgent pattern).
Knowledge stored as code means retrieval gives the agent functions it can call directly.

### What the LLM Sees

The context window has two paired sections per domain, plus general-purpose tools:

```
System prompt:
  [working memory blocks WITH their attached functions]
    <schema_knowledge>
      <value>
        Table events: id, user_id, timestamp (partitioned by day)
        Table users: id, email, region_id
      </value>
      <functions>
        async def sql_date_filter(table, start, end) -> DataFrame:
            """Always filter by date range for temporal tables."""
        async def join_users_regions(events_df) -> DataFrame:
            """Join events with users and regions tables."""
      </functions>
    </schema_knowledge>

  [general-purpose functions]
    async def bash(command: str) -> str: ...
    async def file_edit(path, old, new) -> str: ...
    async def memory_update(label, old, new): ...
    async def plan_complete(node, summary): ...
    async def spawn_subagent(task, inherit="blocks") -> str: ...
    async def inspect_function(name) -> str: ...
```

Declarative knowledge and procedural knowledge travel TOGETHER.
When `schema_knowledge` is loaded (because the domain is "statistics"), its functions are loaded too.
The agent does not separately retrieve them — they come with the block.

### Three Function Tiers

**Block-attached functions** — travel with their memory block.
When the block is in context, these are automatically visible.
`schema_knowledge` block → `sql_date_filter`, `join_users_regions`.
This is how human knowledge works: when you know the database schema, you ALSO know the query patterns.

**General-purpose functions** — always available regardless of domain.
`bash`, `file_edit`, `memory_update`, `plan_complete`, `spawn_subagent`, `inspect_function`.
Like Python builtins.

**On-demand functions** — NOT in context until the agent requests them.
"I need a CSV parser" → the agent calls `knowledge.search("csv parsing")` → gets function signatures.
These are deeper library knowledge, retrieved only when needed.

### Functions Are Not Black Boxes

The agent normally sees only the signature + docstring (saves tokens).
But it can request the full implementation at any time:

```python
# Agent writes this when it needs to understand how a function works
source = await inspect_function("sql_date_filter")
# Now the full implementation is visible in the tool result
```

This is like a programmer using `ctrl+click` to see source code.
Knowledge is not a black box — it is accessible on demand but not always in context.

### Knowledge Artifacts Have Two Parts

```
knowledge/domains/statistics/patterns/sql_date_filter/1.0.0/
  manifest.yaml        # name, version, attached_to_block: schema_knowledge
  tool.py              # full implementation
  signature.py         # just the signature + docstring (what the LLM sees)
```

The `attached_to_block` field links procedural to declarative knowledge.
Loading a block automatically loads its attached function signatures.

### DomainProfile Pairs Blocks with Functions

```yaml
name: "statistics"
memory_blocks:
  - label: "schema_knowledge"
    value: "Table events: id, user_id, timestamp..."
    functions:                    # functions travel with the block
      - sql_date_filter/1.1.0
      - join_users_regions/1.0.0
  - label: "query_patterns"
    value: "For daily stats, GROUP BY date..."
    functions:
      - daily_active_users/1.0.0
      - retention_cohort/0.2.0
```

### The Learning Loop for Code Knowledge

When the agent writes code that works:
1. The code is ALREADY a Python function
2. Extract it, add type hints and docstring → it IS a Tool artifact
3. Determine which memory block it is associated with → set `attached_to_block`
4. Apply predict-calibrate: is this genuinely new, or a variant of an existing function?
5. If new: enters admission pipeline as a candidate

The agent's working code becomes tomorrow's reusable function.
No translation step.
This is Voyager's skill library, but in Python instead of JavaScript, and with block attachment instead of standalone retrieval.

---

## What This Is NOT

- **NOT a framework.** No plugin API. No extension points designed upfront. If you need to change behavior, edit the function.
- **NOT microservices.** Everything runs in one process. Background tasks are async coroutines, not separate services.
- **NOT a database application.** SQLite for the index, YAML files for everything else. No PostgreSQL, no Redis, no Docker required for the core.
- **NOT enterprise architecture.** No dependency injection container. No service locator. No abstract factories. Python's duck typing IS the DI.

The entire core (engine + memory + tools + bus + llm) is ~1,000 lines.
Blocks are small functions — 10-50 lines each.
The Knowledge Store is files on disk with a SQLite index.
The lockfile is a YAML file.

Everything can be changed by editing a function.
Nothing requires understanding an inheritance hierarchy.
The Lego property comes from function composition, not from OOP polymorphism.

---

## The Minimum Viable Version

Day 1 — what we build first:

1. `engine.py` with `reduce()` + `run_agent()` — the queue consumer with basic transitions
2. `memory.py` with `WorkingMemory` — blocks compiled into system prompt
3. `tools.py` with basic tools — bash, file_edit, web_search
4. `llm.py` with Anthropic client
5. `bus.py` with instant-tier signals only (utility scores)
6. A `current.lock` with hardcoded block versions

No Knowledge Store hierarchy yet.
No consolidation.
No reflection.
No shadow mode.
Just a working agent that records scorecards via events.

Then we add one feature at a time:
- Week 1: KnowledgeStore with observations (Layer 0)
- Week 2: Pattern consolidation (Layer 1) with capacity limits
- Week 3: Shadow mode for A/B testing lockfile candidates
- Week 4: Background consolidation during idle (timer events)
- Week 5: Reflection (consistency + validity checks)
- Week 6: Domain discovery and DomainProfiles
- ...

Each addition is a new event type + match arm in the reducer + effect handler.
The core five files do not change.
