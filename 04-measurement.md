# Measurement — What To Measure, How To Attribute

## The Problem

An agent that evolves needs data to evolve on.
But agents are ambiguous — every task is different, every context is new, there is no "correct answer" to compare against.

And when something fails, there are three possible causes: the block is buggy, the block was applied to the wrong task, or the blocks are individually fine but the composition is wrong.
Without attribution, the agent cannot learn the right lesson from failure.

This document defines what to measure (the scorecard), how to interpret it (the attribution model), and where the ideas come from (software engineering, RL, recommender systems).

### How This Connects to the Other Docs

- [Doc 01](01-architecture-draft.md) defines the blocks. Doc 04 measures how each block version performs.
- [Doc 02](02-knowledge-as-code.md) defines the learning loop. Doc 04 provides the data that tells the loop WHAT to improve.
- [Doc 03](03-evolution-and-safety.md) defines admission gates and canary deployment. Doc 04 provides the metrics that determine pass/fail and promote/rollback.

The progression: **structure** (01) → **content** (02) → **evolution** (03) → **measurement** (04).

---

## The Scorecard: 8 Domain-Agnostic Metrics

Every task automatically produces these metrics.
They are comparable across completely different tasks because they measure the **agent's behavior**, not the **task content**.

| Metric | Type | What It Captures | Source |
|---|---|---|---|
| **Completion** | Binary (0/1) | Did the task finish successfully? | Every agent knows this — `final_answer` / `attempt_completion` / `AgentFinishAction` vs max_steps / timeout / abort |
| **User acceptance** | Ternary (1/0/-1) | Did the user accept, reject, or abandon? | [Cline](../research/concepts/agentic-loop/02-direct-loops.md) tracks accept/reject explicitly; [Factory Signals](../research/concepts/self-improving/03-self-evaluation.md) detects abandonment via escalation tone |
| **Steps** | Count | Number of loop iterations to completion | Fewer steps = more efficient. [smolagents](../research/products/smolagents/02-agentic-loop.md) shows code agents use ~30% fewer steps |
| **Cost** | Dollars | Total token cost | [PaperQA2](../research/concepts/deep-research/02-paperqa2.md) tracks this in status string: `Current Cost: $X.XX` |
| **Errors** | Count | Number of tool call failures | Available from every ToolRegistry dispatch result |
| **Retries** | Count | Number of retry/recovery events | Tracked by ErrorHandler from [doc 01](01-architecture-draft.md) |
| **Stuck events** | Count | Number of StuckDetector triggers | [OpenHands 5 patterns](../research/concepts/agentic-loop/04-event-driven-loops.md), [Goose RepetitionInspector](../research/concepts/agentic-loop/02-direct-loops.md), [EloPhanto 5-layer stagnation](../research/concepts/agentic-loop/02-direct-loops.md) |
| **Wall time** | Seconds | Time from start to completion | Captures both LLM latency and tool execution time |

### Why These 8 Are Sufficient

None require knowing what the task IS.
A research task and a coding task both have a completion rate, a step count, a cost, and an error rate.
This is the same insight behind SRE/SLI metrics: you do not need to understand HTTP requests to measure latency percentiles.

### What These 8 Cannot Tell You

They cannot tell you about **output quality** — whether the agent's answer was correct, thorough, or well-structured.
For that, you need the LLM-as-judge layer (see below).

---

## Per-Block Performance Tracking

The scorecard above measures the whole task.
To drive evolution, we need to attribute performance to individual blocks.

Every block in the lockfile gets a performance profile, updated after every task that uses it:

```yaml
# Automatically maintained per block version
web_scraper:
  version: 2.0.0
  total_invocations: 147
  success_rate: 0.85
  avg_latency_ms: 1200
  avg_cost_per_invocation: 0.003
  failure_by_task_category:
    research: 0.05
    code_analysis: 0.45
    data_extraction: 0.12
  error_types:
    timeout: 23
    parse_error: 8
    auth_failure: 2
  previous_version:
    version: 1.1.0
    success_rate: 0.92
```

This profile enables direct comparison: "since we deployed `web_scraper@2.0.0`, success rate dropped from 92% to 85%."

---

## The Attribution Model: Three Failure Causes

When a task fails, there are exactly three possible causes.
Each requires a different corrective action.

### Cause 1: Block Bug — The Code Is Wrong

**Signal**: the block fails consistently, regardless of which task uses it and which composition it is part of.

**Detection**: track failure rate **per block version** across all tasks.
If one version has significantly higher failure rate than the previous version, it is a block bug.

**Example**: `web_scraper@2.0.0` throws errors 40% of the time. Same tasks succeed when run with `web_scraper@1.x`. Confirmed regression.

**Action**: fix the block (publish `@2.0.1`) or rollback (targeted revert to `@1.x` via [doc 03 lockfile swap](03-evolution-and-safety.md)).

