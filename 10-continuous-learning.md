# Continuous Learning — Not a Phase, the Steady State

## The Core Idea

Most self-improving systems treat learning as a separate phase: collect data, train offline, deploy, repeat.
Memory-R1, Mem-alpha, and MEM1 all follow this pattern — batch training of memory management policies.
DGM runs evolutionary loops for hours.
GEPA optimizes prompts in discrete runs.

Our architecture is different.
We already have the scorecard running on every task (doc 04), shadow mode running continuously (doc 05), and the admission pipeline evaluating every mutation (doc 03).
Every interaction already produces structured feedback.

**The insight: close the loop.
Every signal immediately creates a candidate for improvement.
Learning is not a phase — it is the steady state.**

---

## Every Signal Has a Target

Every external signal has a natural target for improvement:

| Signal | What Improves |
|---|---|
| User accepts result | This lockfile configuration gets +1 confidence |
| User rejects result | Attribution model identifies which block, that block gets flagged |
| User picks option A over B | The winning lockfile candidate gets promoted |
| Task completes in fewer steps | The Strategy artifacts used get higher utility scores |
| Tool call fails | Error pattern stored, ErrorHandler rule updated |
| Tool call succeeds | Tool artifact utility score refreshed |
| StuckDetector fires | The stuck pattern and recovery action stored as a Strategy candidate |
| Context overflow triggers | ContextBoundary strategy evaluated, better one promoted |
| Shadow produces better result | Shadow lockfile gains confidence toward promotion |
| Same task type repeats | Previous recordings retrieved, delta measured |
| Domain detected via clustering | DomainProfile created or updated |
| New topic in conversation | Episode boundary detected (Nemori), knowledge extracted |
| Idle time detected | Consolidation fires: GEPA optimization, domain discovery |

No signal is wasted.
Every interaction is training data.

---

## Three Learning Speeds

Not everything can be updated at the same speed.

### Instant (Within the Current Turn)

- Utility scores on accessed artifacts: refreshed on every access
- Trust scores: updated when a tool call succeeds or fails
- Usage profiles: incremented on every invocation
- FocusChain state: updated on every subtask completion

These are pure bookkeeping — no LLM calls, no evaluation, just incrementing counters and timestamps.
Cost: effectively zero.

**Critical property**: instant-tier updates modify only READ-SIDE METADATA.
They inform future retrieval and mutation decisions but do NOT change the running behavior.
Like database query statistics — they help the optimizer but do not change query results.
No safety concern.

### Fast (Between Turns, Within the Session)

- StuckDetector detected a new pattern → creates a candidate `stuck_detector@1.3.0`
- ContextBoundary was ineffective → creates a candidate `context_boundary_v2@0.4.0`
- User preferred option A over B → the winning lockfile gets a confidence bump toward promotion
- If A/B comparison is available: user preference immediately feeds the promotion pipeline

These require lightweight computation but not full evaluation cycles.

**Critical property**: fast-tier updates create CANDIDATE VERSIONS, not overwrites.
The candidates enter the admission pipeline (doc 03) but are NOT deployed until they pass all gates AND shadow testing.

### Background (Between Sessions, During Idle)

- GEPA optimization on Strategy artifacts using accumulated scorecard data
- Nemori predict-calibrate on new episodes to extract genuinely new knowledge
- Domain clustering over recent task categories
- Integration replay tests against candidate lockfiles
- Full benchmark evaluation of promising mutations
- RL policy update for memory management (when enough data accumulated)

These are expensive but happen when the agent is idle — like Letta's sleep-time compute (arXiv:2504.13171, 5x test-time compute reduction) and LightMem (arXiv:2510.18866, 117x token reduction).

**Critical property**: same as fast tier — creates candidate versions that enter the admission pipeline.

---

## Why Mutations Create Versions, Not Overwrites

The continuous learning loop does NOT modify the running system.
It creates candidate versions that go through the existing pipeline:

```
Signal arrives (user feedback, tool failure, stuck detection, etc.)
    → Instant tier: utility/trust METADATA updates (safe — read-only counters)
    → Fast tier: candidate mutation CREATED (new version of a block)
    → The candidate enters the admission pipeline (doc 03):
        syntax → security → tests → regression → review
    → If it passes: enters shadow mode (doc 05)
    → Shadow runs alongside primary on real tasks
    → When shadow statistically wins: lockfile swap (promotion)
```

The running lockfile is FROZEN during all of this.
Nothing in production changes until a candidate proves itself.

