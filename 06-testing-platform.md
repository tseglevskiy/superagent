# Testing Platform — Built-In, Zero-Authoring, Three Tiers

## Why Not Unit Tests

Unit tests are coupled to internal implementation.
When you change the code, you change the tests.
The tests verify that the code does what the code does — circular.
They catch typos, not design failures.

What matters for a self-evolving agent is different: **do the blocks still work together after a version change?**
That is an integration question, not a unit question.

The research confirms this.
No studied project uses unit tests as an admission gate for self-improvement:
- [EloPhanto](../research/concepts/self-improvement-architectures/08-elophanto.md) runs `pytest` pre/post modification, but tests are LLM-generated and artifact-specific
- [DGM](../research/concepts/self-improvement-architectures/06-dgm.md) uses SWE-bench benchmarks, not unit tests
- [OpenEvolve](../research/concepts/self-improvement-architectures/02-pattern-atlas.md) uses user-defined evaluators with cascade stages
- [Ouroboros](../research/concepts/self-improvement-architectures/05-ouroboros.md) uses pre-push pytest as a gate, but tests are hand-written

The gap across all projects: **no built-in testing platform that auto-generates tests from the architecture itself**.
Every project either hand-writes tests or skips them.

### How This Connects to the Other Docs

- [Doc 01](01-architecture-draft.md) — blocks have interfaces. Interfaces are testable contracts.
- [Doc 02](02-knowledge-as-code.md) — every artifact has a manifest with typed deps. Manifests are testable.
- [Doc 03](03-evolution-and-safety.md) — admission gates require "targeted tests" and "regression suite." This document defines what those are.
- [Doc 04](04-measurement.md) — every task produces a recorded trace. Traces become integration test fixtures.
- [Doc 05](05-parallel-evaluation.md) — shadow mode produces paired comparison data. Comparisons become regression baselines.

---

## Three Test Tiers

```
Tier 1: Contract Tests
  Source: auto-generated from manifest.yaml declarations
  Trigger: on every block version publish
  Cost: $0 (no LLM, just interface checking)
  Speed: milliseconds

Tier 2: Integration Replay
  Source: auto-generated from recorded task sessions
  Trigger: on every lockfile change
  Cost: $0 (replay recorded responses) or low (Ollama for new paths)
  Speed: seconds to minutes

Tier 3: E2E Smoke with Cheap Local Model
  Source: auto-generated from composition artifacts
  Trigger: on every lockfile change, before promotion
  Cost: $0 (local Ollama on GPU)
  Speed: minutes

All three tiers must pass before lockfile swap (doc 03).
```

---

## Tier 1: Contract Tests

### What They Test

Not internal logic.
**Interface compatibility.**

Every block in [doc 01](01-architecture-draft.md) has an interface:
- ContextBoundary: `(messages, config) -> (messages, metadata)`
- StuckDetector: `(recent_actions) -> Continue | Intervene`
- Tool artifact: `(typed_inputs) -> typed_output`
- Composition artifact: declares deps with version ranges in manifest.yaml

A contract test verifies: "does this block version still satisfy the interface that other blocks depend on?"

If `deep_research_agent@1.0.0` declares `deps: [web_scraper@^2.0]`, and `web_scraper@2.1.0` changes its output format, the contract test catches it — because the composition's declared expectations no longer match the block's actual behavior.

### How They Are Auto-Generated

The platform reads [manifest.yaml](03-evolution-and-safety.md) for every block version.
For each block, it finds all compositions that declare it as a dependency.
Each composition's dependency declaration becomes a contract:

```yaml
# deep_research_agent/1.0.0/manifest.yaml
deps:
  - web_scraper: "^2.0"    # expects web_scraper to return {url, content, metadata}
  - research_context_boundary: "^0.2"  # expects strategy interface
```

The platform generates contract tests that verify:
- `web_scraper@2.1.0` still returns the shape expected by `deep_research_agent@1.0.0`
- `research_context_boundary@0.2.1` still implements the `(messages, config) -> (messages, metadata)` interface
- All declared deps are present in the lockfile with compatible versions

