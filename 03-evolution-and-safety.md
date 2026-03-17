# Evolution and Safety

## Why Evolution Needs Safety

Every self-improving agent eventually breaks itself.
The evidence from the research is unambiguous:

- [Godel Agent](../research/concepts/self-improvement-architectures/07-godel-agent.md) — `exec()` + `setattr()` in globals scope. A bad mutation corrupts the entire runtime. No persistent audit trail. No rollback. If the process crashes, all mutations since the last snapshot are lost.
- [BabyAGI](../research/concepts/self-improvement-architectures/04-babyagi.md) — unrestricted `exec()` with automatic pip install, global secret injection, no validation, no sandbox. A generated function is callable immediately after registration. The only guard is a `visited` set preventing same-chain recursion. The least safe architecture in the study.
- [Ouroboros](../research/concepts/self-improvement-architectures/05-ouroboros.md) — git-based modification with pre-push tests. Better, but if a restart loads broken code, the agent must manually diagnose and fix it. No automatic rollback.
- [EloPhanto](../research/concepts/self-improvement-architectures/08-elophanto.md) — pre/post test gates with automatic rollback on failure. The best single-agent safety model, but review is advisory (not blocking), and test quality determines safety.

The pattern: **the faster the mutation cycle, the easier it is to break things**.
Godel Agent iterates in milliseconds but has no safety net.
DGM takes hours per mutation but uses Docker isolation + benchmark gating.
We want the speed of Godel Agent with the safety of DGM.

The solution is well-established in software engineering: **immutable versioned artifacts with atomic deployment**.

---

## Relationship to Doc 01 and Doc 02

This document refines concepts from the two previous architecture documents:

- [Doc 01 — Architecture Draft](01-architecture-draft.md) defines the runtime: blocks, loop controllers, compositions.
  Doc 03 adds: Layer 0 is a **protected core** that cannot be self-modified. Layer 1+ blocks are **versioned**. The active agent configuration is a **lockfile** (a flat resolved list of block versions).

- [Doc 02 — Knowledge as Code](02-knowledge-as-code.md) defines three artifact types (tools, strategies, compositions) stored as Python modules.
  Doc 03 refines: the Knowledge Store becomes a **versioned** store. Each artifact has SemVer. Multiple versions coexist on disk. The Learning Loop produces a **new version**, not an overwrite.

The three docs form a progression: **structure** (doc 01) → **content** (doc 02) → **evolution** (doc 03).

---

## Four Mutation Levels

Every self-improving agent must answer: **how does the mutation reach the running system?**
The six studied projects implement four distinct answers, from the [pattern atlas](../research/concepts/self-improvement-architectures/02-pattern-atlas.md):

### Level 1: Artifact Growth

New plugin/skill/function written alongside the agent, discovered by a loader.
The agent's core code does not change — only its capability surface grows.
This handles ~80% of self-improvement needs.

Maps to doc 02's three artifact types: tool artifacts, strategy artifacts, composition artifacts.

Studied implementations:
- [OpenClaw skills](../research/concepts/self-improvement-architectures/03-openclaw.md) — SKILL.md + scripts, six-root precedence merge, hot-reload
- [EloPhanto plugin creation](../research/concepts/self-improvement-architectures/08-elophanto.md) — 7-stage pipeline with DevelopmentBudget
- [BabyAGI function registry](../research/concepts/self-improvement-architectures/04-babyagi.md) — SQLite-backed versioned functions with dependency graphs

### Level 2: Source Rewrite

Agent's own source code edited, committed, activated by restart or reload.
Needed when the agent must change how existing functionality works — not just add a new tool, but modify an existing block's behavior.

Maps to modifying Layer 1 blocks from doc 01 (ContextBoundary, StuckDetector, etc.).