**Ancestor pattern**: this is **canary analysis** from Kubernetes — compare error rates between the new version (canary) and the old version (baseline). If the canary is significantly worse, roll back.

### Cause 2: Misapplication — The Block Was Used for the Wrong Task

**Signal**: the block works fine in its intended context but fails when applied to a different kind of task.

**Detection**: track failure rate **per block x task category**.
If a block succeeds for research tasks but fails for coding tasks, it is misapplication, not a bug.

**Example**: `deep_research_agent@1.0.0` works great for web research but fails for code analysis tasks.
The composition itself is correct — it was retrieved by the semantic index from [doc 02](02-knowledge-as-code.md) for a task it was not designed for.

**Action**: improve the block's **description** (so the semantic index retrieves it more precisely) or create a new variant for the different use case.

**Ancestor pattern**: this is **segment analysis** from A/B testing — the treatment works for segment A but not segment B. The treatment is not broken; the targeting is wrong.

**Inspiration from research**:
- [DGM](../research/concepts/self-improvement-architectures/06-dgm.md) distinguishes specific-failure mutations (fix the agent on one issue) from meta-level mutations (fix systematic misapplication like empty patches, context overflow).
  25% of mutations target `solve_empty_patches`, 25% target `solve_stochasticity` — these are all misapplication-class fixes.
- [Voyager CriticAgent](../research/products/voyager/04-iterative-code-and-critic.md) evaluates from game state, not from code.
  If `craftIronPickaxe` fails because the bot lacked iron ingots, the skill is correct — the prerequisites were wrong.
  The curriculum agent proposes mining iron next, not rewriting the crafting skill.

### Cause 3: Composition Mismatch — The Wiring Is Wrong

**Signal**: the individual blocks all work, but the combination does not.

**Detection**: if all component blocks pass their individual tests but the composition fails integration tests, it is a composition mismatch.

**Example**: `web_scraper@2.0` works. `research_context_boundary@0.2` works. But the composition that wires them together fails because the scraper output format changed and the context boundary does not understand it.

**Action**: fix the composition (update the wiring) or fix the interface contract between blocks.

**Ancestor pattern**: this is **integration testing** vs **unit testing** — all units pass, but the system fails. The interfaces between components are the source of error.

### The Sibling Analysis (from Moatless)

Before blaming a block, check its siblings — the same approach [Moatless uses for MCTS node evaluation](../research/concepts/agentic-loop/07-tree-search-loops.md):

1. Did the same block version succeed on a similar task recently? → misapplication, not bug
2. Did a different block version succeed on the same task? → block regression
3. Did the same composition succeed with different sub-blocks? → composition mismatch
4. Did multiple sibling approaches all fail? → the approach is fundamentally wrong

The [Moatless FeedbackGenerator](../research/concepts/agentic-loop/07-tree-search-loops.md) analyzes all sibling nodes' actions, observations, and reward scores, then synthesizes guidance that steers new attempts away from previously failed approaches.
The [TerminalValueFunction](../research/concepts/agentic-loop/07-tree-search-loops.md) deliberately provides abstract strategic feedback rather than code-level details — to avoid biasing toward minor variations of a failed approach.

Applied to our block evolution: when a block version fails, analyze it in context of all other versions and all other tasks before deciding what to fix.

---

## Task Categorization — The Missing Piece

Attribution requires knowing task categories, but the agent "always does something new."

**Solution: let the LLM categorize.**
After each task, a lightweight LLM call classifies the task into high-level categories:

```yaml
# Auto-generated task classification
type: research          # research / coding / data_analysis / automation / communication
domain: web             # web / filesystem / API / database / document / mixed
complexity: moderate    # simple / moderate / complex
tools_used: [web_scraper, research_context_boundary, deep_research_agent]
novel: true             # has the agent seen a similar task before?
```

