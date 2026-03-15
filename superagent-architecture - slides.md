---
marp: true
paginate: true
theme: default
---

# The Superagent Architecture 🏗️
## A Self-Evolving AI Agent Built from Lego Blocks

<!-- This presentation explains the architecture from first principles. No prior knowledge of AI agent internals is assumed. Each concept is fully explained before it is used in a later slide. -->

---

# What Is an AI Agent? 🤖

An AI agent is a program that:
1. Receives a task from a human
2. Calls an LLM (like Claude or GPT) to reason about it
3. Uses tools (file editor, web search, shell commands) to act
4. Observes the results
5. Repeats steps 2-4 until the task is done

This loop is called the **agentic loop** or **ReAct pattern** (Reasoning + Acting).

<!-- Every modern AI coding assistant - Claude Code, Cursor, Cline, Codex - runs this loop. The differences are in how they configure each step. -->

---

# The Agentic Loop — Simplified 🔄

```
User says something
    → LLM thinks about it
    → LLM decides to use a tool
    → Tool runs, returns result
    → LLM thinks about the result
    → LLM decides: use another tool, or answer?
    → ... repeat ...
    → Final answer delivered
```

This is the same pattern used by every agent: ChatGPT with tools, Claude Code, GitHub Copilot, OpenHands, and 30+ other projects we studied.

<!-- The key insight from studying 28 agents: this loop is universal. What varies is how each step is configured, not the overall structure. -->

---

# The Problem with Today's Agents 😤

Every agent is a **monolith**.

- Cline has its own context management, its own tool system, its own approval flow
- Codex CLI has completely different ones
- OpenHands has yet another set
- They cannot share components

When you want a new capability (like deep research), you build an entirely new agent from scratch.

<!-- We studied 28 open-source agents and found they all use the same ~10 building blocks, just wired differently. This is the key observation that makes a Lego architecture possible. -->

---

# The Key Observation 💡

After studying 28 agents across 7 architectural patterns, we found:

**Every agent architecture decomposes into the same ~10 primitive blocks.**

What varies is how they are wired together.

A coding agent and a research agent use the same building blocks — just in different configurations.

<!-- This is not a hypothesis. We verified it by mapping every studied agent to the same set of blocks. The evidence is in our research corpus of 36 product deep-dives. -->

---

# 1. The Lego Architecture 🧱

---

## What Are the Blocks? 🧩

The ~10 building blocks that appear in every agent:

- **ContextAssembler** — builds the prompt the LLM sees each turn
- **ToolRegistry** — registers, discovers, and dispatches tools
- **ContextBoundary** — prevents context overflow (compression, truncation)
- **ApprovalGate** — decides if a tool call needs human approval
- **StuckDetector** — detects when the agent is repeating itself
- **ValueFunction** — scores how well the agent is doing
- **ErrorHandler** — retries, falls back to another model, recovers
- **FocusChain** — maintains a tree-structured plan of what to do

<!-- Each block has a simple interface. ContextBoundary, for example, takes messages in and returns fewer messages out. Any implementation that satisfies this interface can be plugged in. -->

---

## How Blocks Communicate 📡

One rule makes the Lego property work:

**Every block communicates through the EventBus and reads/writes state through the Store.**

No block directly calls another block.

This means:
- Swap any ContextBoundary strategy without touching the loop
- Add any StuckDetector to any loop type
- Nest any loop inside another loop

<!-- This is the same architecture that OpenHands uses — and it is the most principled system in our study. We are generalizing their approach. -->

---

## Six Loop Controllers 🔄

The blocks wire together into different loop patterns:

| Loop | How It Works | Used By |
|------|-------------|---------|
| **DirectLoop** | Simple while-loop | Cline, Codex CLI, Goose |
| **EventReactiveLoop** | Pub/sub event-driven | OpenHands, Letta |
| **DelegatedLoop** | Hands off to external SDK | OpenClaw, n8n |
| **PipelineLoop** | Stage 1 → Stage 2 → ... | GPT-Researcher, STORM |
| **TreeSearchLoop** | MCTS over solution tree | Moatless |
| **EvolutionaryLoop** | Mutate → Evaluate → Select | DGM, OpenEvolve |

