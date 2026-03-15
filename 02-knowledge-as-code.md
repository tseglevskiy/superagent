# Knowledge as Executable Code

## The Thesis

The strongest insight from the research is that **knowledge should be executable code, not prompt text**.

Three projects prove this from different angles:

**Voyager** proved that an agent's accumulated knowledge can be a growing codebase of composable functions.
Every successful task produces a JavaScript function that is described in natural language, embedded in a vector store, and retrieved by semantic similarity for future tasks.
The 51st skill calls functions from the first 50.
The agent never explicitly "remembers" — it describes what it needs, and relevant skills surface automatically.
See [Voyager skill library](../research/products/voyager/02-skill-library.md) — the three properties that make it a genuine memory system: autonomous storage, semantic retrieval, and compositional reuse.

**smolagents** proved that when the agent writes Python as its action modality, the code it produces is already in the right format to be stored and reused.
The `CodeAgent` writes Python at each ReAct step, calling tools as plain function invocations.
The executor maintains a persistent `state` dictionary across all code executions — variables from step 1 are available in step 5.
See [smolagents code execution](../research/products/smolagents/02-agentic-loop.md) — code as action naturally produces reusable artifacts.

**OpenClaw** proved how to make this practical at scale.
52 bundled SKILL.md files with executable scripts, a six-root precedence merge, filesystem-watcher hot-reload, five-gate eligibility filtering, security scanning before execution, and a built-in skill-creator that teaches the agent to write new skills autonomously.
See [OpenClaw skills system](../research/products/openclaw/03-skills-system.md) — the most complete autonomous capability creation system among the coding agents studied.

### Why Code Beats Prompts

Prompt-based knowledge (SKILL.md instructions, AGENTS.md rules, .clinerules) is passive — it tells the LLM what to do in natural language.
The LLM must re-derive the solution from scratch every time.

Code-based knowledge is active — it encapsulates the solution as an executable function.
The LLM calls it, gets the result, and moves on.

The evidence from Voyager is definitive: `craftIronPickaxe` does not re-derive how to mine iron, smelt it, and craft the tool.
It calls `mineBlock`, `smeltItem`, and `craftItem` — skills learned earlier — and composes them.
See [Voyager compositionality](../research/products/voyager/02-skill-library.md) — each skill in the chain was generated with previous skills in its prompt context.

Prompt-based knowledge also has a fundamental scaling problem: the more you know, the more tokens it costs.
OpenClaw caps skills at 30,000 characters and 150 skills in the prompt.
See [OpenClaw prompt limits](../research/products/openclaw/03-skills-system.md).
Code-based knowledge scales differently: you can have 10,000 functions on disk, but only the 5 most relevant ones enter the prompt via semantic retrieval.
See [Voyager retrieve_skills](../research/products/voyager/02-skill-library.md) — top-k (default 5) results injected, regardless of total library size.

---

## Connection to the Lego Architecture

In [01-architecture-draft.md](01-architecture-draft.md), every architecture is a composition of Lego blocks: ContextAssembler, ToolRegistry, ContextBoundary, ApprovalGate, InspectorPipeline, StuckDetector, ValueFunction, ErrorHandler — wired by 6 loop controllers and composed via SubAgentSpawner, SupervisorPattern, PeerGroupOrchestrator, etc.

The central design principle is that every block communicates through the EventBus and reads/writes state through the Store.
No block directly calls another block.

**What if "knowledge" is not just tools — but entire Lego compositions?**

The agent could learn and store:
- A new **tool** — a function it wrote and tested
- A new **ContextBoundary strategy** — "when doing research tasks, use architectural isolation with parallel sub-agents"
- A new **StuckDetector pattern** — "when I see this error pattern, try this specific recovery"
- A new **ValueFunction** — "for code review tasks, score based on these criteria"
- A new **complete agent composition** — a SubAgentSpawner wiring diagram that connects blocks together for a specific purpose

Each of these is a Python module that plugs into the architecture's block interface.
The format is the same.
The storage is the same.
The retrieval is the same.

This is the key idea: **the Lego blocks from doc 01 are both the runtime architecture AND the knowledge schema**.

---

## Three Knowledge Artifact Types