Studied implementations:
- [Ouroboros git-based modification](../research/concepts/self-improvement-architectures/05-ouroboros.md) — commit + pre-push pytest + multi-model review + restart gate
- [EloPhanto self_modify_source](../research/concepts/self-improvement-architectures/08-elophanto.md) — pre/post test gates, automatic rollback, PROTECTED_PATHS

### Level 3: Population Evolution

Multiple agent variants spawned in containers, evaluated on benchmarks, best admitted to an archive.
For high-risk architectural changes where you want measured improvement, not just "it doesn't crash."

Maps to EvolutionaryLoop from doc 01.

Studied implementation:
- [DGM Darwinian evolution](../research/concepts/self-improvement-architectures/06-dgm.md) — o1 diagnoses, Claude implements in Docker, SWE-bench gates archive admission

### Level 4: Runtime Patch

Live objects rebound in the running process.
Fastest possible iteration — useful for experimentation, never for production.

Studied implementation:
- [Godel Agent monkey-patching](../research/concepts/self-improvement-architectures/07-godel-agent.md) — `exec()` + `setattr()`, no restart, no git, no review

### Risk Ladder

From the [safety ladder](../research/concepts/self-improvement-architectures/02-pattern-atlas.md):

1. BabyAGI — `exec()` with auto pip install, no validation, no sandbox
2. Godel Agent — `exec()` + `setattr()` in same process, no review
3. OpenClaw — skill artifacts with security scan, but scripts not sandboxed before activation
4. Ouroboros — git + pre-push tests + multi-model review, but gates are prompt-level
5. EloPhanto — pre/post test gates with auto-rollback + protected files, but review is advisory
6. DGM — Docker isolation + multi-tier benchmark gating (strictest quantitative gate)

Our architecture should combine: the speed of Level 1 for most changes, the durability of Level 2 for core modifications, and the safety of Level 3 for architectural changes.
Level 4 exists only inside an isolated experimental sandbox.

---

## Immutable Versioned Blocks

### The Core Model

This refines the Knowledge Store from [doc 02](02-knowledge-as-code.md) by adding immutable versioning.

Every block version is **immutable once published**.
`web_scraper@1.0.0` never changes.
If you want to fix it, you publish `web_scraper@1.0.1`.

Multiple versions **coexist on disk**.
Nothing is deleted until explicitly retired.
This is the property that makes rollback instant — you don't need to restore anything, just point to the old version.

```
knowledge/
  blocks/
    tools/
      web_scraper/
        1.0.0/
          tool.py
          test_tool.py
          manifest.yaml    # deps: []
        1.1.0/
          tool.py
          test_tool.py
          manifest.yaml    # deps: []
        2.0.0/
          tool.py
          test_tool.py
          manifest.yaml    # deps: [pdf_parser@^1.0]
    strategies/
      research_context_boundary/
        0.1.0/
          strategy.py
          manifest.yaml
        0.2.0/
          strategy.py
          manifest.yaml
    compositions/
      deep_research_agent/
        1.0.0/
          composition.py
          manifest.yaml    # deps: [web_scraper@^2.0, research_context_boundary@^0.2]

  lockfiles/
    current.lock           # the active configuration
    2026-03-14T21-00.lock  # previous (instant rollback target)
    2026-03-14T19-30.lock  # older

  index.db                 # semantic index across all versions
```

### Why Immutability

The alternative — overwrite-in-place — is what most studied projects do:
- OpenClaw overwrites SKILL.md files in place
- Ouroboros overwrites source files and commits
- Godel Agent overwrites live objects

Overwrite-in-place creates two problems:
1. **Rollback requires restoration** — you must have saved the old version somewhere and restore it.
2. **Cross-dependency breakage** — if block A@old depends on block B@old, and you overwrite B with B@new (which has a different interface), A breaks silently.

Immutability solves both: old versions are always on disk, and old blocks always see the versions they were tested with.

### Semantic Versioning

