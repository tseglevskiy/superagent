# Tier-1 Repo Synthesis — What We Get From Nemori, A-MEM, GEPA, FoldAgent

Four Tier-1 repos from the research corpus have been fully written up.
This document maps specific implementation patterns from each to our superagent architecture docs (01-08), identifying what we can directly adopt, what needs adaptation, and what changes our design.

---

## Product-by-Product Analysis

### Nemori — Predict-Calibrate for Knowledge Extraction

**What it is:** A Python library that converts raw conversations into a dual-store memory (episodic narratives + semantic knowledge statements) via a three-module pipeline.

**What we get:**

1. **Predict-Calibrate as the Learning Loop's knowledge extraction mechanism (doc 02, Step 2-3).**
   Our current Learning Loop says "evaluate what was novel" then "extract the reusable part" — but does not specify HOW to distinguish genuinely new knowledge from redundant repetition.
   Nemori solves this: retrieve relevant existing knowledge, predict what the episode should contain, then extract ONLY the delta.
   The ablation evidence is direct: prediction-driven extraction scores 0.615 vs naive extraction at 0.518 on LoCoMo — an 18.7% improvement from the same data.
   
   **Adoption path:** When the Learning Loop extracts a new artifact (tool, strategy, or composition), first retrieve the top-k most similar existing artifacts from the Knowledge Store.
   Feed them to the LLM as "what we already know."
   Then ask: "given what we already know, what is genuinely new in this session?"
   This prevents the Knowledge Store from accumulating redundant near-duplicate artifacts — the exact problem SkillsBench warns about.

2. **Episode segmentation with non-consecutive indices for domain boundary detection (doc 07, Scenario 5).**
   Nemori's `BatchSegmenter` groups messages by topic coherence, not chronological position.
   Messages [1, 2, 8] might form one episode (restaurant discussion) while [3, 4, 5] form another (coding).
   This is exactly what our DomainProfile discovery needs: when the agent's session mixes topics (coding + statistics + marketing), the segmenter identifies which messages belong to which domain — even when they are interleaved.
   
   **Adoption path:** Use Nemori-style batch segmentation as the first step of domain discovery.
   After each session, segment the conversation by topic.
   Each topic group maps to a candidate domain.
   Over time, recurring topic groups crystallize into DomainProfiles.

3. **Dual-store architecture maps to our Knowledge Store's need for both episodes and distilled knowledge.**
   Nemori keeps episodic memories (narrative summaries of what happened) AND semantic memories (atomic knowledge statements like "the user works at ByteDance as a senior ML engineer").
   Our Knowledge Store (doc 02) currently stores only artifacts (tools, strategies, compositions).
   It has no equivalent of episodic memory — no record of WHAT HAPPENED, only WHAT WAS LEARNED.
   
   **Adoption path:** Add a session trace store alongside the artifact store.
   Session traces are the "episodes" — compressed summaries of what the agent did and why.
   Artifacts are the "semantic memories" — distilled reusable knowledge extracted from episodes.
   The Predict-Calibrate engine bridges the two: episodes are the raw material, artifacts are the refined output.

4. **The cold-start path is the default for new domains.**
   When no relevant semantic memories exist (first episode on a new topic), Nemori bypasses prediction entirely and does direct extraction.
   Our DomainProfiles (doc 07) have the same cold-start problem: the first time the agent encounters a new domain, there is no existing knowledge to predict against.
   Nemori's solution is clean: detect empty retrieval, skip prediction, extract directly.
   Once there IS prior knowledge, switch to predict-calibrate.

5. **Temporal resolution during episode generation (not retrieval).**
   Nemori converts "yesterday" to "June 15, 2023" during episode creation, not during search.
   This is a general principle: resolve ambiguous references at WRITE time, not at READ time.
   Our artifacts should do the same: when extracting a tool or strategy, resolve relative references ("this project," "the current model") to absolute values.

**What we do NOT adopt:**
- The BM25 + vector hybrid search — our Knowledge Store already plans hybrid search (doc 02).
  Nemori's specific implementation (separate ChromaDB collections per user per type, spaCy tokenization) is too coupled to their domain.
