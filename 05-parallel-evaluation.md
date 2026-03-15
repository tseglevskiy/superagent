# Parallel Evaluation — Every Task Is an Experiment

## The Idea

Pay 2x, get consistent improvement.

Instead of running one agent configuration per task, run two: the current best (primary) and a candidate (shadow).
The primary serves the user.
The shadow produces measurement data.
Over time, when the shadow consistently wins, it becomes the primary.

This turns every task into an A/B test.
The agent improves continuously from its own workload without ever degrading the user's experience.

### How This Connects to the Other Docs

- [Doc 01](01-architecture-draft.md) — the EnvironmentMultiplexer provides isolation between primary and shadow
- [Doc 02](02-knowledge-as-code.md) — the Knowledge Store provides the block versions being compared
- [Doc 03](03-evolution-and-safety.md) — the lockfile swap provides the promotion mechanism; canary deployment IS this pattern run across many tasks
- [Doc 04](04-measurement.md) — the scorecard + attribution model provide the comparison criteria; the LLM-as-judge layer evaluates quality

The progression: **structure** (01) → **content** (02) → **evolution** (03) → **measurement** (04) → **experimentation** (05).

---

## What the Research Proves

Five studied projects already run parallel execution on the same task:

### Agent S — Behavior Best-of-N

Run the agent N times (default 3) on the same GUI task.
[BehaviorNarrator](../research/concepts/llm-as-judge/03-per-trajectory-evaluation.md) generates per-step fact captions from annotated before/after screenshots.
[ComparativeJudge](../research/concepts/llm-as-judge/03-per-trajectory-evaluation.md) evaluates all N trajectories against a detailed rubric.
Result: +6.6pp improvement (66% to 72.6%), surpassing human performance on OSWorld.
Cost: 3x base.
Generalized zero-shot to WindowsAgentArena (+6.4pp) and AndroidWorld (+3.5pp).

**Key insight**: N parallel runs + LLM judge is the simplest architecture that produces superhuman results.
The agent itself does not change — only the selection improves the output.

### SWE-Agent — RetryAgent with Reviewer/Chooser

[RetryAgent](../research/concepts/agentic-loop/02-direct-loops.md) wraps DefaultAgent and runs it multiple times (attempts).
Each attempt produces a complete trajectory.
After all attempts, a reviewer LLM scores each trajectory, and a chooser selects the best.
This is trajectory-level Best-of-N — fundamentally different from step-level retry.

### dmux — Environment Multiplexing A/B