<!-- The same blocks work in all six loops. A ContextBoundary that works in a DirectLoop also works in a TreeSearchLoop. That is the Lego property. -->

---

## Compositions — Combining Loops 🔗

Loops can be nested and combined:

- **SubAgentSpawner** — creates a child agent with its own loop
- **SupervisorPattern** — a supervisor delegates to multiple sub-agents
- **PeerGroupOrchestrator** — multiple agents as conversational equals
- **SharedStateStore** — agents coordinate through shared data

Example: A research agent is a SupervisorPattern with DirectLoop researchers inside it. The supervisor spawns 5 researchers in parallel, each running their own loop.

<!-- Open Deep Research is exactly this: a supervisor with parallel researcher sub-agents. We are not inventing new patterns — we are formalizing what already exists. -->

---

# 2. Knowledge as Executable Code 📦

---

## The Problem with Prompt-Based Knowledge 📝

Most agents store knowledge as text:
- SKILL.md files with instructions
- .clinerules with markdown rules
- AGENTS.md with guidelines

**Problem**: The LLM must re-derive the solution from scratch every time it reads the instructions.

<!-- This is like giving someone a recipe book vs giving them a kitchen with pre-made ingredients. The recipe requires work every time; the ingredients are ready to use. -->

---

## Code Beats Prompts 💻

**Voyager** (NeurIPS 2023) proved a better approach:

The agent writes JavaScript functions for Minecraft. Each successful task produces a reusable function. The 51st skill calls functions from the first 50.

`craftIronPickaxe` does not re-derive how to mine iron. It calls `mineBlock`, `smeltItem`, and `craftItem` — skills learned earlier.

**Knowledge as code scales differently**: 10,000 functions on disk, but only the 5 most relevant enter the prompt via semantic search.

<!-- Prompt-based knowledge has a scaling problem: the more you know, the more tokens it costs. Code-based knowledge has no such limit. -->

---

## Three Artifact Types 📁

Everything the agent learns is stored as one of three types:

| Type | What It Is | Example |
|------|-----------|---------|
| **Tool** | A function the agent can call | Web scraper, SQL query runner |
| **Strategy** | A pluggable behavior for a block | "Compress at 50% for research tasks" |
| **Composition** | A wiring diagram of blocks | "Deep research = SupervisorPattern + 3 researchers" |

Each is a Python module with typed interfaces, stored on disk, indexed for semantic search.

<!-- The key insight: the Lego blocks from the architecture ARE the knowledge schema. A new ContextBoundary strategy is both a runtime component and a piece of learned knowledge. -->

---

## The Knowledge Store 🗄️

```
knowledge/
  blocks/
    tools/
      web_scraper/1.0.0/tool.py
      web_scraper/2.0.0/tool.py
    strategies/
      research_context_boundary/0.1.0/strategy.py
    compositions/
      deep_research_agent/1.0.0/composition.py
  index.db    ← semantic search index
```

Every artifact has a natural-language description. Retrieval is hybrid: semantic similarity + keyword matching.

<!-- Multiple versions coexist on disk. Nothing is deleted. This is the foundation for safe evolution — you can always roll back. -->

---

## The Learning Loop 🔁

How the agent creates new knowledge:

1. **Task succeeds** — the agent completed something novel
2. **Evaluate novelty** — was there a new tool, strategy, or pattern?
3. **Extract** — turn the novel behavior into a reusable Python module
4. **Describe and index** — generate a description, embed it for search
5. **Store** — write to disk, security scan, hot-reload

Next time a similar task appears, the knowledge surfaces via semantic search.

<!-- This is exactly what Voyager does in Minecraft, but applied to the agent's own architectural capabilities. -->

---

# 3. Evolution and Safety 🛡️

---

## Why Evolution Needs Safety ⚠️

Every self-improving agent eventually breaks itself.

- **Godel Agent**: `exec()` + `setattr()` in live process. A bad mutation corrupts the runtime.
- **BabyAGI**: Unrestricted `exec()` with auto pip install. No validation.
- **Ouroboros**: Git-based, but if restart loads broken code, agent must fix itself.

**The faster the mutation cycle, the easier it is to break things.**