### Example: Deleting an Artifact

Scenario: the RL memory policy recommends DELETE for block X.

This does NOT delete block X from the running system.
Instead:
1. A **candidate lockfile** without block X is created
2. Tier 1 contract tests run — if a composition depends on X, the candidate is immediately rejected
3. OR: a new composition version that does not use X is also created, and BOTH the new lockfile + new composition enter shadow testing together
4. Shadow mode compares the agent with and without block X on real tasks
5. Only if the version without X performs at least as well: the lockfile swap happens

No oscillation.
No races.
No interference with the running system.

---

## Consistency Model: Resolved by Existing Architecture

The open question from the discussion: can the three speeds coexist without interference?

The answer: **yes, because the lockfile provides isolation.**

- The running system sees only the current lockfile — immutable during a session
- Instant-tier metadata updates are append-only counters — no conflict possible
- Fast-tier candidates are new version directories on disk — no conflict with running versions
- Background-tier candidates are the same — new versions, not overwrites

The only shared mutable state is the metadata (utility scores, trust scores, usage profiles).
These are read-side counters that guide FUTURE decisions.
Multiple writers can safely increment the same counter — worst case is a slightly stale read, which is acceptable for statistical metadata.

For safety: the admission pipeline (doc 03) is the serialization point.
Only one lockfile swap can happen at a time.
This is the same model as database write-ahead logging — many concurrent readers, serialized writers.

---

## The Biological Analogy

This mirrors how biological learning works:

| Biological | Our Architecture |
|---|---|
| Synaptic plasticity (instant) — every firing adjusts weights slightly | Utility/trust score updates on every signal |
| Short-term potentiation (fast) — repeated patterns strengthen within minutes | Within-session pattern detection, candidate creation |
| Long-term potentiation + sleep consolidation (background) — patterns consolidated, noise pruned | Idle consolidation: GEPA, predict-calibrate, domain discovery |
| Active forgetting during sleep | Utility-based temporal decay, RL-trained DELETE operations |

The key biological insight: **forgetting is active, not passive.**
The brain actively prunes connections during sleep.
Our utility-based temporal decay + RL-trained DELETE operations implement active forgetting.

---

## How the Learning Loop Changes

The Learning Loop from doc 02 currently describes a five-step extraction pipeline that runs after task success.
In the continuous model:

**Old model (batch):**
```
Task completes → evaluate novelty → extract → describe → store
```

**New model (continuous):**
```
ALWAYS running:
  - Instant: utility/trust scores update on every signal
  - Fast: patterns detected within session, candidates prepared
  - Background: consolidation, optimization, testing during idle

The "Learning Loop" is not a pipeline that fires on events.
It IS the architecture.
Learning is not a phase — it is the steady state.
```

The existing five steps (evaluate novelty → extract → describe → store → test) still exist — they describe what happens at the fast and background tiers.
But they are no longer triggered by "task completes" — they are triggered by ANY signal at the appropriate speed tier.

---

## Connection to Other Docs

- [Doc 02](02-knowledge-as-code.md) — the Learning Loop becomes continuous rather than event-triggered
- [Doc 03](03-evolution-and-safety.md) — the admission pipeline + lockfile swap are the serialization points that make continuous learning safe
- [Doc 04](04-measurement.md) — the scorecard provides the reward signal for all three tiers
- [Doc 05](05-parallel-evaluation.md) — shadow mode is the A/B testing layer for fast and background candidates
- [Doc 06](06-testing-platform.md) — all three test tiers run before any candidate is promoted
- [Doc 09](09-benchmarks-and-performance.md) — continuous learning produces the "performance as delta" growth curve that is our primary metric

---

## What Makes This Different from Existing Systems

| System | Learning Model | Our Continuous Model |
|---|---|---|
| **Letta** | Agent edits memory, no feedback on whether it helped | Every memory operation generates a utility signal; RL-trained policy learns from accumulated signals |
| **Codex CLI** | Extraction once per startup, consolidation once | Any signal at any time creates a candidate; consolidation runs during every idle period |
| **DGM** | Evolutionary loop runs for hours, best variant deployed | Every task is an evaluation; winners promoted via shadow mode |
| **Memory-R1** | Train policy offline, deploy as batch update | Candidates created continuously; promoted only when they prove themselves via A/B |
| **ECC** | Captures observations continuously, but `/evolve` is manual | Automatic: patterns → candidates → admission → shadow → promotion |
| **GEPA** | Discrete optimization runs with budget caps | GEPA runs during idle periods on accumulated data; results enter shadow as candidates |