These categories are cheap to compute (one fast LLM call, like PaperQA2's `FAST_LLM` tier) and provide the stratification needed for attribution.

**The categories evolve autonomously.**
From [Factory Signals](../research/concepts/self-improving/03-self-evaluation.md): the facet extraction system generates embeddings for session summaries, clusters similar sessions, and proposes new facet categories when clusters do not fit existing dimensions.
The "branch switches" category was discovered autonomously when clustering revealed sessions that correlated with complexity but did not match existing categories.

Applied to our architecture: the initial category set (type, domain, complexity) is a starting point.
Over time, the measurement system discovers new categories via clustering — "oh, tasks involving legacy APIs form a distinct cluster with systematically different performance."

---

## The LLM-as-Judge Layer

For signals that the 8-metric scorecard cannot capture — output quality, user satisfaction beyond accept/reject, subtle behavioral patterns — an LLM-as-judge analyzes session transcripts.

### What It Detects

From [Factory Signals](../research/concepts/self-improving/03-self-evaluation.md):

**Friction patterns** (domain-agnostic behavioral signals):
- Error events per session
- Repeated rephrasing — user restates the same thing 3+ times
- Escalation tone — user frustration
- Abandoned tool flows — agent starts something, user interrupts
- Backtracking — agent undoes its own work
- Context churn — repeatedly adding/removing the same file

**Delight patterns**:
- First-attempt success on complex tasks
- User positive reactions
- Efficiency comments

**Category discovery**:
- New friction types emerge via embedding clustering
- "Context churn" did not exist in Factory's original design — it was surfaced when clustering found a group of friction moments with shared semantic similarity
- "Learning moments" delight type was discovered when sessions where the agent explained its reasoning generated disproportionately positive signals

### How It Runs

A **batch process** (not real-time) analyzes completed sessions:
1. Session transcript is sent to a cheap LLM (the judge)
2. The judge classifies friction events, delight events, and task categories
3. Results are stored alongside the scorecard metrics
4. Aggregation happens per block version and per task category

This is exactly [Factory Signals' daily batch](../research/concepts/self-improving/03-self-evaluation.md) — analyzing thousands of sessions per day, with results flowing to a database for historical analysis.

### Connection to Self-Evaluation

From [Ouroboros 7-layer stack](../research/concepts/self-improving/03-self-evaluation.md):
- Health invariants surface anomalies as informational text
- Self-check checkpoints every 50 rounds provide quantitative data (token count, cost, rounds remaining)
- Drift detection watches for behavioral anti-patterns

From [OpenHands stuck detector](../research/concepts/self-improving/03-self-evaluation.md):
- 5 procedural pattern matchers run after each step
- Each detection injects a corrective message

These are real-time self-evaluation.
The LLM-as-judge is post-hoc evaluation.
Both feed into the learning loop from [doc 02](02-knowledge-as-code.md) and the admission gates from [doc 03](03-evolution-and-safety.md).

---

## Aggregate Signals for Evolution Decisions

The per-block metrics and the attribution model combine into evolution signals:

### When to Fix a Block

- Block version success rate dropped > 10% from previous version → likely regression
- Block version error rate consistently high (> 20%) across all task categories → bug
- Multiple users rejecting results from tasks using this block → quality issue

### When to Improve a Block's Description

- Block retrieved for task categories where it has low success rate → semantic index returning wrong results
- Block never retrieved for task categories where it would succeed → description too narrow

### When to Create a New Block

- Task category has no matching blocks and consistently low completion rate → capability gap
- Existing blocks work for simple variants of this category but fail for complex variants → need a more sophisticated version
- The agent repeatedly improvises the same pattern (e.g., spawning parallel sub-agents for research) → crystallize into a composition artifact

This last signal is the [OpenClaw-Foundry crystallization pattern](../research/concepts/self-improving/04-self-modification.md): when a workflow pattern hits 5+ uses with 70%+ success rate, Foundry automatically generates a dedicated tool for it.

### When to Retire a Block

- Block version has not been used in the last N tasks → candidate for retirement
- A newer version has strictly better metrics across all task categories → old version is obsolete
- But: do not delete — mark as retired in the index. It stays on disk for rollback.

---

## Software Engineering Ancestors

| Pattern | Source | How It Applies |
|---|---|---|
| **SLIs/SLOs** | Google SRE | The 8-metric scorecard defines SLIs. Thresholds define SLOs. Violations trigger alerts. |
| **A/B testing with stratification** | Netflix, web analytics | Compare block versions controlling for task category. Canary deployment from doc 03 IS an A/B test. |
| **Engagement metrics** | Recommender systems (Netflix, Spotify) | User acceptance = engagement. Abandonment = churn. Session length = dwell time. |
| **Cumulative reward** | Reinforcement learning | The scorecard can be collapsed into a single scalar reward per task for RL-style training. [PaperQA2 Aviary](../research/concepts/deep-research/02-paperqa2.md) was designed for this. |
| **Feature importance / SHAP values** | ML model interpretability | Attribution model asks "which feature (block) caused this prediction (outcome)?" Same decomposition logic. |
| **Root cause analysis** | SRE incident management | Three failure causes (bug, misapplication, composition mismatch) are a structured RCA framework. |
| **Funnel analysis** | Product analytics | Track where in the agentic loop tasks fail: context assembly? tool dispatch? LLM reasoning? Identifies bottleneck blocks. |
| **Cohort analysis** | Product analytics | Group tasks by category and compare block performance across cohorts. Different cohorts may need different block versions. |
| **Multi-armed bandit** | RL, ad optimization | Instead of fixed A/B split, dynamically route tasks to the block version that performs best for that task category. Exploration vs exploitation. |
| **Blame/bisect** | Git | When performance degrades, bisect across lockfile history to find which version change caused it. Lockfile archive from doc 03 enables this. |