Following [npm/cargo conventions](https://semver.org/):

- **MAJOR** (2.0.0) — breaking interface change. Blocks depending on `^1.x` will not auto-upgrade.
- **MINOR** (1.1.0) — new capability, backward compatible. Blocks depending on `^1.0` will auto-upgrade.
- **PATCH** (1.0.1) — bug fix, backward compatible. Always auto-upgraded.

This is critical for composition artifacts: `deep_research_agent@1.0.0` declares `deps: [web_scraper@^2.0]`, meaning "any 2.x version." When `web_scraper@2.1.0` is published, the composition automatically uses it. When `web_scraper@3.0.0` appears (breaking change), the composition stays on 2.x until explicitly updated.

---

## Dependency Resolution

### How Blocks Declare Dependencies

Every block's `manifest.yaml` declares its dependencies with version ranges:

```yaml
name: deep_research_agent
version: 1.0.0
type: composition
description: "Multi-phase research agent with supervisor-subagent pattern"
deps:
  - web_scraper: "^2.0"
  - research_context_boundary: "^0.2"
  - pdf_parser: ">=1.0, <3.0"
```

### The Lockfile as Active Configuration

The lockfile (`current.lock`) is a flat resolved list of exact versions that defines the running agent:

```yaml
# current.lock - resolved 2026-03-14T21:00:00Z
web_scraper: 2.1.0
pdf_parser: 1.3.0
research_context_boundary: 0.2.1
deep_research_agent: 1.0.0
api_error_recovery: 0.1.0
```

Every block loaded at runtime comes from this lockfile.
Changing the lockfile is the **only** way to activate a new version.
This is the atomic deployment boundary — the running agent is completely defined by one file.

### Diamond Dependency Handling

If block A depends on `utils@^1.0` and block B depends on `utils@^1.2`, the resolver picks `utils@1.2.x` (highest compatible).
If block A depends on `utils@^1.0` and block B depends on `utils@^2.0`, this is a conflict — the resolver flags it and refuses to create the lockfile.
The agent must either upgrade A to work with utils@2.x or keep two separate lockfile profiles.

This is exactly how npm and cargo handle it.

---

## The Admission Pipeline

Before any mutation reaches the running agent, it must pass through gates.
Not every mutation needs every gate — the gates scale with risk level.

### Five Admission Gates

| Gate | What It Catches | Reference |
|---|---|---|
| **Syntax/AST check** | Malformed code, missing imports | [BabyAGI AST parameter parsing](../research/concepts/self-improvement-architectures/04-babyagi.md) |
| **Static security scan** | Shell execution, eval, credential access, network exfiltration | [OpenClaw skill-scanner](../research/concepts/self-improvement-architectures/03-openclaw.md) — line rules + source rules |
| **Targeted tests** | Functional correctness for the specific mutation | [EloPhanto test+fix loop](../research/concepts/self-improvement-architectures/08-elophanto.md) — Stage 4 of plugin creation |
| **Full regression suite** | Regressions across the entire agent | [EloPhanto pre/post test gates](../research/concepts/self-improvement-architectures/08-elophanto.md) on core modification |
| **Independent multi-model review** | Systematic biases, security issues, design violations | [Ouroboros multi-model adversarial review](../research/concepts/self-improvement-architectures/05-ouroboros.md) — 2-3 rival LLMs |

### Gates Per Risk Level

| Artifact Type (from doc 02) | Mutation Level | Required Gates |
|---|---|---|
| Tool artifact | Level 1 (artifact growth) | Syntax + security + targeted tests |
| Strategy artifact | Level 1 (artifact growth) | Syntax + security + targeted tests + regression suite |
| Composition artifact | Level 1 (artifact growth) | All five gates |
| Existing block modification | Level 2 (source rewrite) | All five gates + auto-rollback on regression failure |
| Architectural change | Level 3 (population evolution) | All five gates + benchmark scoring in container |
| Experimental prototype | Level 4 (runtime patch) | None — sandbox only, never reaches production |

---

## The Activation Boundary

Separating "mutation created" from "mutation active."
No mutation becomes active as a side effect of creation.

### The Deployment Workflow

1. **Write** new version directory (immutable once written)
2. **Run admission gates** (per risk level above)
3. **Create candidate lockfile** — copy `current.lock`, update the one block version, resolve dependencies
4. **Integration test** — boot the agent from the candidate lockfile in a sandbox, run the full test suite
5. **Swap** — atomically replace `current.lock` with the candidate
6. **Verify** — the running agent loads the new configuration on next cycle (hot-reload) or restart

### Hot-Reload vs Restart

Tool and strategy artifacts: **hot-reload**.
The filesystem watcher detects the lockfile change, reloads affected blocks.
No restart needed.
Inspired by [OpenClaw chokidar watcher](../research/concepts/self-improvement-architectures/03-openclaw.md) — debounced version bumping, next agent cycle picks up changes.

Composition artifacts and core modifications: **restart with interlock**.
Inspired by [Ouroboros last_push_succeeded flag](../research/concepts/self-improvement-architectures/05-ouroboros.md) — the agent cannot restart until the new lockfile has been committed and tested.

### Erlang-Style Version Coexistence

For hot-reloaded blocks, the old version stays active for in-progress operations.
New operations use the new version.
This is the [Erlang/OTP hot code loading](https://www.erlang.org/doc/system/code_loading.html) model: old processes finish on old code, new processes start on new code.
Applied to our architecture: an in-progress DirectLoop iteration finishes with the old ContextBoundary version, the next iteration uses the new one.

---

## Rollback Primitives

### Instant Rollback: Lockfile Swap

If the new configuration breaks at runtime:
1. Copy the previous lockfile back: `cp 2026-03-14T21-00.lock current.lock`
2. The agent loads the previous configuration on next cycle/restart

Both versions are still on disk.
Nothing needs to be restored, rebuilt, or re-downloaded.
This is the key benefit of immutability.

### Targeted Rollback: Single Block Revert

If one specific block is broken:
1. Edit `current.lock` to downgrade just that block: `web_scraper: 2.1.0` → `web_scraper: 2.0.0`
2. Re-resolve dependencies (check for conflicts)
3. Activate the updated lockfile

Everything else stays on the new version.
Only the broken block reverts.

### Auto-Rollback: Circuit Breaker

Inspired by [EloPhanto automatic rollback](../research/concepts/self-improvement-architectures/08-elophanto.md) — if post-change tests fail, the change is rolled back automatically.

Applied to our versioning model:
1. After lockfile swap, a health check runs
2. If the health check fails N times (configurable), the circuit breaker trips
3. The previous lockfile is automatically restored
4. The failed version is flagged in the index (not deleted — for diagnosis)

### Canary Deployment

For high-risk changes, gradual promotion:
1. Route 10% of tasks to the new lockfile, 90% to the old
2. Monitor ValueFunction scores for both
3. If the new version scores well, promote to 50%, then 100%
4. If it scores poorly, auto-rollback to 0%

Inspired by Kubernetes canary deployments and [DGM's fitness-proportional selection](../research/concepts/self-improvement-architectures/06-dgm.md) — variants must prove themselves before full adoption.

### Variant Fallback

For architectural changes, maintain an archive of known-good lockfiles:
1. The agent keeps the last N lockfiles (with timestamps and performance scores)
2. If the current configuration degrades, the system can fall back to any historical lockfile
3. This is the [DGM archive pattern](../research/concepts/self-improvement-architectures/06-dgm.md) applied to configurations rather than code patches

---

## Memory Security

### Why Memory Is an Attack Surface

Memory poisoning is no longer theoretical.
Microsoft discovered 31 companies across 14 industries commercially deploying memory poisoning — hidden instructions in "Summarize with AI" buttons that inject persistent memory commands.
OWASP 2026 lists Memory and Context Poisoning as risk ASI06 in the Top 10 for Agentic Applications.
MINJA (arXiv:2503.03704) achieves >95% injection success via query-only interaction — any user of a shared agent can become an attacker.
See [persistent memory research](../research/external/2026-03-17-persistent-memory-research-1.md) for the full attack landscape.

Any system that stores persistent knowledge — including our Knowledge Store — inherits these risks.

### Three Baseline Protections

**1. Provenance tracking.**
Every artifact in the Knowledge Store records: who created it (which agent, which subagent), from what source (user input, tool output, web scraping, internal generation), via what process (Learning Loop extraction, GEPA optimization, manual creation), and when.
Provenance is immutable — it cannot be modified after creation.
This enables tracing any suspicious artifact back to its origin.

**2. Trust scoring.**
Artifacts from trusted sources (successful tasks with user acceptance, multi-model-reviewed compositions) get higher trust than artifacts from untrusted sources (web scraping results, user-provided files, third-party tool outputs).
Trust scores influence:
- Search ranking — higher-trust artifacts are preferred in retrieval
- Admission gates — untrusted artifacts require more gates before activation
- Error attribution — when a task fails, low-trust artifacts are suspected first

**3. Utility-based lifecycle with temporal decay.**
Every artifact gets a utility score updated on every access (from AMV-L, arXiv:2603.04443).
Artifacts that have not been used or validated decay in utility over time.
GitHub Copilot's 28-day auto-expiry is a simple version of this.
Our version is richer: since artifacts are Python modules, we profile their actual invocation frequency.
Declining-utility artifacts are flagged for review; zero-utility artifacts are candidates for retirement; negative-utility artifacts (correlated with task failures) are flagged for removal.

### The Admission Gate as Primary Quality Mechanism

The most important empirical finding from the persistent memory research: **indiscriminate memory reliably degrades performance** (Xiong et al., arXiv:2505.16067).
Agents strongly mimic retrieved memories when similarity is high, creating error propagation and misaligned experience replay.
Only strict selective addition with evaluation improved performance.

This means our five admission gates from above are not just safety features — they are the PRIMARY quality mechanism.
What you choose NOT to remember matters more than how you organize what you do remember.
A-MAC (arXiv:2603.04549) adds anti-hallucination gating: without filtering, agents store and retrieve fabricated information, compounding errors.

The Learning Loop from [doc 02](02-knowledge-as-code.md) must include quality validation at every extraction step, not just at the artifact-publishing boundary.
Nemori's Predict-Calibrate pattern (extract only genuinely new knowledge by comparing against predictions from existing knowledge) is the recommended quality gate — it naturally filters redundant and low-signal information.

## Protected Core

### What Cannot Be Self-Modified

From [EloPhanto's PROTECTED_PATHS](../research/concepts/self-improvement-architectures/08-elophanto.md): certain infrastructure must be immutable from self-modification.

Mapped to doc 01's architecture:

| Protected | Why |
|---|---|
| **EventBus** (Layer 0) | All blocks communicate through it. If corrupted, everything breaks. |
| **Store** (Layer 0) | All state lives here. If corrupted, data loss. |
| **LLMClient** (Layer 0) | If corrupted, the agent cannot think. Godel Agent correctly protects its LLM call functions. |
| **The versioning system itself** | Lockfile resolution, admission gates, rollback primitives. If the agent can modify its own safety system, safety is meaningless. |
| **The protection list** | Must include itself. Prevents meta-level manipulation where the agent removes items from the protected list before modifying them. |

Everything above Layer 0 is versioned and mutable through the admission pipeline.
Layer 0 and the versioning infrastructure are **not addressable** by the mutation tools.

---

## Self-Evaluation as Feedback Loop

The agent needs to know WHAT to improve.
This maps to the ValueFunction block from doc 01, but applied to mutations rather than task actions.

### Four Evaluation Modes

| Mode | When | What | Reference |
|---|---|---|---|
| **Pre/post test gates** | Every mutation | Did the change break anything? | [EloPhanto modifier](../research/concepts/self-improvement-architectures/08-elophanto.md) |
| **Multi-model adversarial review** | Strategy + composition artifacts | Does the change make sense to rival LLMs? | [Ouroboros multi_model_review](../research/concepts/self-improvement-architectures/05-ouroboros.md) — 2-3 rival LLMs via OpenRouter |
| **Benchmark gating** | Architectural changes | Did the change measurably improve performance? | [DGM multi-tier evaluation](../research/concepts/self-improvement-architectures/06-dgm.md) — small, medium, full cascade |
| **Runtime performance monitoring** | Continuously after deployment | Is the new version actually better in production? | [Factory Signals LLM-as-judge](../research/concepts/self-improving/03-self-evaluation.md) — session friction analysis |

### What Gets Measured

From [Ouroboros 7-layer self-evaluation stack](../research/concepts/self-improving/03-self-evaluation.md):
- Health invariants (automated anomaly detection — version desync, budget drift, duplicate processing)
- Codebase health (complexity metrics — oversized modules, long functions)
- Drift detection (behavioral anti-patterns — task queue mode, permission mode, amnesia)

From [Factory Signals](../research/concepts/self-improving/03-self-evaluation.md):
- Friction detection (error events, repeated rephrasing, escalation tone, abandoned tool flows)
- Delight identification (first-attempt successes, efficiency comments)
- Autonomous category evolution (new friction/delight types discovered via embedding clustering)

These signals feed into the Learning Loop from doc 02: the agent identifies what to improve, creates a new block version, runs it through the admission pipeline, and deploys it via lockfile swap.

---

## Software Engineering Ancestors

These problems are ancient.
The solutions are well-established.

| Pattern | Source | How It Applies |
|---|---|---|
| **Semantic versioning** | [npm](https://semver.org/), cargo, pip | `MAJOR.MINOR.PATCH` — breaking changes bump major, features bump minor, fixes bump patch |
| **Version ranges in deps** | npm `^1.0.0`, cargo `~1.0` | Compositions declare compatibility range, auto-pick latest within range |
| **Lockfiles** | npm `package-lock.json`, pip-tools `requirements.txt`, cargo `Cargo.lock` | Flat resolved version list = the running agent's complete configuration |
| **Content-addressed storage** | Nix, Git objects | Each block version addressed by content hash — integrity verification for free |
| **Hot code swap with version coexistence** | [Erlang/OTP](https://www.erlang.org/doc/system/code_loading.html) | Old loops finish on old block version, new loops start on new version. No restart for compatible changes |
| **Up/down migrations** | Alembic, Flyway, Django migrations | Strategy artifacts that change state format need migration scripts between versions |
| **Feature flags** | LaunchDarkly, Unleash | Gradually activate new block version for a subset of tasks before full rollout |
| **Blue/green deployment** | Kubernetes, AWS CodeDeploy | Two complete lockfiles active simultaneously, switch traffic atomically |
| **Canary deployment** | Kubernetes, Istio | Route small percentage to new lockfile, promote based on health metrics |
| **Circuit breaker** | Hystrix, resilience4j, Polly | If a new block version fails N times, automatically fall back to previous version |
| **Immutable infrastructure** | Docker images, Nix derivations | Published versions never change. Fix by publishing a new version, not by patching in place |
| **Dependency resolution with SAT solver** | npm, cargo, Nix | Resolve compatible version set across all blocks, detect conflicts before deployment |

The key insight: the agent architecture community has been reinventing package management, deployment pipelines, and version control — poorly.
[Ouroboros uses git](../research/concepts/self-improvement-architectures/05-ouroboros.md) but without lockfiles.
[BabyAGI uses SQLite versioning](../research/concepts/self-improvement-architectures/04-babyagi.md) but without dependency resolution.
[DGM uses patch chains](../research/concepts/self-improvement-architectures/06-dgm.md) but without SemVer compatibility ranges.

We should use the real thing.