The fundamental difference: every other system has an explicit boundary between "learning time" and "serving time."
Our system has no such boundary.
It is always learning and always serving.
The admission pipeline ensures that learning never disrupts serving.

---

## The Growth Curve

This directly enables the "performance as delta" metric from doc 09:

**Month 1**: Agent starts with baseline blocks.
Utility scores are neutral.
No domain profiles.
Strategies are generic.
Every task produces signals that create candidates.

**Month 2**: Utility scores have identified high-value artifacts.
Domain profiles have formed from task clustering.
Strategies have been GEPA-optimized during idle periods.
Stale artifacts have been deprioritized.
The agent handles familiar tasks in fewer steps.

**Month 3**: The RL memory policy has enough accumulated signals to outperform the heuristic.
Domain-specific compositions have crystallized from pattern detection.
The agent's cost per task is measurably lower than month 1.

The growth curve emerges naturally from continuous learning — not from periodic training runs.
The agent improves as long as it is running.

---

## Hierarchical Knowledge Consolidation

### How Human Learning Works

A human working across multiple domains (a project at work, family logistics, learning music, studying statistics) accumulates knowledge at multiple levels.
The process has a natural structure:

**Layer 0: Raw observations.**
"This SQL query returned wrong results."
"The user prefers bullet points over paragraphs."
"The test failed because of a missing import."
These are unprocessed signals — just things that happened.

**Layer 1: Patterns.**
After enough observations: "queries against this table often need a date filter."
"This user always wants concise output."
"Missing imports usually mean the file was recently refactored."
These are generalizations from repeated observations.

**Layer 2: Concepts.**
After enough patterns: "this database has temporal partitioning, always consider date ranges."
"This user values density over completeness — optimize for signal-to-noise."
"After refactoring, always run the import checker before committing."
These are actionable rules derived from patterns.

**Layer 3+: Higher-order concepts.**
After enough concepts accumulate, they generalize further — and this can continue to arbitrary depth:

- Level 3: "data engineering tasks require schema-awareness at every step"
- Level 4: "infrastructure work requires understanding the deployment model, not just the code"
- Level 5: "engineering decisions should consider operational constraints alongside correctness"
- Level N: increasingly abstract principles that shape how the agent APPROACHES entire domains

The number of levels is NOT fixed at four.
It is a tree that grows as deep as the knowledge requires.
A simple domain might have only two levels (observations and a few patterns).
A complex domain the agent has worked in for months might develop five or six levels of increasingly abstract understanding.

This is the same property as the FocusChain from doc 07: a tree with arbitrary depth, where each node can have children.
The knowledge hierarchy grows organically — the agent does not decide "now I will create a Level 4 concept."
It happens naturally when enough Level 3 concepts accumulate and consolidation pressure forces a generalization.

### Bounded Capacity at Every Layer

The critical property: **each layer has limited capacity.**

A human cannot hold 500 raw observations in working memory.
If consolidation does not happen — if observations are not generalized into patterns — the oldest observations are simply forgotten.

This is not a bug.
It is how learning works.
The pressure of limited capacity FORCES consolidation.
Without pressure, there is no reason to generalize.

**The same constraint must apply to our Knowledge Store.**

If the Tool artifact namespace for "statistics" grows to 500 tools, something is wrong.
Most of those tools should have been consolidated into higher-level patterns.
If the Strategy artifact namespace for "research" grows to 200 strategies, most should have been generalized into a few powerful compositions.

Capacity limits at each layer create consolidation pressure:
- Too many observations → MUST generalize into a pattern or forget
- Too many patterns → MUST abstract into a concept or prune
- Too many concepts → MUST form higher-order domain knowledge or simplify

### How This Maps to Our Architecture

The bottom two layers have concrete implementations.
Above that, the hierarchy is a tree of artifacts with arbitrary depth — each node is a generalization of its children.

| Layer | Our Architecture | Capacity Limit | Consolidation Mechanism |
|---|---|---|---|
| Raw observations | Scorecard metrics, tool call logs, session traces | Time-bounded (30 days default) | Background consolidation extracts patterns |
| Patterns | Strategy artifacts, StuckDetector rules, Tool artifacts | Per-domain cap (configurable) | GEPA optimization generalizes into fewer, better strategies |
| Concepts (level 2+) | Composition artifacts, generalized strategies, DomainProfiles | Per-domain cap per level (configurable) | When a level is full, its nodes are clustered and generalized into a parent node at the next level |
| Domain understanding | The top of whatever tree has grown for this domain | Implicitly small (generalizations get more abstract and fewer) | Formed only under consolidation pressure from below |