<!-- We need the speed of Godel Agent with the safety of DGM (which uses Docker isolation + benchmark gating). -->

---

## Immutable Versioned Blocks 📌

The solution from software engineering: **immutable versions with atomic deployment**.

- `web_scraper@1.0.0` never changes. Fix → publish `1.0.1`.
- Multiple versions coexist on disk.
- Rollback = point to the old version. Instant.

This is npm/cargo/pip for agent components.

<!-- The agent community has been reinventing package management — poorly. Ouroboros uses git without lockfiles. BabyAGI uses SQLite without dependency resolution. We use the real thing. -->

---

## The Lockfile ⚙️

A flat resolved list of exact versions = the running agent:

```yaml
# current.lock
web_scraper: 2.1.0
research_context_boundary: 0.2.1
deep_research_agent: 1.0.0
```

**Changing the lockfile is the ONLY way to activate a new version.**

Roll back = copy the previous lockfile. Both versions are still on disk.

<!-- This is the same as npm's package-lock.json. The entire agent configuration is defined by one file. -->

---

## Five Admission Gates 🚦

Before any change reaches the running agent:

| Gate | What It Catches |
|------|----------------|
| **Syntax/AST check** | Malformed code, missing imports |
| **Security scan** | Shell execution, eval, credential access |
| **Targeted tests** | Does this specific change work? |
| **Regression suite** | Did anything else break? |
| **Multi-model review** | 2-3 rival LLMs review the change |

Higher-risk changes require more gates.

<!-- Tool artifacts need gates 1-3. Composition artifacts need all five. The gates scale with risk. -->

---

## Rollback Primitives ↩️

Three levels of recovery:

1. **Instant rollback** — swap to previous lockfile. Everything is still on disk.
2. **Targeted revert** — downgrade just one block version.
3. **Auto-rollback** — circuit breaker: if health check fails N times, automatically restore previous lockfile.

<!-- Inspired by Kubernetes canary deployments and EloPhanto's automatic rollback on test failure. -->

---

# 4. Measurement 📊

---

## The 8-Metric Scorecard 📋

Every task automatically produces these metrics:

| Metric | What It Captures |
|--------|-----------------|
| **Completion** | Did the task finish? (0/1) |
| **User acceptance** | Accept / reject / abandon |
| **Steps** | Number of loop iterations |
| **Cost** | Total token cost in dollars |
| **Errors** | Number of tool failures |
| **Retries** | Number of recovery events |
| **Stuck events** | StuckDetector triggers |
| **Wall time** | Seconds from start to finish |

None require knowing what the task IS. A research task and a coding task both have these metrics.

<!-- This is the same insight behind SRE metrics: you don't need to understand HTTP to measure latency. -->

---

## Three Failure Causes 🔍

When something fails, there are exactly three possible causes:

1. **Block bug** — the code is wrong. The block fails consistently.
2. **Misapplication** — the block was used for the wrong task type.
3. **Composition mismatch** — blocks work individually but not together.

Each requires a different fix:
- Bug → publish a patch or roll back
- Misapplication → improve the description (so search retrieves it for the right tasks)
- Mismatch → fix the wiring between blocks

<!-- Without attribution, the agent cannot learn the right lesson from failure. This is why measurement matters. -->

---

# 5. Parallel Evaluation ⚖️

---

## Every Task Is an Experiment 🧪

Instead of running one agent configuration per task, run **two**:

- **Primary** — the current best. Serves the user.
- **Shadow** — a candidate. Runs in background. Produces measurement data only.

Over time, when the shadow consistently wins, it becomes the primary.

**The agent improves continuously from its own workload.**

<!-- Agent S proved this: running 3 parallel attempts and selecting the best with an LLM judge surpassed human performance on OSWorld. -->

---

## Three Modes ⚡

| Mode | What Happens | Cost |
|------|-------------|------|
| **Shadow** | Primary serves user. Shadow runs silently in background. | 2x (but prefix caching makes it closer to 1.2x) |
| **Race** | Both run. Return the better or faster result. | 2x |
| **Ensemble** | Both run. Synthesize the best parts of both. | 2x + synthesis |