### Type 1: Tool Artifacts

The simplest form: the agent writes a new tool and registers it with the ToolRegistry.

This is already proven by:
- [smolagents @tool decorator](../research/products/smolagents/03-tools-and-hub.md) — a function with type hints and docstring becomes a Tool instance automatically
- [OpenClaw api.registerTool](../research/products/openclaw/02-plugin-system-and-hooks.md) — plugins register tools at load time
- [Voyager skill library](../research/products/voyager/02-skill-library.md) — successful JavaScript functions stored and retrieved for future tasks

A tool artifact is:
- A Python function with typed inputs and outputs
- A natural-language description (for semantic retrieval)
- An embedding vector (for the index)
- Metadata: when created, from which task, success rate, dependencies

The creation flow follows Voyager's pattern: task succeeds → extract the reusable part → describe it → embed it → store it.
See [Voyager add_new_skill](../research/products/voyager/02-skill-library.md) — description generation, vector storage, file persistence, versioning.

### Type 2: Strategy Artifacts

A strategy artifact is a pluggable behavior for any Layer 1 block from doc 01.

Examples:
- A new ContextBoundary strategy: "when the conversation is about research, proactively compact at 50% instead of 75%"
- A new StuckDetector pattern: "when the agent calls the same API endpoint 3 times with 401 errors, suggest checking auth credentials before retrying"
- A new ErrorHandler rule: "when this specific error appears, try switching to a different model"
- A new ApprovalGate policy: "for this project, auto-approve all read-only filesystem operations"

The format is the same as a tool artifact: a Python module that implements the block's interface.
A ContextBoundary strategy is `(messages, config) -> (messages, metadata)`.
A StuckDetector pattern is `(recent_actions) -> Continue | Intervene(strategy)`.

The difference from a tool is scope: a tool adds a new action the agent can take.
A strategy changes how the agent behaves during its existing loop.

Inspiration:
- [OpenHands 11 pluggable condensers](../research/concepts/context-management/03-coding-agents.md) — each condenser is a composable strategy with the same interface
- [Goose 3-inspector pipeline](../research/concepts/agentic-loop/02-direct-loops.md) — each inspector is a pluggable check with the same signature
- [OpenClaw 23 plugin hook events](../research/products/openclaw/02-plugin-system-and-hooks.md) — each hook is a strategy that fires at a lifecycle point

### Type 3: Composition Artifacts

The most powerful form: the agent creates an entire wiring diagram that connects blocks into a new agent persona or capability.

A composition artifact describes:
- Which loop controller to use (DirectLoop, SupervisorPattern, PipelineLoop, etc.)
- Which blocks to wire in (which ContextBoundary, which ToolRegistry entries, which StuckDetector)
- How to configure each block
- What the entry point looks like (what input triggers this composition)
- How to test whether it works

This is analogous to:
- [OpenClaw skills](../research/products/openclaw/03-skills-system.md) — SKILL.md with frontmatter metadata, scripts, references, and a 6-step creation pipeline
- [Open Deep Research 3-tier architecture](../research/concepts/deep-research/03-open-deep-research.md) — a composition of SupervisorPattern + DirectLoop researchers + ArchitecturalIsolation + ValueFunction(coverage)
- [GPT-Researcher multi-agent mode](../research/concepts/deep-research/04-gpt-researcher.md) — a composition of PipelineLoop with 7 specialized stages
- [Codex CLI agent roles](../research/concepts/multi-agent/02-parent-child-delegation.md) — typed roles (default/explorer/worker/monitor) that configure a spawned agent with different tools, prompts, and permissions

A concrete example: the agent is asked "research X thoroughly."
It recognizes this needs a multi-phase pipeline.
It creates a composition artifact that wires:
- SupervisorPattern as the loop controller
- SubAgentSpawner with DirectLoop researchers
- ContextBoundary(ArchitecturalIsolation) — each researcher gets isolated state
- ValueFunction(coverage assessment via think_tool)
- A compression step before results cross the tier boundary

This composition is stored as a Python module, described in natural language, indexed.
Next time someone asks for research, the composition surfaces via semantic retrieval and the agent reuses it — possibly adapting it (different number of sub-agents, different search tools).

---

## The Knowledge Store