The key: there is no predetermined number of levels.
A new domain starts flat (observations only).
As the agent accumulates experience, levels emerge organically.
A domain the agent has worked in for 3 months might have 5 levels.
A domain touched once stays at 1 level.

### Consolidation as Upward Pressure

When a layer is full:

1. **The agent takes a break** — switches to a different domain or enters idle mode
2. **Background consolidation fires** (the sleep-time pattern):
   - Raw observations at Layer 0 are clustered and generalized into Layer 1 patterns
   - Patterns at Layer 1 that appear across multiple tasks are abstracted into Layer 2 concepts
   - Concepts at Layer 2 that consistently succeed are promoted into Layer 3 domain knowledge
3. **The agent returns to the domain** — and finds that individual observations are no longer needed, because the generalization now handles those cases

This is exactly what Nemori's Predict-Calibrate does at the observation→pattern boundary: predict what you should already know, extract only the genuinely new delta.
We need the same mechanism at EVERY boundary: pattern→concept, concept→higher-order.

### Generalizations Are Provisional

A generalization is not permanent truth.
It is a **hypothesis derived from observations** that must be continuously tested.

When the agent applies a generalization and it works: the generalization's utility score increases.
When the agent applies a generalization and it fails: the attribution model (doc 04) traces the failure back to the generalization.

Three possible outcomes after attribution:
1. **The generalization is still mostly correct** — the failure was an edge case. Record the exception.
2. **The generalization needs refinement** — the pattern was too broad. Create a more specific version.
3. **The generalization is wrong** — the observations it was based on were misleading. Deprecate it, fall back to the observations.

This is the same admission pipeline (doc 03) running in REVERSE: instead of "should this new version be promoted?" it asks "should this existing version be demoted?"

### Attribution Through the Hierarchy

When a task fails, the attribution model from doc 04 traces through the hierarchy:

```
Task failed
  → Which composition was used? → deep_research_agent@1.0.0
  → Which strategy within it failed? → research_context_boundary@0.2.1
  → What generalization does that strategy encode? → "compress at 50% for research tasks"
  → Was this generalization valid for THIS task? → No — this task needed full context
  → What observations led to this generalization? → 15 past research tasks where 50% worked
  → Were those observations representative? → They were all simple queries; this was complex
  → Fix: create a conditional strategy — 50% for simple, 80% for complex research
```

The attribution flows DOWN the hierarchy: task → composition → strategy → generalization → observations.
The fix flows UP: new observation → refined pattern → updated strategy → tested via shadow mode.

### The Hierarchy in the Knowledge Store

```
knowledge/
  domains/
    statistics/
      observations/       ← Layer 0: raw signals, time-bounded, max 100
      patterns/            ← Layer 1: strategy artifacts, max 20 per domain
      concepts/            ← Layer 2: composition artifacts, max 5 per domain
      domain_profile.yaml  ← Layer 3: the domain-level understanding
    research/
      observations/
      patterns/
      concepts/
      domain_profile.yaml
```

Capacity limits are configurable per domain.
When a layer exceeds its cap, consolidation is triggered:
- Below cap: new artifacts are added normally
- At cap: adding a new artifact triggers consolidation — merge, generalize, or prune to make room
- Over cap: forced consolidation — the oldest or lowest-utility artifacts are retired

### The Organizational Analogy

The knowledge hierarchy maps to something familiar: organizational structure.

A small company has a flat hierarchy — everyone does everything, knowledge is concrete and operational.
"Ship this order." "Fix this bug." "Call this customer."
Two or three levels at most.

As the company grows, the context expands — more customers, more products, more markets, more complexity.
The person who mastered the operational level generalizes: "these types of orders always need express shipping" becomes a PROCESS.
The person who mastered processes generalizes further: "our logistics strategy should prioritize speed over cost for enterprise customers" becomes a POLICY.
The person who mastered policy generalizes into vision: "we compete on service quality, not price" becomes STRATEGY.

Each level of the hierarchy corresponds to a level of knowledge abstraction:
- **Line worker** — knows the specific observations (this task, this tool, this error)
- **Team lead** — knows the patterns (this type of task usually needs this approach)
- **Manager** — knows the concepts (this domain works this way, these are the trade-offs)
- **Director** — knows the strategies (how to approach an entire class of problems)
- **VP/CEO** — knows the principles (what matters, what to optimize for, how to think about the business)