Shadow mode has zero risk to user experience. The shadow can crash without affecting anyone.

<!-- SGLang's RadixAttention makes full context cloning nearly free at the KV cache level. The shared prefix is cached; only the diverging part costs tokens. -->

---

## The Promotion Pipeline 📈

1. Shadow runs alongside primary on every task
2. Scorecard + LLM judge compares results across N tasks
3. When shadow is statistically significantly better → promote
4. The shadow's lockfile becomes `current.lock`
5. A new shadow starts testing the next candidate

Borrowed from A/B testing: minimum sample size, significance threshold, per-category stratification, guardrails.

---

# 6. Testing Platform 🧪

---

## No Hand-Written Tests ✋

Traditional testing: developers write tests manually.

For a self-evolving agent, this does not work. The agent creates new components faster than humans can write tests.

**Our approach: the platform generates all tests automatically from the architecture.**

<!-- No studied project has a built-in testing platform that auto-generates tests from the architecture itself. Every project either hand-writes tests or skips them. -->

---

## Three Test Tiers 🏗️

| Tier | Source | Cost | Speed |
|------|--------|------|-------|
| **Contract tests** | Auto-generated from manifest.yaml | $0 | Milliseconds |
| **Integration replay** | Auto-recorded from successful tasks | $0 | Seconds-minutes |
| **E2E smoke** | Auto-generated, run with cheap local LLM | $0 (Ollama) | Minutes |

All three tiers must pass before any lockfile swap.

---

## Tier 1: Contract Tests 📝

Every block has a `manifest.yaml` declaring its interface.
Every composition declares what it expects from its dependencies.

The platform **auto-generates** tests that verify: does this block version still satisfy the interface that other blocks depend on?

**Zero test authoring.** The developer writes the manifest. The platform generates the tests.

<!-- Inspired by Pact consumer-driven contract testing from the microservices world. -->

---

## Tier 2: Integration Replay 🔁

The measurement system records every successful task: inputs, LLM calls, tool results, outputs, scorecard.

When a block version changes, the platform **replays recorded traces** against the new lockfile.

Same inputs through the new pipeline → same outputs? Scorecard still passes?

**Tests come from real usage, not from imagination.**

<!-- Inspired by VCR/Betamax for HTTP recording, and Jest snapshot tests. -->

---

## Tier 3: E2E Smoke with Ollama 🐵

A 14B model on local GPU (Qwen, Llama, Mistral) can verify:
- Does the loop terminate?
- Do blocks connect without errors?
- Does error recovery fire on tool failures?
- Does stuck detection intervene on repetition?

The cheap model makes **worse decisions** — which is the point. It stress-tests error handling, stuck detection, and recovery paths.

**Cost: $0. The GPU is already there.**

<!-- The cheap model is a chaos monkey. It makes the architecture prove it can handle real LLM behavior — including bad behavior — without crashing. -->

---

# 7. Context Flow 🌊

---

## The Empty Context Problem 😱

When an agent spawns a child to do a subtask:

**Claude Code**: the child gets ONLY the task prompt. No parent conversation.
**OpenHands**: the child gets events by position, not by relevance.

Result: the child agent is **dumb**. It does not know the business context, the user's goals, or what was already discussed.

<!-- This is the most common failure mode in multi-agent systems. The child produces technically correct but strategically wrong results because it lacks context. -->

---

## Five Inheritance Modes 🧬

When spawning a child, the parent chooses:

| Mode | What the child sees | Use case |
|------|-------------------|----------|
| **None** | Only the task prompt | Run 10 commands, check results |
| **Summary** | LLM-compressed summary | Background coding |
| **Full** | Complete conversation copy | Deep research (precision needs everything) |
| **Blocks** | Shared memory blocks (Letta pattern) | Long-running collaboration |
| **Selective** | LLM picks what to pass | Mixed |

<!-- GCC paper (arXiv:2508.00031) proved that BRANCH/MERGE for context forking improves SWE-bench by +13pp. SGLang makes full-copy nearly free via KV cache sharing. -->

---

## Agent Cloning 🧬

You have been discussing a topic for 20 minutes. Rich, nuanced understanding built up. Now you need deep research on a specific aspect.