[dmux's A/B comparison mode](../research/concepts/multi-agent/05-environment-multiplexing.md): launch the same task with two different agents (e.g., Claude Code vs Codex) in separate git worktrees.
Human compares results.
[Two-phase merge](../research/concepts/multi-agent/05-environment-multiplexing.md) reconciles with AI-assisted conflict resolution.

**Key insight**: git worktrees provide perfect isolation for coding tasks.
No shared state, no interference, clean merge path.

### Moatless — MCTS Tree Search

[Moatless SearchTree](../research/concepts/agentic-loop/07-tree-search-loops.md) explores multiple approaches simultaneously on the same task.
Each tree branch is a different solution path.
The [ValueFunction](../research/concepts/llm-as-judge/02-per-action-evaluation.md) scores every node.
The [FeedbackGenerator](../research/concepts/agentic-loop/07-tree-search-loops.md) teaches new branches what did not work in sibling branches.
The [TerminalValueFunction](../research/concepts/agentic-loop/07-tree-search-loops.md) evaluates finished solutions with abstract strategic feedback.

**Key insight**: parallel exploration with feedback between branches is strictly better than independent parallel runs.
The 14-component UCT scoring guides exploration toward promising paths.

### Open Deep Research — Parallel Researchers

[Open Deep Research supervisor](../research/concepts/deep-research/03-open-deep-research.md) spawns up to 5 parallel researcher sub-agents.
Each explores a different angle of the same broad topic.
Results are compressed before crossing the tier boundary.
The supervisor assesses coverage via [think_tool](../research/concepts/coverage-assessment/_index.md) and spawns more researchers for gaps.

**Key insight**: for research tasks, parallel exploration from different angles produces better coverage than sequential deep dives.

---

## Three Execution Modes

### Mode 1: Shadow (Background Comparison)

The primary configuration serves the user.
The shadow configuration runs in the background on the same task.
The shadow's result is logged but never delivered.

**When to use**: continuous improvement data collection.
Zero risk to user experience — the shadow can crash, timeout, or produce garbage without affecting anyone.

**What it costs**: 2x compute (always).
No additional latency — the user sees the primary's result at normal speed.

**What it produces**: paired comparison data for every task.
Over N tasks, the measurement system (doc 04) accumulates statistically significant evidence about which lockfile is better.

**Inspiration**: shadow traffic in microservices — route production traffic to both the current and candidate service, serve from current, log candidate results.

### Mode 2: Race (Return the Better/Faster)

Both configurations run in parallel.
Return whichever finishes first (latency optimization) OR whichever scores higher (quality optimization).

**When to use**: when both configurations are trusted and you want the best result for the user right now.

**What it costs**: 2x compute.
Latency is the MINIMUM of the two (if racing for speed) or the MAXIMUM plus judge time (if racing for quality).

**What it produces**: the better result for the user + comparison data.

**Quality race**: both results are evaluated by the [LLM-as-judge](../research/concepts/llm-as-judge/_index.md) (Agent S's ComparativeJudge pattern).
The judge picks the winner.
The user gets the winning result.
The losing result is logged for measurement.

**Speed race**: return whichever completes first.
Log the slower one when it arrives.
Useful when both configurations produce equivalent quality but different latency.

**Inspiration**: Google's hedged requests — send the same request to two servers, return whichever responds first.

### Mode 3: Ensemble (Synthesize Both)

Both configurations run in parallel.
A synthesizer combines the best parts of both results.

**When to use**: research, writing, and analysis tasks where the outputs are complementary rather than competing.

**What it costs**: 2x compute + synthesizer cost.
Highest total cost, but produces the richest output.

**What it produces**: a combined result that is often better than either individual result.

**How synthesis works**:
- For research: merge source lists, deduplicate findings, combine perspectives.
  This is exactly what [Open Deep Research's supervisor](../research/concepts/deep-research/03-open-deep-research.md) does with parallel researcher outputs.
- For writing: an LLM takes both drafts and produces a synthesis that keeps the best elements of each.
- For analysis: programmatic merge where structures overlap, LLM merge where they diverge.

**Inspiration**: ensemble methods in ML — Random Forest runs all trees and votes; stacking uses a meta-learner to combine predictions.

---

## Isolation by Task Type

The parallel configurations need isolated execution environments.
The isolation mechanism depends on the task type.

### Coding Tasks

**Isolation**: git worktrees (dmux pattern).
Each configuration gets its own branch and working directory.
See [environment multiplexing](../research/concepts/multi-agent/05-environment-multiplexing.md).

**Comparison**: programmatic — diff the patches, run tests on both, compare test results.
The [8-metric scorecard](04-measurement.md) (steps, cost, errors, wall time) provides objective comparison.
Tests provide ground truth.

**Merge path**: two-phase merge (dmux) or cherry-pick specific changes.

### Research Tasks

**Isolation**: architectural context isolation (Open Deep Research pattern).
Each configuration gets its own conversation state.
See [architectural isolation in context management](../research/concepts/context-management/02-bounding-strategies.md).

**Comparison**: LLM-as-judge evaluates thoroughness, accuracy, source diversity, citation quality.
The scorecard captures steps, cost, and source count.

**Merge path**: ensemble synthesis — combine source lists, deduplicate findings, merge outlines.

### Writing and Analysis Tasks

**Isolation**: independent execution — no shared state needed.
Each configuration produces its output from the same input.

**Comparison**: LLM-as-judge with task-specific rubric (Agent S's ComparativeJudge pattern).
The scorecard captures steps, cost, and wall time.

**Merge path**: LLM synthesis (take the best elements of both) or direct selection (pick the winner).

### Data Processing Tasks

**Isolation**: independent execution on the same input data.

**Comparison**: programmatic — diff outputs, compare metrics, hash comparison for deterministic tasks.

**Merge path**: usually direct selection — data processing tends to be correct or incorrect, not a spectrum.

---

## The Judge

Comparing two results requires a judge.
Three judge types, used in combination:

### Programmatic Judge (Fast, Free, Limited)

Compare outputs using the [8-metric scorecard](04-measurement.md): completion, steps, cost, errors, retries, stuck events, wall time.
Plus task-type-specific comparisons: test results for code, source count for research, output length for writing.

Inspired by: [Moatless CodingValueFunction](../research/concepts/llm-as-judge/02-per-action-evaluation.md) — rule-based heuristics that handle common cases deterministically for zero cost.

### LLM-as-Judge (Rich, Moderate Cost, Non-Deterministic)

Send both outputs to an LLM with a comparison rubric.
The LLM evaluates quality dimensions that programmatic comparison cannot: correctness, thoroughness, clarity, relevance.

Inspired by:
- [Agent S ComparativeJudge](../research/concepts/llm-as-judge/03-per-trajectory-evaluation.md) — 8+ guideline rubric, trajectory-by-trajectory evaluation
- [Moatless AgentDiscriminator](../research/concepts/llm-as-judge/03-per-trajectory-evaluation.md) — multi-agent debate with N agents x N rounds for more robust comparison
- [Factory Signals](../research/concepts/llm-as-judge/04-per-session-and-variant.md) — batch LLM analysis with self-evolving category taxonomy

### User Feedback (Ground Truth, Sparse)

When the user accepts, rejects, or provides feedback on the primary's result, that is ground truth.
In race mode (Mode 2), the user can also see both results and choose.

This is the sparsest signal but the most authoritative.
It calibrates the other two judges.

---

## The Promotion Pipeline

Shadow data feeds into the [canary deployment](03-evolution-and-safety.md) mechanism from doc 03.

### The Flow

1. **Create candidate lockfile** — a new block version is deployed as the shadow
2. **Accumulate data** — shadow runs alongside primary on every task (or a configured percentage)
3. **Statistical comparison** — the measurement system aggregates scorecard + judge results across N tasks
4. **Promotion decision** — when the shadow is statistically significantly better (configurable threshold), promote it: the shadow's lockfile becomes `current.lock`
5. **The promoted version becomes the new primary** — and a new shadow can start testing the next candidate

### Statistical Rigor

Borrowed from A/B testing best practices:
- **Minimum sample size** — do not promote until N tasks have been compared (configurable, default maybe 20-50)
- **Significance threshold** — require p < 0.05 or equivalent Bayesian credible interval
- **Stratification** — compare within task categories (from [doc 04](04-measurement.md)) to catch cases where the shadow is better for research but worse for coding
- **Guardrails** — if the shadow is significantly WORSE on any task category, block promotion even if it is better overall

### Multi-Armed Bandit Allocation

Instead of fixed 50/50 split, dynamically adjust the shadow traffic percentage:
- Start at 50/50 (maximum learning speed)
- As evidence accumulates, shift toward the winner: 70/30, 90/10
- Keep a minimum exploration percentage (e.g., 10%) forever to detect environmental changes
- If a new block version is published, reset to 50/50 for the new comparison

Inspired by: Thompson Sampling, UCB (the same UCB that [Moatless uses for MCTS node selection](../research/concepts/agentic-loop/07-tree-search-loops.md) — balancing exploitation of known good options with exploration of uncertain alternatives).

---

## Cost-Quality Tradeoff

### When to Run Shadow (Always? Sometimes?)

| Strategy | Cost | Data Quality | When to Use |
|---|---|---|---|
| **Always** | 2x | Maximum — every task produces comparison data | When continuous improvement is the top priority |
| **High-value tasks only** | 1.1-1.5x | Good for important tasks, no data for simple ones | When cost matters but you want to test on complex tasks |
| **Random sample** (e.g., 20%) | 1.2x | Statistical — slower convergence but sufficient | When cost is constrained |
| **Triggered by new version** | Burst 2x, then 1x | Focused — data only during candidate evaluation | When new block versions are infrequent |

### The ROI Calculation

Agent S proved that 3x cost produces +6.6pp improvement.
That is a 2.2pp improvement per 1x additional cost.

If our shadow mode (2x cost) produces even half that improvement rate (+3pp per 1x additional cost), the ROI is clear: better outcomes on every task, plus the continuous stream of comparison data that drives block evolution.

The cost is also front-loaded: once a candidate is promoted and the lockfile is updated, you stop paying for shadow on that comparison.
The 2x cost only applies during the evaluation window.

---

## Software Engineering Ancestors

| Pattern | Source | How It Applies |
|---|---|---|
| **Speculative execution** | CPU architecture (1960s) | Execute both branches, keep the correct one. Applied: run both lockfiles, keep the better result. |
| **A/B testing** | Web analytics (2000s) | Split traffic between variants, measure which wins. Applied: shadow mode with lockfile comparison. |
| **Multi-armed bandit** | Statistics, ad optimization | Dynamically allocate traffic toward the winner. Applied: shift shadow percentage as data accumulates. |
| **Hedged requests** | Google Tail at Scale (2013) | Send same request to two servers, return faster. Applied: race mode returning first/better result. |
| **Shadow traffic** | Microservices (2010s) | Route to both versions, serve from current, log candidate. Applied: shadow mode exactly. |
| **Ensemble methods** | ML (Random Forest 1995, Stacking 1992) | Run all models, combine predictions. Applied: ensemble mode with LLM synthesis. |
| **Blue/green deployment** | DevOps (2010s) | Two identical environments, atomic switch. Applied: lockfile swap from doc 03. |
| **Chaos engineering** | Netflix (2011) | Inject failures to test resilience. Applied: shadow can test aggressive new configurations without risk. |
| **Canary analysis** | Kubernetes, Kayenta | Compare canary metrics against baseline with statistical rigor. Applied: promotion pipeline with significance testing. |
| **Tournament selection** | Genetic algorithms (1970s) | Run N candidates, select the best. Applied: Agent S bBoN, SWE-Agent RetryAgent. |