### Storage: Python Modules on Disk

Every artifact is a Python file in a knowledge directory.
Human-readable, git-trackable, editable.

```
knowledge/
  tools/
    web_scraper.py              # Tool artifact
    pdf_parser.py               # Tool artifact
  strategies/
    research_context_boundary.py # Strategy artifact
    api_error_recovery.py        # Strategy artifact
  compositions/
    deep_research_agent.py       # Composition artifact
    code_review_pipeline.py      # Composition artifact
  index.db                       # Semantic index (SQLite + vectors)
```

Inspired by:
- [OpenClaw skill directory structure](../research/products/openclaw/03-skills-system.md) — SKILL.md + scripts/ + references/ per skill
- [Voyager checkpoint directory](../research/products/voyager/01-architecture-overview.md) — skill/code/, skill/description/, skill/vectordb/
- [Codex CLI memory folder](../research/concepts/persistent-memory/codex-cli-two-phase-memory-pipeline-with-agent-driven-consolidation.md) — MEMORY.md, memory_summary.md, skills/, rollout_summaries/

### Index: Semantic + Keyword Hybrid

Every artifact has a natural-language description stored as an embedding in a vector index.

Retrieval is hybrid: semantic similarity + keyword matching + MMR diversity.

Inspired by:
- [OpenClaw memory-core hybrid search](../research/products/openclaw/05-persistent-memory.md) — vector + FTS5 + MMR + temporal decay
- [Voyager ChromaDB skill index](../research/products/voyager/02-skill-library.md) — LLM-generated descriptions embedded for similarity search

### Compositionality

New artifacts can import and extend previous ones.
A composition artifact can reference tool artifacts.
A strategy artifact can compose multiple simpler strategies.

This is Voyager's key property at a higher abstraction level.
See [Voyager compositionality](../research/products/voyager/02-skill-library.md) — `craftIronPickaxe` calls `mineBlock` and `smeltItem` learned earlier.
In our architecture, `deep_research_agent.py` imports `web_scraper.py` and `research_context_boundary.py` learned earlier.

### Hot-Reload

Inspired by [OpenClaw filesystem-watcher hot-reload](../research/products/openclaw/03-skills-system.md) — chokidar watches skill directories, debounced callback bumps version, next agent cycle picks up changes.
No restart required.

### Security Scanning

Before executing any artifact, static analysis checks for dangerous patterns.

Inspired by:
- [OpenClaw skill scanner](../research/products/openclaw/03-skills-system.md) — line rules (exec, eval, crypto mining) and source rules (exfiltration, obfuscation, env harvesting)
- [smolagents AST interpreter](../research/products/smolagents/04-security.md) — import allowlist, dangerous module blocklist, operation limits, dunder blocking

---

## The Learning Loop

How the agent creates new knowledge artifacts.

### Step 1: Task Succeeds

The agent completes a task.
The task may have involved novel behavior: a new tool the agent wrote inline, a new error recovery strategy it discovered, a new multi-agent composition it improvised.

### Step 2: Evaluate What Was Novel

After task completion, a lightweight evaluation step identifies what was reusable.

Inspired by:
- [Voyager CriticAgent](../research/products/voyager/04-iterative-code-and-critic.md) — evaluates task success from game state; only successful tasks produce skills
- [Codex CLI phase 1 extraction](../research/concepts/persistent-memory/codex-cli-two-phase-memory-pipeline-with-agent-driven-consolidation.md) — LLM reads past rollouts and extracts reusable knowledge with a minimum-signal gate
- [OpenClaw skill-creator](../research/products/openclaw/03-skills-system.md) — 6-step pipeline: understand, plan, initialize, edit, package, iterate

### Step 3: Extract the Reusable Part

The novel behavior is extracted into a Python module that conforms to the appropriate artifact type interface.

For tool artifacts, this is straightforward: the code the agent wrote inline becomes a standalone function.
See [smolagents @tool decorator](../research/products/smolagents/03-tools-and-hub.md) — type hints and docstring are sufficient to create a Tool.

For strategy artifacts, the agent must generalize: the specific error recovery it used becomes a pattern parameterized by the error type.

For composition artifacts, the agent must describe the wiring: which blocks, which configuration, what triggers it.