**Clone the agent**: fork the full state, send the clone to research, get back a precisely targeted report.

The clone knows everything you discussed — it researches at the right depth, from the right angle.

The result: a report that is precisely targeted to YOUR question, not generic surface-level research.

<!-- This is GCC's BRANCH/MERGE pattern. BRANCH = full context copy. MERGE = the clone's report becomes a tool result in the parent's context. -->

---

## Tree-Structured Context Compression 🌳

Standard approach: kill the oldest messages first.

**Problem**: the oldest messages contain the GOALS and REQUIREMENTS.

Our approach: compress from the **leaves**, not the root.

```
1. Business analysis        ← NEVER compressed
   1.1 Gather requirements  ← summary after completion
   1.2 Implement changes    ← summary after completion
      1.2.1 Refactor auth   ← compressed to: "done, 3 files changed"
      1.2.2 Add endpoints   ← compressed to: "done, 5 new endpoints"
```

The ROOT stays untouched. Completed subtask details compress into summaries.

<!-- FoldAgent (arXiv:2510.11967) already implements this with RL-trained branch/fold, achieving 10x context reduction. HiAgent (ACL 2025) validates subgoal-as-compression-boundary with 2x success rate improvement. -->

---

## The Agent Chooses the Strategy 🧠

The agent picks the right context strategy based on the situation:

- "Code this while we keep talking" → **spawn with shared blocks**
- "Research this deeply" → **clone self** with full context
- "Subtask done, compress it" → **tree compression**
- "Run 10 build commands" → **spawn with empty context**
- "Context getting long, no plan tree" → **flat compression**

This is just... more tools in the ToolRegistry. The agent already decides which tools to call.

<!-- Sculptor (arXiv:2508.04664) proved 8 context-management tools work via zero-shot tool calling: +49.3pp on interference benchmarks. -->

---

# 8. Domain-Aware Knowledge 🏘️

---

## The Domain Problem 🗂️

An agent running for months works across many topics:
- Product coding
- Statistics and SQL
- Marketing materials
- Research papers

All knowledge in one flat pile → wrong tool retrieved for wrong task.

Each domain should develop its own expertise independently.

<!-- ExpeL (AAAI 2024) proved that different domains naturally develop different expertise types. HotpotQA benefited from abstract insights; ALFWorld benefited from retrieved trajectories. -->

---

## Domain Profiles 📋

A **DomainProfile** bundles everything for a domain:

```yaml
name: "statistics"
lockfile_overlay:
  sql_query_tool: 3.2.0
default_composition: direct_loop_with_sql_tools
knowledge_namespace: "statistics"
memory_blocks:
  - label: "schema_knowledge"
    value: "Table users has columns id, email..."
  - label: "query_patterns"
    value: "For daily stats, GROUP BY date..."
```

When spawning a subagent for statistics, it gets the domain's tools, knowledge, and strategies.

<!-- Nemori (arXiv:2508.03341) and A-MEM (NeurIPS 2025) prove that domains can be discovered autonomously via clustering, not just manually configured. -->

---

## Autonomous Domain Discovery 🔍

The agent discovers domains through clustering:

1. Every task is auto-classified (type, domain, complexity)
2. Over time, tasks cluster into natural domains
3. When a cluster stabilizes → auto-create a DomainProfile
4. Each domain evolves independently

The agent does not need to be told "you have a statistics domain." It discovers it.

<!-- Factory Signals discovered "branch switches" as a friction category via embedding clustering. The same mechanism discovers knowledge domains. -->

---

# 9. Mutation Operators 🧬

---

## Three Layers, Three Speeds ⚡

| Layer | What Changes | Mutation Tool | Testing | Risk |
|-------|-------------|---------------|---------|------|
| **Strategy** (prompts) | How the LLM reasons | GEPA, DSPy | Shadow mode | Low |
| **Tool** (code) | What the agent can do | DGM-style coding | Contract + E2E | Medium |
| **Composition** (architecture) | How blocks connect | ADAS, AFlow | Full regression | High |

Optimize in order: strategies first (cheap, fast, 5-20% gains), then tools, then compositions.