**Zero test authoring.** The block author writes the manifest. The platform generates the tests.

### Ancestors

**Pact / Consumer-Driven Contract Testing** (microservices, 2013) — each consumer declares what it expects from a provider.
The provider is tested against ALL consumer contracts.
If any contract breaks, the provider cannot deploy.
Our compositions are "consumers" of their dependency blocks.

**TypeScript structural typing** — interface mismatches caught at compile time.
Our manifest.yaml + typed interfaces provide the same structural checking at the block level.

**Protocol Buffers / gRPC interface evolution** — backward compatibility rules (never remove a field, never change a field type).
Our SemVer from [doc 03](03-evolution-and-safety.md) encodes the same rules: MAJOR bump = breaking change, MINOR = backward compatible addition.

---

## Tier 2: Integration Replay

### What They Test

That a chain of 2+ blocks still works together after a version change.

### How They Are Auto-Generated

The measurement system from [doc 04](04-measurement.md) records every successful task: inputs, block invocations, LLM calls, tool results, outputs, scorecard.
These recorded sessions become test fixtures automatically.

**The replay process:**

1. Task succeeds with lockfile A. The full trace is recorded: user input, every LLM call (prompt + response), every tool call (name + args + result), final output, scorecard.
2. A block version changes. New lockfile B is proposed.
3. The platform replays the recorded trace against lockfile B:
   - Same user input
   - For LLM calls: either replay the recorded response (deterministic mode) or re-run with Ollama (re-execution mode)
   - For tool calls: replay recorded results (deterministic) or re-execute (live)
   - Compare: does the output still match? Does the scorecard still pass?

**Deterministic replay** (fastest, $0): all LLM and tool responses are replayed from the recording.
This tests whether the block wiring still routes correctly — the same inputs through the same pipeline should produce the same outputs.
If a block version change causes a different routing decision, the replay diverges and the test flags it.

**Re-execution replay** (more thorough, uses Ollama): LLM calls are re-executed with a cheap local model.
Tool calls are re-executed against real tools (or mocked).
This tests whether the new block version produces reasonable behavior even when the LLM makes different choices.

### What Gets Recorded (The Session Trace)

Every task already produces the [8-metric scorecard](04-measurement.md).
The integration replay adds a deeper trace:

```yaml
# Auto-recorded after every successful task
task_id: "2026-03-14-research-quantum"
lockfile: "2026-03-14T21-00.lock"
input: "Research the state of quantum error correction in 2025"
task_category: { type: research, domain: web, complexity: moderate }
trace:
  - step: 1
    block: deep_research_agent@1.0.0
    action: spawn_subagent
    args: { task: "search quantum error correction papers 2025" }
    result: { status: ok, sources: 12 }
  - step: 2
    block: web_scraper@2.0.0
    action: scrape
    args: { url: "https://arxiv.org/..." }
    result: { content: "...", length: 15000 }
  # ... full trace
output: "Based on 12 sources, quantum error correction in 2025..."
scorecard: { completion: 1, steps: 8, cost: 0.42, errors: 0, retries: 0, stuck: 0, wall_time: 45 }
```

### How Many Replays

The platform keeps the last N successful task recordings per task category (configurable, default 10 per category).
When a block version changes, it replays all recordings that involved that block.

If `web_scraper@2.0.0` was used in 7 research tasks and 3 coding tasks, updating to `web_scraper@2.1.0` triggers replay of all 10.
If 9/10 pass but 1 fails on a coding task, the [attribution model](04-measurement.md) identifies: regression in the coding category.

### Ancestors

**Golden file tests / snapshot tests** (Jest snapshots, Go testdata/) — record expected output, compare on every run.
Our "golden file" is a recorded task session with its full trace.

**VCR / Betamax** (Ruby `vcr` gem, Python `vcrpy`) — record HTTP interactions on first run, replay them in tests.
Our equivalent: record LLM API calls and tool results, replay them to test block changes without paying for LLM calls.

**Database migration tests** — run the migration on a copy of production data, then run the integration suite.
Our equivalent: swap the lockfile on a copy of the session trace, then replay the integration tests.