The number of levels grows with the SIZE OF THE CONTEXT being managed.
A solo freelancer needs two levels.
A global corporation needs eight.

**The same is true for our agent.**

When the agent works on one small project, two levels suffice (observations and a few patterns).
When the agent manages multiple domains for months — coding, research, statistics, marketing — the hierarchy must grow deeper because the CONTEXT is larger.

The depth of the knowledge tree IS the agent's sophistication.
A shallow tree means the agent reacts to each task from first principles.
A deep tree means the agent has accumulated understanding that shapes how it approaches ENTIRE classes of problems before it even looks at the specific task.

**This is the growth curve from doc 09, expressed structurally.**
Month 1: 2 levels (observations, a few patterns).
Month 3: 4 levels (observations, patterns, concepts, domain understanding).
Month 6: the deepest domains might have 5-6 levels, with the highest levels being abstract principles that transfer across domains.

And just like in organizations, the higher-level knowledge is RARE.
There are many observations, fewer patterns, even fewer concepts, and only a handful of high-level principles.
The tree is wide at the bottom and narrow at the top.
This is natural — not a design constraint, but an emergent property of consolidation under capacity pressure.

### Domains Are the Horizontal Dimension of the Hierarchy

The knowledge hierarchy has two dimensions:
- **Vertical**: abstraction level (observations → patterns → concepts → principles)
- **Horizontal**: specialization (statistics domain, coding domain, marketing domain)

At the bottom of the hierarchy, knowledge is highly specialized.
SQL patterns for THIS specific database.
Test scripts for THIS specific build system.
Marketing templates for THIS specific brand.
Each domain has its own wide base of specialized knowledge.
Just like in a company: accountants know accounting, programmers know code, testers know testing.
Each group has its own deep operational knowledge that does not overlap.

As you go UP the hierarchy, knowledge CONVERGES.
The patterns in the statistics domain ("always check data types before aggregation") and the patterns in the coding domain ("always check types before operations") start to look similar.
At the concept level, they might merge: "type safety is a cross-cutting concern."
At the highest level, there might be a single principle: "validate assumptions before acting."

**This means domains from [doc 07](07-context-flow.md) are not a separate concept from the knowledge hierarchy — they ARE the horizontal dimension at the lower levels.**

The DomainProfile from doc 07 is the boundary between the specialized bottom and the shared top.
Below the DomainProfile: domain-specific observations, patterns, tools, strategies.
Above the DomainProfile: cross-domain concepts and principles that transfer.

```
                    ┌──────────────────┐
        Level N:    │   "validate      │    ← one principle
                    │   assumptions"   │      (narrow, shared)
                    └──────┬───────────┘
                    ┌──────┴───────────┐
        Level 3:    │ "type safety is  │    ← cross-domain concept
                    │ cross-cutting"   │
                    ├──────┬───────────┤
        Level 2:    │concepts│concepts │    ← domain-level concepts
                    ├───┬───┤───┬─────┤
        Level 1:    │pat│pat│pat│pat  │    ← domain-specific patterns
                    ├─┬─┼─┬─┼─┬─┼─┬───┤
        Level 0:    │o│o│o│o│o│o│o│o│o│    ← raw observations
                    └─┴─┴─┴─┴─┴─┴─┴─┴─┘
                     statistics  coding      ← domains (horizontal)
```

The tree is wide at the bottom (many specialized observations per domain), narrow at the top (few principles that apply everywhere).
Domains are most distinct at the bottom and increasingly merged at the top.

**Implication for the Knowledge Store:**
- Retrieval at the bottom levels should be DOMAIN-SCOPED (search within "statistics" namespace)
- Retrieval at the top levels should be CROSS-DOMAIN (principles apply everywhere)
- Consolidation can happen WITHIN a domain (bottom-up) and ACROSS domains (when similar patterns emerge in different domains, they merge into a shared concept)

Cross-domain consolidation is the most valuable and rarest form of learning — it is the moment the agent discovers that something it learned in one area applies to another.
This is why the agent should periodically compare patterns across domains during background consolidation: "the statistics domain has a pattern about validating inputs, and the coding domain has a similar one — are these the same insight?"

### The Unified Pattern: Every Return Is Folding

Four things that seem different are actually the same pattern:

**1. A subagent returns a result to its parent** (doc 07).
The programmer completed the authentication module.
The manager gets: "auth refactored, 3 files changed, all tests pass."
The manager never sees the code diffs, the debug sessions, the Stack Overflow searches.
The details are folded into a summary.

**2. A subtask completes in the plan tree** (doc 07 Scenario 3).
The FocusChain node moves from "active" to "complete + summary."
All working context — tool calls, file edits, test runs — is compressed.
Only the summary survives in the parent's context.

**3. Raw observations consolidate into a pattern** (this document).
15 observations about SQL errors compress into: "always check date ranges on this table."
The 15 individual memories are no longer needed — the pattern handles those cases.

**4. A subordinate reports to a boss** (organizational analogy).
"The order shipped" — not "I walked to warehouse, found box 37B on shelf 4, scanned barcode, loaded truck..."
The boss operates at a higher abstraction level and needs the RESULT, not the PROCESS.

In every case: **a child does detailed work → compresses the result → returns it to the parent → the parent uses the summary without seeing the details.**

The details are either discarded (context compression during a session) or archived for potential retrieval (knowledge consolidation across sessions).
But the ACTIVE context — what the parent sees — always receives only the compressed summary.

### Context Inheritance Is the Downward Complement

Every boss knows this: you want your subordinate to know what YOU know.
A subordinate who understands the business context asks fewer questions and produces more relevant results.
One who does not wastes time on irrelevant directions or produces technically correct but strategically wrong output.

This is exactly the [context inheritance](07-context-flow.md) problem from doc 07.
The `inherit: blocks` mode (shared Letta-style memory blocks) gives the child the parent's business context.
The child who shares the parent's memory blocks understands WHY the task matters, not just WHAT to do.

So the full cycle is:

```
DOWNWARD (delegation):
  Parent shares context with child (context inheritance)
  → "Here's what we're building and why"
  → The more context the child has, the fewer questions it asks,
    the more relevant its output

CHILD WORKS:
  Detailed execution at the lower level
  → Code diffs, debug sessions, tool calls, search results

UPWARD (return):
  Child compresses result and returns to parent (context folding)
  → "Auth module refactored, 3 files, tests pass"
  → The parent never sees the details
```

This is the same cycle at every level of the hierarchy:
- Director delegates to manager (shares strategy context) → manager works → manager reports summary
- Manager delegates to team lead (shares project context) → team lead works → team lead reports summary
- Team lead delegates to developer (shares task context) → developer works → developer reports result

And in our architecture:
- SupervisorPattern delegates to researcher agents (shares research brief) → researchers search → researchers return compressed findings
- FocusChain parent delegates subtask to child (shares plan context) → child executes → child returns summary
- Knowledge hierarchy: higher-level concepts inform lower-level patterns → observations happen → observations consolidate upward

**The entire system is a hierarchy of delegation (downward, with context sharing) and return (upward, with compression).**

This is why context inheritance (doc 07) and context compression (doc 07 Scenario 3) and knowledge consolidation (this document) are not three separate concepts — they are three aspects of ONE pattern operating at different scales.

### Why This Solves the "Indiscriminate Memory Degrades Performance" Problem

Xiong et al.'s finding (arXiv:2505.16067) makes perfect sense in this framework:
- Indiscriminate memory = unlimited Layer 0 with no consolidation pressure
- Agents mimic retrieved memories = retrieving raw observations instead of generalizations
- Error propagation = wrong observations becoming entrenched because nothing forces them to be validated

Bounded capacity + forced consolidation + provisional generalizations + attribution through the hierarchy = memory that actually improves the agent.

---

## Software Engineering Ancestors

| Pattern | Source | How It Applies |
|---|---|---|
| **Write-ahead logging** | Databases (PostgreSQL, MySQL) | Metadata updates are append-only; lockfile swaps are serialized |
| **CQRS (Command Query Responsibility Segregation)** | DDD / Event Sourcing | Read-side (utility scores) and write-side (lockfile) are separate |
| **Continuous deployment** | DevOps | Every commit (candidate) goes through CI/CD (admission pipeline) |
| **Feature flags with gradual rollout** | LaunchDarkly | Shadow mode is a feature flag that routes traffic to candidates |
| **Online learning / bandit algorithms** | ML | Multi-armed bandit for selecting which candidate to shadow-test next |
| **Synaptic plasticity** | Neuroscience | Continuous weight adjustment from every signal |
| **Sleep consolidation** | Neuroscience | Background processing during idle periods |