<!-- MASS (arXiv:2502.02533) confirms: "prompts are the dominant factor." But for tasks that need fundamentally different architectures, composition mutations are the only path. -->

---

## Strategy Mutation: GEPA 🏆

**GEPA** (ICLR 2026 Oral) is the primary optimizer:

- Reflects on full agent trajectories (reasoning + tool calls + results)
- Genetic algorithms + Pareto selection
- Outperforms all other optimizers (OPRO, EvoPrompt, TextGrad, MIPROv2)
- Produces **33% shorter** prompts that work **better**
- Integrated into DSPy

One tool that replaces an entire stack of optimizers.

<!-- AGENTIF (NeurIPS 2025): fewer than 30% of system prompt instructions are perfectly followed. Most prompt content is effectively ignored. GEPA optimizes for density, not volume. -->

---

## The SkillsBench Warning ⚠️

**Critical negative result** (arXiv:2602.12670):

"Self-generated Skills provide **zero benefit** on average. Curated Skills add 16.2 percentage points."

Models "cannot reliably author the procedural knowledge they benefit from consuming."

**Implication**: our Learning Loop MUST include quality validation. Multi-model review should gate ALL new artifacts, not just compositions.

<!-- This is the most sobering finding from the research. Self-improvement is possible, but self-authored knowledge needs a quality gate. -->

---

# 10. Putting It All Together 🎯

---

## The Full Flow 🔄

```
Task arrives
  → Knowledge Store retrieves relevant blocks + composition
  → Lockfile resolves exact versions
  → Loop controller wires blocks together
  → Agent executes (with all Layer 1 blocks active)
  → Scorecard recorded (8 metrics + full trace)
  → Learning Loop: novel behavior? → extract → version → store
  → Shadow mode: candidate lockfile runs in parallel
  → Promotion: when candidate wins → swap lockfile
  → Testing: contract + replay + E2E before any swap
```

<!-- Each step is independently pluggable. Any block can be swapped. Any loop controller can be used. Any testing tier can be added or removed. -->

---

## What Makes This Different 🌟

| Other Agents | Our Architecture |
|-------------|-----------------|
| Monolithic codebase | Composable Lego blocks |
| Knowledge as prompts | Knowledge as executable code |
| Fixed configuration | Versioned lockfiles with rollback |
| No self-measurement | 8-metric scorecard + attribution |
| Single execution | Shadow/race/ensemble parallel eval |
| Hand-written tests | Auto-generated three-tier testing |
| Flat context management | Tree-structured + agent-controlled |
| One-size-fits-all | Domain-aware with autonomous discovery |

---

## The Research Foundation 📚

This architecture is grounded in analysis of **36 open-source agent projects** and validated by **200+ recent papers**:

- FoldAgent validates tree compression (10x reduction)
- GEPA validates prompt optimization (ICLR 2026 Oral)
- Sculptor validates agent-controlled context (8 tools, +49pp)
- Block TestProvider validates record-and-replay testing
- ABC validates probabilistic contract testing
- A-MEM validates autonomous domain discovery (NeurIPS 2025)

Every architectural decision has a research precedent.

---

## What We Build Next 🚀

1. **Seed agent** — minimum viable DirectLoop with the core blocks
2. **Knowledge Store** — versioned artifacts with lockfile resolution
3. **Measurement** — scorecard collection from day one
4. **Shadow mode** — parallel evaluation from the first task
5. **Tree compression** — FocusChain block with plan-driven compression
6. **Domain discovery** — clustering over accumulated task categories
7. **Self-evolution** — GEPA for strategies, DGM-style for tools

The blocks compose independently. We build them one at a time.

---

# Questions? 💬

## Architecture Documents

- `01-architecture-draft.md` — Lego blocks and loop controllers
- `02-knowledge-as-code.md` — Artifact types and mutation operators
- `03-evolution-and-safety.md` — Versioning, lockfiles, admission gates
- `04-measurement.md` — Scorecard and attribution model
- `05-parallel-evaluation.md` — Shadow, race, ensemble modes
- `06-testing-platform.md` — Three-tier auto-generated testing
- `07-context-flow.md` — Five scenarios for context inheritance
- `08-research-synthesis.md` — 200 papers mapped to our architecture