- The episode merging mechanism — merging similar episodes adds complexity for marginal benefit (the paper's own ablation shows episodic memory contributes more than semantic, and merging operates on the less important layer).
- JSONL storage — we use versioned directories with manifest.yaml (doc 03).

---

### A-MEM — Zettelkasten Linking for Knowledge Organization

**What it is:** A memory system where adding a new memory triggers LLM-driven link generation and neighbor metadata updates, creating an emergent knowledge graph.

**What we get:**

1. **"Add triggers reorganize" pattern for the Knowledge Store (doc 02).**
   In A-MEM, adding a new memory is NOT just storage — it is an active reorganization step.
   The LLM decides: should this new memory link to existing ones?
   Should existing memories update their metadata based on the new information?
   
   Our Knowledge Store (doc 02) currently treats storage as passive: write the artifact, index it, done.
   A-MEM's pattern says: when a new tool artifact is stored, check its top-k neighbors in the index.
   Should the new tool's description reference related tools?
   Should existing tools update their descriptions to mention the new one?
   
   **Adoption path:** After storing a new artifact in the Knowledge Store, run a lightweight "reorganize" step:
   - Retrieve top-5 nearest artifacts by embedding similarity
   - Ask the LLM: should this new artifact link to any of them? Should any of them update their descriptions?
   - If yes, publish new PATCH versions of the affected artifacts with updated descriptions
   This keeps the Knowledge Store's semantic index self-organizing rather than relying solely on initial descriptions.

2. **CopiedChromaRetriever for multi-agent context isolation (doc 07, Scenario 1).**
   A-MEM's `CopiedChromaRetriever` creates a temporary isolated copy of a persistent collection.
   Multiple agents start from the same shared memory but diverge independently.
   This maps directly to our `inherit: blocks` mode from doc 07.
   
   **Adoption path:** When spawning a subagent with `inherit: blocks`, the child gets a copy-on-write snapshot of the parent's knowledge namespace.
   The child can add/modify knowledge within its copy without affecting the parent.
   When the child completes, its new knowledge is reviewed and optionally merged back (the "return" half of the fork).
   A-MEM's three-tier retriever hierarchy (in-memory, persistent, copied) maps to our three use cases: ephemeral subagents, persistent agents, and forked agents.

3. **Directed links as explicit semantic relationships beyond embedding similarity.**
   A-MEM's `search_agentic` follows link edges, not just embedding distance.
   A memory about "implementing an LRU eviction policy" retrieves memories about caching that the LLM previously linked — even if their embeddings are not close.
   
   Our Knowledge Store's current design (doc 02) relies entirely on semantic similarity for retrieval.
   A-MEM shows that explicit link structure captures relationships that embeddings miss.
   A tool for database migrations might not embed close to a tool for schema validation, but they are logically related.
   
   **Adoption path:** Add a `links` field to artifact manifests.
   When the reorganize step (point 1 above) fires, links are created between related artifacts.
   Retrieval follows both embedding similarity AND link traversal — if a tool is retrieved, its linked tools come along.
   This is cheap at retrieval time (dictionary lookups, no LLM calls).

4. **What A-MEM does NOT do is as instructive as what it does.**
   - No merge or deduplication — every `add_note` creates a new memory.
     Our architecture MUST deduplicate (SkillsBench warning).
     Nemori's Predict-Calibrate is the better approach here.
   - No content modification — the `content` field never changes, only `context`, `tags`, and `links`.
     This aligns with our immutability principle (doc 03) — published content is immutable, metadata evolves.
   - No embedding update on evolution — neighbor updates modify in-memory objects but NOT ChromaDB until consolidation every 100 evolutions.
     This is a bug in A-MEM but a feature for us: batch index rebuilds are more efficient than per-mutation updates.

5. **The t-SNE emergent clusters validate autonomous domain discovery (doc 07, Scenario 5).**
   A-MEM's link graph implicitly creates topic clusters visible in t-SNE visualizations.
   No programmatic cluster detection exists — the clusters emerge from the link structure.
   For our DomainProfile discovery, this suggests: let the link graph grow organically, then periodically run cluster detection over the graph to discover domain boundaries.
   This is complementary to Nemori's segmentation approach: Nemori discovers domains per-session, A-MEM discovers them over the accumulated knowledge graph.

**What we do NOT adopt:**
- The `all-MiniLM-L6-v2` embedding model — we should use whatever model the LLMClient is configured with.
- The consolidation mechanism (rebuild ChromaDB every N evolutions) — our versioned store with immutable artifacts avoids this problem entirely.
  Each artifact version has its embedding computed once at publish time.
- The `evo_threshold` counter approach — we should reorganize on every add (the cost is 1 LLM call, which is acceptable for knowledge store mutations that happen at task-completion frequency, not per-turn frequency).

---

### GEPA — The Strategy Mutation Engine

**What it is:** A genetic algorithm where LLMs serve as the mutation operator and a Pareto frontier over per-task-instance scores drives candidate selection.
ICLR 2026 Oral.

**What we get:**

1. **GEPA IS our Strategy mutation operator (doc 02, Layer 1).**
   Doc 02 lists four mutation operators for Strategy artifacts: OPRO, EvoPrompt, TextGrad, DSPy MIPROv2.
   Doc 08 already says "Replace multi-optimizer with GEPA."
   Now with the full writeup, the case is definitive:
   - GEPA outperforms all four on every benchmark
   - 35x fewer rollouts than GRPO
   - 33% shorter prompts (addresses the AGENTIF finding that <30% of instructions are followed)
   - Already integrated into DSPy, MLflow, Google ADK, Pydantic AI, Comet ML Opik
   - The `optimize_anything` API wraps any text parameter, not just prompts
   
   **Adoption path:** Replace the multi-optimizer section in doc 02 with GEPA as the primary operator.
   Keep DSPy MIPROv2 as fallback for environments where GEPA is not available.
   Drop OPRO, EvoPrompt, TextGrad as standalone options — GEPA subsumes them.

2. **The Pareto frontier maps to our per-task-category performance tracking (doc 04).**
   GEPA does not maintain a single "best" candidate — it maintains a frontier of candidates that each excel on different subsets of the validation set.
   This is exactly our attribution model's insight: a block might be excellent for research tasks but poor for coding tasks.
   GEPA's Pareto frontier preserves this diversity rather than collapsing to a single "globally best" version.
   
   **Adoption path:** When evolving Strategy artifacts, maintain a Pareto frontier per task category.
   The current lockfile might use `research_context_boundary@0.3.0` for research tasks and `research_context_boundary@0.2.1` for coding tasks — different optimal versions for different domains.
   This directly connects to doc 07's DomainProfiles: each domain's lockfile overlay can point to the Pareto-optimal version for that domain.

3. **The `optimize_anything` API wraps our ENTIRE evolution pipeline (doc 03).**
   `optimize_anything` takes a seed candidate (any text), an evaluator function, a dataset, and optimizes the text via reflective mutation + Pareto selection.
   
   This can wrap:
   - **Strategy artifacts:** the text is a system prompt, the evaluator runs the agent on a benchmark
   - **Tool descriptions:** the text is a tool's docstring, the evaluator measures retrieval accuracy
   - **Composition wiring:** the text is a composition's configuration, the evaluator runs E2E smoke (doc 06 Tier 3)
   - **FocusChain prompts:** the text is the plan-update prompt, the evaluator measures plan quality
   
   **Adoption path:** Implement a `SuperagentGEPAAdapter` (following the `GEPAAdapter` protocol) that:
   - Wraps any block's text parameters as the candidate
   - Uses the 8-metric scorecard (doc 04) as the evaluator
   - Captures full execution traces (for ASI-powered reflection)
   - Returns per-task-instance scores for Pareto tracking

4. **The gskill module IS our skill learning pipeline (doc 02, Learning Loop + doc 07, DomainProfiles).**
   gskill learns repository-specific skills for coding agents by running GEPA over SWE-bench tasks in Docker containers.
   Results: 24% to 93% on Bleve.
   Skills transfer cross-model: learned on gpt-5-mini, transferred to Claude Code Haiku 4.5 (79% to 100%).
   
   This validates three things simultaneously:
   - **Skills work** — contradicting SkillsBench, but with a crucial difference: gskill validates skills via benchmark, while SkillsBench measured self-authored skills with no validation.
     The quality gate is what makes the difference.
   - **Domain-specific skills** — gskill learns skills for a SPECIFIC repository (Bleve, Jinja).
     These are DomainProfile-scoped Strategy artifacts.
   - **Cross-model transfer** — skills learned with a cheap model work with expensive models.
     This means our evolution pipeline can use cheap models for exploration and expensive models for production.
   
   **Adoption path:** The Learning Loop's "Step 3: Extract the Reusable Part" should use gskill-style optimization:
   - After a domain accumulates enough task history, run GEPA with the domain's tasks as the dataset
   - The candidate is a Strategy artifact (system prompt additions for the domain)
   - The evaluator is the scorecard from actual task executions
   - The output is a validated, domain-specific Strategy artifact

5. **Actionable Side Information (ASI) is the key to rich evolution signals (doc 04).**
   GEPA's reflection LM does not just see "score = 0.7."
   It sees the FULL execution trace: reasoning chains, tool calls, tool outputs, error messages.
   This is what makes GEPA outperform gradient-based methods: the reflection LM can diagnose WHY a candidate failed, not just THAT it failed.
   
   Our measurement system (doc 04) records the 8-metric scorecard + LLM-as-judge analysis.
   But for GEPA-style evolution, we need to record the full execution trace — every tool call, every LLM response, every error.
   This is already planned in doc 06 (integration replay traces), but the traces need to be formatted as GEPA-compatible ASI.
   
   **Adoption path:** The session trace format (doc 06) should be compatible with GEPA's reflective dataset schema:
   `{"Inputs": ..., "Generated Outputs": ..., "Feedback": ...}` per component.
   This ensures traces recorded for testing (doc 06) can be directly reused for evolution (doc 02 + GEPA).

6. **The MCP adapter provides a direct integration path.**
   GEPA's `MCPAdapter` optimizes MCP tool descriptions and system prompts for any MCP-compatible agent.
   Since our ToolRegistry (doc 01) supports MCP servers, GEPA can optimize tool descriptions out of the box.
   
   **Adoption path:** Register GEPA's MCPAdapter as a built-in integration.
   When a new MCP tool is added to the ToolRegistry, GEPA can optimize its description for our specific agent's tool selection patterns.

7. **System-Aware Merge (crossover) maps to our composition evolution (doc 02, Layer 3).**
   GEPA periodically combines strengths of two Pareto-optimal candidates that excel on different tasks.
   For composition artifacts, this means: if Composition A is great for research but weak for coding, and Composition B is great for coding but weak for research, merge them into a hybrid that handles both.
   
   **Adoption path:** When evolving compositions, use GEPA's merge strategy: find pairs of compositions with complementary strengths (from Pareto frontier), combine their per-component best versions.

**What we do NOT adopt:**
- The round-robin component selector for multi-component systems — our evolution should be guided by the attribution model (doc 04), not round-robin.
  Focus mutations on the component that the attribution model identifies as the bottleneck.
- The refiner inner loop — adds complexity for marginal improvement on our use case.
  The main reflective mutation loop is sufficient.

---

### FoldAgent — Learned Tree Compression

**What it is:** An agent that actively manages its own working context through two learned tool calls: `branch(description, prompt)` and `return(message)`.
Trained via FoldGRPO with dense process rewards.

**What we get:**

1. **branch/return IS our Scenario 3, almost exactly (doc 07).**
   FoldAgent's architecture matches doc 07's tree compression:
   - Main thread = root of the plan tree (never compressed)
   - Each branch = a subtask node
   - `return(message)` = subtask completion with summary propagation
   - Folded content is permanently discarded = compression
   
   The match is close but not identical.
   Key differences:
   - FoldAgent is FLAT: main → branches, no branch → sub-branch.
     Our doc 07 envisions recursive tree compression (supported by ReCAP's arbitrary-depth proof).
   - FoldAgent DISCARDS folded content permanently.
     Our architecture might want to store it (in the session trace store) for later retrieval.
   - FoldAgent's branch inherits the FULL main thread history as prefix.
     This is our `inherit: full` mode from Scenario 1.
   
   **Adoption path:** Implement `branch` and `return` as FocusChain tools:
   - `branch(description, prompt)` = `plan_update(add_child)` + `spawn_subagent(inherit: full)`
   - `return(message)` = `plan_update(complete)` + return summary to parent
   - The flat two-level restriction should be configurable, not hardcoded.
     Start with flat (simpler, proven by FoldAgent), add nesting later (validated by ReCAP).

2. **FoldGRPO's three process rewards could train our FocusChain's decisions (future work).**
   The three rewards are:
   - **Unfolded Token Penalty (-1):** when the main context exceeds 50% of budget but the agent did not branch.
     Teaches: "you should have branched for that token-intensive work."
   - **Out-of-Scope Penalty (-0.2):** when a branch performs work outside its assigned task.
     Teaches: "stay focused on your subtask."
   - **Failure Penalty (-1):** when a tool call produces an error.
     Teaches: "do not generate malformed tool calls."
   
   For our architecture, these map to:
   - Penalize the agent when it accumulates too much working context without compressing (drives tree compression adoption)
   - Penalize subagents that go beyond their assigned scope (drives focused execution)
   - Penalize malformed tool calls (standard)
   
   **Adoption path (future):** If we train our own models or fine-tune, FoldGRPO's reward design is the template.
   For now, the same signals can be used as heuristic rules in the StuckDetector:
   - If main context exceeds 50% of budget and no subagent has been spawned, inject a nudge: "Consider using branch to offload this work."
   - If a subagent's work diverges from its assigned task (detectable by the LLM-as-judge), inject a redirect.

3. **The flat two-level hierarchy is a deliberate design choice, not a limitation.**
   FoldAgent explicitly prevents nesting: branches cannot call `branch` or `finish`.
   The paper says this is to "maintain a clear structure and prevent nested complexity."
   
   This is pragmatic wisdom: the 10x context reduction comes from ONE level of branching.
   ReCAP proves arbitrary depth works in theory, but FoldAgent proves one level suffices in practice.
   
   **Adoption path:** Our FocusChain should support nesting (because some tasks genuinely need it), but the DEFAULT should be flat (one level of branches).
   The agent should need to explicitly justify deeper nesting, and the StuckDetector should flag excessive depth as a potential anti-pattern.

4. **The `judge_scope` verifier is a per-subtask ValueFunction (doc 04).**
   FoldAgent uses GPT-5-nano to evaluate whether a branch stayed within scope.
   The judgment is independent of task success — a branch that fails but stays focused gets `<good>`, while one that succeeds but does extra work gets `<error>`.
   
   This maps to our ValueFunction block (doc 01): after each subagent completes, score it on scope adherence.
   The scope score feeds into the attribution model (doc 04): if a subagent goes out of scope, the failure is attributed to scope management, not to the block that executed within the branch.
   
   **Adoption path:** Add a "scope adherence" metric to the scorecard for subagent tasks.
   After a subagent returns, a lightweight LLM call evaluates: did the subagent stay within its assigned task?
   This is cheap (GPT-5-nano tier) and directly actionable.

5. **The 10x context reduction validates our core thesis (doc 07).**
   Main thread averages 8K tokens while processing 100K+ total across branches.
   This is the strongest empirical evidence that tree-structured context management works at scale.
   BrowseComp-Plus: 62.0% (matching ReAct baselines that use the full 327K context).
   SWE-Bench Verified: 58.0%.
   
   The number to remember: **10x context reduction with no quality loss on BrowseComp-Plus.**

6. **The Summary Agent baseline is what NOT to do.**
   FoldAgent's comparison baseline: when context hits 95%, summarize everything and reset.
   FoldAgent outperforms this by +20.0% on BrowseComp-Plus.
   This confirms doc 07's thesis: compress from the leaves (completed subtasks), not from the root (everything).
   
   **Adoption path:** Our ContextBoundary should never use global summarization as the primary strategy.
   Global summarization is the LAST resort fallback (when no plan tree exists).
   Tree compression (FocusChain-driven) is the primary strategy.

**What we do NOT adopt:**
- The XML tool calling format — we use native provider APIs via ToolRegistry (doc 01).
- The Caesar-cipher encoded examples — this is a training data leakage prevention hack, irrelevant to our architecture.
- The VeRL training infrastructure — this is specific to ByteDance's RL setup.
  The reward DESIGN is what we adopt, not the training framework.
- The `mask_rollout` mechanism — specific to RL training, not applicable to our lockfile-based evolution.

---

## Cross-Product Patterns

### Pattern 1: Predict-Before-Extract (Nemori) + Reorganize-On-Add (A-MEM) = Active Knowledge Store

Nemori says: before extracting new knowledge, predict what you should already know, then extract only the delta.
A-MEM says: when new knowledge arrives, reorganize existing knowledge in response.

Combined: our Knowledge Store becomes actively self-organizing.
When a new artifact is published:
1. **Predict:** retrieve related artifacts, predict what the new one should contain given existing knowledge
2. **Extract:** extract only genuinely new content (Nemori's Predict-Calibrate)
3. **Reorganize:** check if existing artifacts should update their descriptions or add links (A-MEM's evolution)
4. **Quality gate:** validate the new artifact actually helps (GEPA's evaluation, SkillsBench warning)

This is a four-step pipeline that replaces doc 02's current three-step Learning Loop (evaluate → extract → store).

### Pattern 2: GEPA Optimization + FocusChain Compression = Trained Context Management

GEPA can optimize any text parameter.
FoldAgent proves context management decisions can be learned.

Combined: use GEPA to optimize the prompts that drive FocusChain decisions:
- The prompt that tells the agent when to branch
- The prompt that tells the agent how to summarize a completed subtask
- The prompt that tells the agent when to compress vs when to keep full context

GEPA's evaluator measures: did the agent's context management decisions lead to better task outcomes (scorecard) with lower context usage (token count)?
The Pareto frontier maintains variants that trade off quality vs efficiency.

### Pattern 3: Domain Discovery (Nemori segmentation + A-MEM clustering) + Domain-Specific Skills (GEPA gskill)

Nemori discovers domain boundaries per-session via topic segmentation.
A-MEM discovers domain boundaries over accumulated knowledge via emergent link clusters.
GEPA's gskill learns domain-specific skills that dramatically improve performance.

Combined pipeline for DomainProfile lifecycle:
1. **Discover:** Nemori-style segmentation identifies recurring topic clusters (doc 07 Scenario 5)
2. **Crystallize:** when a cluster is stable, create a DomainProfile (doc 07)
3. **Optimize:** run GEPA gskill with the domain's task history as the dataset
4. **Deploy:** the optimized Strategy artifact goes into the DomainProfile's lockfile overlay
5. **Maintain:** A-MEM-style reorganization keeps the domain's knowledge graph current

### Pattern 4: FoldAgent Branching + A-MEM CopiedRetriever = Context-Isolated Subagents With Shared Knowledge

FoldAgent gives subagents the full conversation as prefix but isolated execution.
A-MEM's CopiedChromaRetriever gives subagents a copy of shared knowledge that they can modify independently.

Combined: our `inherit: blocks` mode (doc 07 Scenario 1) gets a concrete implementation:
- The subagent inherits FoldAgent-style conversation prefix (knows the context)
- The subagent gets an A-MEM-style copied knowledge store (can add/modify knowledge without affecting the parent)
- On return, new knowledge from the copy is reviewed and optionally merged back

---

## Specific Updates Per Architecture Doc

### Doc 01 — Architecture Draft

1. **Add `reorganize_on_add` behavior to Knowledge Store description.**
   Reference A-MEM's process_memory pattern: every store write triggers a neighbor check and optional metadata update.
   
2. **Add `scope_adherence` as a ValueFunction criterion.**
   Reference FoldAgent's `judge_scope` verifier: per-subtask scope evaluation, independent of task success.

3. **Strengthen FocusChain description with FoldAgent evidence.**
   The 10x context reduction and +20pp over summary baseline are the strongest empirical arguments for FocusChain as a Layer 1 block.
   Add: "FoldAgent (arXiv:2510.11967) proves that a flat two-level plan hierarchy achieves 10x context reduction with no quality loss, outperforming heuristic summarization by 20 percentage points."

### Doc 02 — Knowledge as Code

1. **Replace multi-optimizer section with GEPA as primary Strategy mutation operator.**
   GEPA outperforms OPRO, EvoPrompt, TextGrad, MIPROv2 on every metric.
   The `optimize_anything` API wraps any text parameter.
   Keep MIPROv2 as fallback only.

2. **Rewrite Learning Loop Steps 2-3 with Predict-Calibrate mechanism.**
   Step 2 (evaluate what was novel) becomes: retrieve related existing artifacts, predict what this session should have produced, identify the delta.
   Step 3 (extract the reusable part) becomes: extract only genuinely new content from the delta, not everything that looks useful.
   Reference Nemori's ablation: 18.7% improvement from prediction-driven extraction.

3. **Add Step 2.5: Reorganize existing artifacts.**
   After extracting new knowledge (Step 3), check neighbors and update their descriptions/links if the new artifact changes the context.
   Reference A-MEM's `process_memory` pattern.

4. **Add gskill as the Domain-Specific Strategy Learning Pipeline.**
   When a DomainProfile accumulates enough task history, run GEPA gskill:
   - Tasks as dataset, scorecard as evaluator, Strategy artifact as candidate
   - Results: validated domain-specific skills (not self-authored guesses)
   - Cross-model transfer: learn cheap, deploy expensive
   Reference gskill's Bleve results: 24% to 93%, transferring to Claude Code at 79% to 100%.

5. **Reference GEPA's Pareto frontier for multi-version Knowledge Store.**
   The Knowledge Store should not collapse to a single "best" version per artifact.
   Different tasks may need different versions.
   GEPA's Pareto frontier is the mechanism for maintaining this diversity.

### Doc 03 — Evolution and Safety

1. **Reference GEPA's acceptance gate for the admission pipeline.**
   GEPA's minibatch acceptance (sum of new scores > sum of old scores) is a lightweight pre-gate before full evaluation.
   Our admission pipeline should include: cheap minibatch test first, then full regression only for accepted candidates.

2. **Add A-MEM-style batch consolidation to the versioning system.**
   After N artifact mutations, rebuild the semantic index from scratch.
   This prevents index drift from accumulated incremental updates.
   A-MEM rebuilds ChromaDB every 100 evolutions; our threshold should be configurable.

### Doc 04 — Measurement

1. **Add scope adherence metric for subagent tasks.**
   FoldAgent's `judge_scope` provides the template: cheap LLM call, three-level verdict (good/fine/error), independent of task success.

2. **Record full execution traces in GEPA-compatible format.**
   Traces must include: reasoning chains, tool calls, tool outputs, error messages, per-component inputs/outputs.
   Format as GEPA's reflective dataset: `{"Inputs": ..., "Generated Outputs": ..., "Feedback": ...}` per component.
   This ensures traces serve double duty: testing (doc 06 Tier 2) and evolution (GEPA optimization).

3. **Add Pareto frontier tracking to per-block metrics.**
   Instead of tracking only the globally best version, track which version is best for which task category.
   Reference GEPA's four frontier types: instance, objective, hybrid, cartesian.

### Doc 05 — Parallel Evaluation

1. **GEPA's minibatch acceptance as a lightweight shadow mode.**
   Instead of full shadow execution (2x cost), evaluate candidate lockfiles on a small minibatch first (1.1x cost).
   Only proceed to full shadow evaluation for candidates that pass the minibatch test.
   This is GEPA's acceptance gate applied to lockfile promotion.

### Doc 06 — Testing Platform

1. **Reference GEPA's ASI for enriching Tier 2 replay traces.**
   Replay traces should capture not just inputs/outputs but also side information: error messages, profiler output, compiler traces.
   GEPA's `oa.log()` mechanism (thread-safe per-evaluator-call capture) is the implementation pattern.

2. **Add FoldAgent's `judge_scope` as a Tier 2 assertion.**
   After replaying a session that involved subagents, verify that each subagent stayed within its assigned scope.
   This catches regressions where a block change causes subagents to go out of scope.

### Doc 07 — Context Flow

1. **Scenario 1: Reference A-MEM's CopiedChromaRetriever for `inherit: blocks` mode.**
   Concrete implementation: the child gets a COW snapshot of the parent's knowledge namespace.

2. **Scenario 3: Strengthen with FoldAgent's specific implementation details.**
   branch/return as tool calls, flat two-level default, 10x measured context reduction.
   Add the comparison: FoldAgent achieves 62.0% on BrowseComp-Plus with 32K active context vs ReAct baseline needing 327K.

3. **Scenario 5: Add Nemori's batch segmentation as the per-session domain discovery mechanism.**
   Five signals for boundary detection: topic change, intent transition, temporal markers, structural signals, content relevance.
   Non-consecutive index support for interleaved topics.

4. **Scenario 5: Add A-MEM's emergent link clusters as the cross-session domain discovery mechanism.**
   Complementary to Nemori: segmentation discovers domains per-session, link clustering discovers them across sessions.

5. **Add Nemori's Predict-Calibrate as the knowledge extraction mechanism for DomainProfiles.**
   When a domain accumulates new session traces, extract domain knowledge using prediction-driven extraction.
   Cold-start path for new domains: direct extraction (no prediction).

### Doc 08 — Research Synthesis

1. **Move Nemori, A-MEM, GEPA, FoldAgent from Tier 2 (validates) to Tier 1 (changes) where applicable.**
   - GEPA is already Tier 1 (correct).
   - FoldAgent is already Tier 1 (correct).
   - Nemori should be Tier 1: the Predict-Calibrate mechanism changes our Learning Loop design.
   - A-MEM stays Tier 2: it validates our domain discovery but does not change the fundamental design.

2. **Add cross-product patterns (from this document) to the synthesis.**
   The four combined patterns (Active Knowledge Store, Trained Context Management, Domain Lifecycle, Context-Isolated Subagents) are integration insights that emerge from reading all four products together.

---

## Summary: What Changes

| Architecture Area | Before | After |
|---|---|---|
| Learning Loop knowledge extraction (doc 02) | "Evaluate what was novel" - unspecified | Predict-Calibrate mechanism from Nemori |
| Strategy mutation operator (doc 02) | OPRO / EvoPrompt / TextGrad / MIPROv2 | GEPA as primary, MIPROv2 as fallback |
| Knowledge Store on-write behavior (doc 02) | Passive - write and index | Active - reorganize neighbors on every add, A-MEM pattern |
| Domain-specific skill learning (doc 02 + 07) | Not specified | GEPA gskill pipeline with benchmark validation |
| Tree compression evidence (doc 07) | Theoretical - references to HiAgent, ReCAP | Empirical - FoldAgent 10x reduction, 62% BrowseComp-Plus |
| `inherit: blocks` implementation (doc 07) | Conceptual - "Letta shared blocks pattern" | Concrete - A-MEM CopiedChromaRetriever COW pattern |
| Domain discovery mechanism (doc 07) | "Clustering over task categories" | Two-layer: Nemori segmentation per-session + A-MEM link clustering cross-session |
| Subagent scope evaluation (doc 04) | Not specified | FoldAgent `judge_scope` pattern - cheap LLM call, three-level verdict |
| Execution trace format (doc 04 + 06) | Session trace with scorecard | GEPA-compatible reflective dataset for dual-use: testing + evolution |
| Flat vs recursive tree compression (doc 07) | "Tree-structured" - implied recursive | Flat two-level default (FoldAgent evidence), recursive as opt-in (ReCAP validation) |