**Playwright / Cypress record-and-replay** — record user interactions in a browser, replay as tests.
Our equivalent: record agent interactions with tools and LLMs, replay as integration tests.

---

## Tier 3: E2E Smoke with Cheap Local Model

### The Insight

You do not need Claude/GPT to test whether the plumbing works.

A 14B model on Ollama (Qwen-3, Llama, Mistral) can verify:
- Does the ContextAssembler produce valid messages?
- Does the ToolRegistry dispatch correctly?
- Does the DirectLoop terminate?
- Does the SupervisorPattern actually spawn sub-agents?
- Does the composition artifact wire blocks together without errors?
- Does the ErrorHandler fire on tool failures?
- Does the StuckDetector intervene on repetition?

The cheap model produces WORSE answers, but the test is not checking answer quality.
It is checking that **the architecture does not crash, the blocks connect, the interfaces work, and the loop terminates.**

### What the Cheap Model Tests

**1. Liveness** — DirectLoop with Ollama, simple task ("list files in the current directory"), verify it completes without crash.
Tests: EventBus delivers messages, LLMClient returns responses, ToolRegistry dispatches, loop terminates.

**2. Block wiring** — Each composition artifact loaded from the Knowledge Store, run with Ollama, verify all declared dependency blocks are invoked.
Tests: manifest.yaml deps are resolved, blocks are loaded from the correct versions, the composition executes its wiring.

**3. Error recovery** — Force errors (return error from a tool, simulate timeout), verify ErrorHandler fires and the loop continues.
Tests: retry with backoff, model fallback chain, the agent does not crash on tool failure.

**4. Stuck detection** — Feed the same input repeatedly, verify StuckDetector intervenes before max_steps.
Tests: repetition detection, oscillation detection, corrective message injection.

**5. Context bounding** — Run a long conversation (50+ turns with the cheap model), verify ContextBoundary triggers and compaction happens.
Tests: token counting, threshold detection, compaction execution, post-compaction continuation.

**6. Sub-agent spawning** — Run a composition that uses SubAgentSpawner, verify the child starts and returns a result.
Tests: isolation (child gets own context), lifecycle (child completes and result returns to parent).

**7. Version compatibility** — New lockfile, run all E2E tests with Ollama, verify nothing crashes.
Tests: the full lockfile resolves, all block versions load, the system is operational.

### Why a Cheap Model Is Better Than Mocks

Mocks are deterministic — they return exactly what you programmed.
A cheap LLM is non-deterministic — it makes unexpected decisions, calls tools in weird orders, sometimes fails.

This non-determinism is **valuable for testing**.
It stress-tests error handling, stuck detection, and recovery paths that mocks never exercise.
The cheap model is a **chaos monkey** — it makes the architecture prove it can handle real LLM behavior (including bad behavior) without crashing.

Inspired by:
- **Chaos engineering / Netflix Simian Army** — inject failures to test resilience
- **Fuzz testing** — feed random/malformed inputs to find crashes
- **Compiler bootstrapping** — build with a simpler compiler first, then rebuild with itself

### Cost: $0

Ollama runs locally on the GPU.
The GPU cost is amortized (you already have it for other tasks).
The cheap model uses ~8GB VRAM.
You can run the entire E2E suite before every lockfile swap for zero marginal cost.

### Speed: Minutes

A 14B model on a modern GPU generates ~40 tokens/second.
A simple liveness test (5-10 turns) takes ~30 seconds.
The full E2E suite (7 test types, maybe 3-5 scenarios each) takes 5-15 minutes.

This is fast enough to run on every lockfile change, which is the trigger from [doc 03](03-evolution-and-safety.md).

---

## The Testing Platform Architecture

### Built-In, Not Developer-Created

The key difference from traditional software testing: **the agent developer writes zero tests.**

| What | Who Creates It | How |
|---|---|---|
| Contract tests | The platform | Auto-generated from manifest.yaml declarations |
| Integration replay fixtures | The platform | Auto-recorded from successful task sessions |
| E2E smoke scenarios | The platform | Auto-generated from composition artifact declarations |