### Step 4: Describe and Index

Generate a natural-language description for semantic retrieval.

Inspired by:
- [Voyager SkillManager description generation](../research/products/voyager/02-skill-library.md) — sends function source to gpt-3.5-turbo, gets a 6-sentence description formatted as a function stub with comment
- [Codex CLI phase 2 consolidation](../research/concepts/persistent-memory/codex-cli-two-phase-memory-pipeline-with-agent-driven-consolidation.md) — a full agent rewrites and merges memory files, making editorial decisions about what is valuable

### Step 5: Store, Test, Hot-Reload

Write the artifact to disk.
Run the security scanner.
Update the semantic index.
The filesystem watcher picks up the change and makes it available.

---

## Example: Agent Creates a Deep Research SubAgent

The agent is asked: "Research the state of quantum error correction in 2025."

### First time — no relevant knowledge

1. The agent searches the knowledge store.
   No composition artifact matches "deep research" or "multi-source research."
2. The agent recognizes (from its system prompt or through reasoning) that this needs:
   - Multiple search queries (query decomposition)
   - Processing more source text than fits in context (progressive compression)
   - Knowing when to stop (coverage assessment)
3. The agent improvises a solution using the Lego blocks from doc 01:
   - Creates a SupervisorPattern loop
   - Spawns 3 SubAgent researchers via SubAgentSpawner, each with DirectLoop + web search tools
   - Uses ContextBoundary(ArchitecturalIsolation) — each researcher gets isolated state
   - Implements a simple coverage check: after each round, count sources found and assess gaps
4. The task succeeds.
5. The learning loop kicks in:
   - Evaluates: "this multi-agent research pattern was novel and worked"
   - Extracts: a composition artifact `deep_research_agent.py` that encodes the wiring
   - Describes: "Multi-phase research agent with supervisor-subagent pattern for thorough web research. Spawns parallel researchers, compresses findings, assesses coverage iteratively."
   - Stores and indexes it

### Second time — knowledge retrieved

1. The agent is asked: "Research the latest developments in CRISPR gene therapy."
2. The agent searches the knowledge store.
   `deep_research_agent.py` surfaces with high similarity.
3. The agent loads the composition and adapts it: different search queries, maybe different number of researchers.
4. The task completes faster and more reliably because the architecture was pre-built.

This is exactly what Voyager does at the Minecraft level — but applied to the agent's own architectural capabilities.
See [Voyager learn() loop](../research/products/voyager/01-architecture-overview.md) — outer loop proposes tasks, inner loop generates code, success stores skills, skills compound over time.

---

## How This Connects to Existing Knowledge Systems

| System | Knowledge Type | Storage | Retrieval | Compositionality |
|---|---|---|---|---|
| [Voyager skills](../research/products/voyager/02-skill-library.md) | Executable JS functions | ChromaDB + files | Semantic similarity | Yes — skills call earlier skills |
| [OpenClaw skills](../research/products/openclaw/03-skills-system.md) | SKILL.md + scripts | Disk + SQLite index | Eligibility filtering + always/on-demand | Partial — scripts can call each other |
| [Codex CLI memory](../research/concepts/persistent-memory/codex-cli-two-phase-memory-pipeline-with-agent-driven-consolidation.md) | MEMORY.md + skills | Disk (markdown) | Summary injection + shell search | No — skills are prompt text |
| [smolagents tools](../research/products/smolagents/03-tools-and-hub.md) | Python functions + Hub | Hub + local files | Registered at init | Yes — code can compose tools |
| [OpenClaw memory-core](../research/products/openclaw/05-persistent-memory.md) | Markdown files | SQLite + vectors + FTS5 | Hybrid search | No — files are text |
| **This proposal** | Python modules (tools, strategies, compositions) | Disk + SQLite + vectors | Hybrid semantic + keyword | Yes — compositions import tools and strategies |

The key difference: existing systems store either prompt text (OpenClaw skills, Codex CLI memory) or domain-specific code (Voyager JS functions, smolagents tools).
This proposal stores **architectural knowledge** — not just "how to do X" but "how to configure the agent to do X."
The knowledge schema is the Lego block interface from doc 01.