The developer writes blocks and compositions with manifests.
The platform generates and runs tests from those manifests and from recorded usage.

This is possible because our architecture (doc 01) has **typed interfaces** and **declarative wiring**.
In traditional software, the interfaces are implicit in the code and the wiring is procedural — you cannot auto-generate integration tests because you do not know how the pieces connect.
In our Lego architecture, the interfaces are in manifest.yaml and the wiring is in composition artifacts — the platform knows everything it needs to generate tests.

### When Each Tier Runs

| Event | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|
| Block version published | ✅ | | |
| Lockfile change proposed | ✅ | ✅ | ✅ |
| Before lockfile promotion (doc 03) | ✅ | ✅ | ✅ |
| Scheduled (nightly) | | ✅ | ✅ |
| On demand | ✅ | ✅ | ✅ |

### Connection to Doc 03 Admission Gates

The five admission gates from [doc 03](03-evolution-and-safety.md) map to:

| Gate | Testing Tier |
|---|---|
| Syntax/AST check | Tier 1 (contract tests cover interface validity) |
| Static security scan | Separate — not a test tier |
| Targeted tests | Tier 2 (replay tests for the specific changed block) |
| Full regression suite | Tier 2 (all replays) + Tier 3 (full E2E smoke) |
| Multi-model review | Separate — not a test tier |

The testing platform is what makes the "targeted tests" and "regression suite" gates concrete.
Without it, those gates are empty words.

---

## What About Test Quality?

### The Tests Are Only as Good as the Recordings

Integration replay tests come from recorded sessions.
If the recordings only cover research tasks, the replay suite has zero coverage for coding tasks.

**Mitigation**: the platform tracks coverage by task category.
If a block is used in categories that have no recordings, it flags: "no integration test coverage for web_scraper in coding tasks."
This is the same coverage signal from [doc 04](04-measurement.md) — the attribution model already tracks per-block x task-category metrics.

### The Cheap Model Finds Different Bugs Than the Real Model

A 14B model on Ollama will:
- Make more tool call errors (testing error recovery)
- Get stuck more often (testing stuck detection)
- Produce worse outputs (testing output validation)
- Exceed context windows faster (testing context bounding)
- Sometimes refuse to call tools at all (testing the "no tool use" nudge path)

These are all GOOD test scenarios.
They exercise code paths that the production model rarely triggers.

### Tests Can Become Stale

Recorded sessions age out as the agent evolves.
A session from 3 months ago may test block combinations that no longer exist.

**Mitigation**: the platform garbage-collects recordings older than N days (configurable, default 30) or recordings that reference retired block versions.
Fresh recordings continuously replace old ones as the agent handles new tasks.

---

## Software Engineering Ancestors

| Pattern | Source | How It Applies |
|---|---|---|
| **Consumer-driven contract tests** | Pact (2013) | Compositions declare expectations of deps, platform verifies |
| **Snapshot / golden file tests** | Jest, Go testdata | Recorded task sessions are golden files |
| **VCR / HTTP recording** | Ruby vcr, Python vcrpy | Record LLM + tool interactions, replay in tests |
| **Database migration tests** | Alembic, Flyway | Swap lockfile on recorded data, verify still works |
| **Record-and-replay** | Playwright, Cypress | Record agent interactions, replay as integration tests |
| **Chaos engineering** | Netflix Simian Army (2011) | Cheap model as chaos monkey — stress-tests error handling |
| **Fuzz testing** | AFL, libFuzzer | Non-deterministic LLM inputs find edge cases mocks miss |
| **Compiler bootstrapping** | GCC, Rust | Test with a simple tool first, then use the real one |
| **Canary testing** | Kubernetes, Spinnaker | Run tests before promoting candidate lockfile |
| **Coverage tracking** | Istanbul, Coverage.py | Track which task categories have replay coverage |
| **Property-based testing** | QuickCheck, Hypothesis | The "property" is "the architecture does not crash." The Ollama model generates the diverse inputs. |
