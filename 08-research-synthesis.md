# Research Synthesis — What We Learned and What Changes

Six research surveys produced ~200 papers across context inheritance, tree compression, domain discovery, meta-context strategy, prompt optimization, and testing for self-evolving agents.
This document maps findings to specific architecture decisions across docs 01-07.

## Key Papers by Impact on Our Architecture

### Tier 1: Changes Our Design

| Paper | What It Changes |
|---|---|
| **GEPA** (arXiv:2507.19457, ICLR 2026 Oral) | Replaces OPRO/EvoPrompt/TextGrad as primary Strategy mutation operator (doc 02). Reflective evolution on full trajectories + genetic algorithms + Pareto selection. Outperforms MIPROv2 by 10%+, produces 33% shorter prompts. Integrated into DSPy. |
| **FoldAgent** (arXiv:2510.11967) | Validates Scenario 3 tree compression (doc 07). `branch(description, prompt)` + `return(message)` as learned actions, trained via FoldGRPO. 10x context reduction, 58% on SWE-Bench Verified. |
| **Sculptor** (arXiv:2508.04664) | Validates Scenario 4 meta-context (doc 07). 8 context-management tools as agent actions. +49.3pp on interference benchmarks via zero-shot tool calling. No training needed. |
| **BATS** (arXiv:2511.17006, Google) | Adds budget awareness to ContextAssembler (doc 01). Injecting "budget remaining: X" into prompt yields 40% fewer search calls. "Agents without budget awareness hit a ceiling regardless of budget size." |
| **SkillsBench** (arXiv:2602.12670) | Adds quality gate to Learning Loop (doc 02). "Self-generated Skills provide NO benefit on average; curated Skills add 16.2pp." Agents cannot reliably author the procedural knowledge they benefit from consuming. |
| **ABC — Agent Behavioral Contracts** (arXiv:2602.22302) | Formalizes Tier 1 contracts (doc 06). C = (P, I, G, R) with probabilistic (p, δ, k)-satisfaction. Detects 5.2-6.8 soft violations per session that baselines miss. Overhead <10ms. |

### Tier 2: Validates Our Design

| Paper | What It Validates |
|---|---|
| **ReCAP** (arXiv:2510.23822, NeurIPS 2025) | Tree compression with recursive LLM calls, O(d·L̄) memory bound. Validates doc 07 Scenario 3 at arbitrary depth. |
| **PAACE** (arXiv:2512.16970) | Plan-conditioned compression. Formally conditions compression on next k plan steps. Validates doc 07 FocusChain-driven compression. |
| **HiAgent** (arXiv:2408.09559, ACL 2025) | Subgoal-as-compression-boundary. 2x success rate. Validates two-level tree compression. |
| **GCC** (arXiv:2508.00031) | Git-like context branching. Three tiers: main.md (never compressed) + commit.md + log.md. Validates root protection principle. |
| **Nemori** (arXiv:2508.03341) | Autonomous episode segmentation via LLM-powered boundary detection. Validates doc 07 Scenario 5 domain discovery. |
| **A-MEM** (arXiv:2502.12110, NeurIPS 2025) | Zettelkasten-inspired memory with emergent topic clusters. Validates autonomous domain organization. |
| **H-MEM** (arXiv:2507.22925) | Four-layer hierarchy: Domain → Category → Trace → Episode. Validates DomainProfile structure from doc 07. |
| **MemAct** (arXiv:2510.12635) | Context curation as RL-trained policy. 14B matches 16x larger models with 51% less context. Validates RL for strategy optimization. |
| **Block TestProvider** (blog, Jan 2026) | Production-grade record/replay for agent testing. Validates doc 06 Tier 2 exactly. |
| **ExpeL** (arXiv:2308.10144, AAAI 2024) | Different domains develop different expertise types. HotpotQA → insights, ALFWorld → trajectories. Validates per-domain composition. |

### Tier 3: Adds New Capabilities

| Paper | New Capability |
|---|---|
| **SGLang fork/join** (arXiv:2312.07104, NeurIPS 2024) | Zero-copy KV cache forking via RadixAttention. Makes `inherit: full` nearly free for shared prefix. 5x throughput. |
| **ContextBranch** (arXiv:2512.13914) | Four Git-like primitives with formal guarantees (branch isolation, checkpoint determinism, injection safety). 900 LOC Python SDK. |
| **ACON** (arXiv:2510.00615) | Task-aware compression for handoff. Failure-driven optimization. 26-54% token reduction. Distilled compressors retain 95%. |
| **ReliabilityBench** (arXiv:2601.06112) | 3D reliability surface R(k, ε, λ). "pass@1 overestimates reliability by 20-40%." Simpler ReAct beats complex Reflexion under stress. |
| **Invariant Labs** (ETH Zürich, open-source) | DSL for temporal ordering constraints on agent traces. Pytest-like assertions for agent behavior. |
| **Pro2Guard** (arXiv:2508.00500) | Formal verification via Markov Chains to PREDICT safety violations before they occur. PAC guarantees. |
| **AgentSpec** (arXiv:2503.18666, ICSE 2026) | Runtime enforcement DSL. Prevents unsafe executions in >90% of cases. Millisecond overhead. |
| **Chroma Context Rot** (research.trychroma.com) | Performance degrades universally with longer prompts. Hard ceiling on prompt complexity. |
| **AGENTIF** (arXiv:2505.16944, NeurIPS 2025) | <30% of agent system prompt instructions are perfectly followed. Task-solving and rule-following are partially decoupled. |
| **MaAS** (arXiv:2502.04180, ICML 2025 Oral) | Supernet over architectures — learn a distribution, not a single optimum. 75% cost reduction. |

---

## Updates Per Document

### Doc 01 — Architecture Draft

**Add FocusChain as Layer 1 block.**
All five scenarios in doc 07 require it.
HiAgent, FoldAgent, ReCAP, and PAACE all use plan-driven compression boundaries.
ReAcTree (arXiv:2511.02424) adds shared working memory across agent nodes.

**Add budget awareness to ContextAssembler.**
BATS proved injecting live resource counters changes agent behavior qualitatively — 40% cost reduction for free.
Letta already shows chars_current/chars_limit in block metadata.
Our ContextAssembler should always include: token usage, remaining budget, task progress from FocusChain.

**Add retrieval-based tool selection to ToolRegistry.**
RAG-MCP: 3x accuracy from not showing irrelevant tools.
Verdent ablation: minimal tools barely affect SWE-bench.
Claude Code defers MCP tools to MCPSearch when they exceed 10% of context.
Default should be deferred/search-based loading, not exhaustive listing.
Tool2Vec (arXiv:2409.02141): 27pp improvement in tool retrieval via usage-driven embeddings.

**Add AgentSpec-style runtime enforcement to InspectorPipeline.**
AgentSpec (ICSE 2026): trigger event + predicate + enforcement action.
Prevents unsafe executions in >90% of cases, millisecond overhead.
Pro2Guard: formal verification predicts violations BEFORE they occur.

### Doc 02 — Knowledge as Code

**Replace multi-optimizer with GEPA.**
GEPA (ICLR 2026 Oral) outperforms OPRO, EvoPrompt, TextGrad, MIPROv2 on every metric.
Produces 33% shorter prompts.
Already integrated into DSPy (`dspy.GEPA`), MLflow, Google ADK.
Keep DSPy MIPROv2 as fallback.

**Add SkillsBench quality gate warning.**
"Self-generated Skills provide no benefit on average; curated Skills add 16.2pp."
The Learning Loop (Step 2-3) MUST include quality validation beyond syntax/security.
Multi-model review from doc 03 should apply to ALL new artifacts, not just compositions.

**Reference validated implementations of each artifact type.**
Strategy mutations: GEPA (reflective evolution), MemAct (RL-trained DCPO).
Tool mutations: FoldAgent (FoldGRPO), EvolveR (self-distillation).
Composition mutations: MaAS (supernet over architectures), AFlow (MCTS over workflows).

### Doc 03 — Evolution and Safety

**Formalize contracts using ABC.**
Agent Behavioral Contracts: C = (P, I, G, R) — Preconditions, Invariants (hard/soft), Governance, Recovery.
Probabilistic (p, δ, k)-satisfaction handles LLM non-determinism.
Detects 5.2-6.8 soft violations per session.
Our manifest.yaml should encode these, not just interface shapes.

**Add Focus finding about explicit scaffolding.**
Focus (arXiv:2601.07190): "current LLMs do NOT naturally optimize for context efficiency — they require explicit scaffolding."
22.7% token savings from explicit "compress every 10-15 tool calls" rule.
Admission gates should include a "compression policy" check — does the new block version include explicit context management instructions?

### Doc 04 — Measurement

**Add ReliabilityBench metrics to scorecard.**
3D reliability surface: consistency × robustness × fault tolerance.
"pass@1 overestimates reliability by 20-40%."
"Simpler ReAct outperforms complex Reflexion under stress by 2.5%."
Our 8-metric scorecard should become 11: add consistency (same result on retry), robustness (result under perturbation), fault tolerance (result under failures).

**Add BATS budget awareness as context for attribution.**
If the agent is not budget-aware, poor performance may be a resource-awareness problem, not a block bug.
Task categorization should include "was the agent budget-aware?" as a dimension.

### Doc 05 — Parallel Evaluation

**Update cost estimate for shadow mode.**
SGLang RadixAttention and provider prefix caching mean shared conversation prefix is nearly free.
Shadow mode cost for `inherit: full` is closer to 1.2x, not 2x, for typical fork points.
The real additional cost is only the diverging part after the fork.

### Doc 06 — Testing Platform

**Reference Block TestProvider for Tier 2.**
Production-grade record/replay that records LLM calls AND MCP server interactions.
Part of Block's 4-layer testing pyramid: deterministic → reproducible reality → probabilistic → vibes.
This is our Tier 2, already built and proven.

**Reference ABC for Tier 1 contracts.**
(P, I, G, R) tuples with probabilistic compliance.
More rigorous than interface-shape checking alone.

**Reference Invariant Labs for Tier 3 property testing.**
DSL for temporal ordering constraints.
Pytest-like assertions for agent traces.
Express invariants: "always terminates," "context never exceeds window," "no tool call after send_message."

**Add agent-chaos for Tier 3 chaos injection.**
Composable chaos injectors: LLM failures, tool failures, data corruption.
Built-in assertions: MaxTotalLLMCalls, AllTurnsComplete, TokenBurstDetection.
Complements our "cheap model as chaos monkey" with deterministic fault injection.

### Doc 07 — Context Flow

**Reference validated implementations for each scenario.**

Scenario 1 (Context-Rich Spawning):
- Google ADK `include_contents` parameter: full/none/compacted.
- OpenAI Agents SDK `input_filter` with `nest_handoff_history`.
- ACON (arXiv:2510.00615): task-aware compression for handoff.

Scenario 2 (Agent Cloning):
- ContextBranch (arXiv:2512.13914): formal guarantees, 900 LOC SDK.
- SGLang fork/join: zero-copy KV cache forking.

Scenario 3 (Tree Compression):
- FoldAgent (arXiv:2510.11967): branch/return as learned actions, 10x reduction.
- ReCAP (arXiv:2510.23822, NeurIPS 2025): recursive context tree, O(d·L̄) bound.
- HiAgent (arXiv:2408.09559, ACL 2025): subgoal compression, 2x success rate.
- PAACE (arXiv:2512.16970): plan-conditioned compression.
- GCC three tiers: main.md never compressed.
- Yang et al. 2026 (arXiv:2603.02112): theoretical proof that recursive decomposition requires exponentially smaller context.

Scenario 4 (LLM-Driven Strategy Selection):
- Sculptor (arXiv:2508.04664): 8 context tools, zero-shot, +49.3pp.
- MemAct (arXiv:2510.12635): RL-trained context policy, 51% less context.
- ARC (arXiv:2602.11574): hierarchical RL for dynamic agent configuration.

Scenario 5 (Domain Discovery):
- Nemori (arXiv:2508.03341): autonomous episode segmentation.
- A-MEM (arXiv:2502.12110): emergent topic clusters via Zettelkasten linking.
- H-MEM (arXiv:2507.22925): Domain → Category → Trace → Episode hierarchy.
- ExpeL (AAAI 2024): different domains → different expertise types.
- River DBSTREAM: production streaming clustering.

---

## The Five Biggest Insights Across All Research

**1. The field IS converging on our architecture.**
Sculptor + MemAct + GCC collectively implement most of our Scenario 4 (LLM-driven strategy selection).
FoldAgent + HiAgent + ReCAP validate our Scenario 3 (tree compression).
Nemori + A-MEM + H-MEM validate our Scenario 5 (domain discovery).
The gap is the INTEGRATION — no system combines all five scenarios. That is our contribution.

**2. RL is the training paradigm for context management.**
MemAct (DCPO), FoldAgent (FoldGRPO), AgeMem (GRPO), SUPO (joint tool+summarization), MEM1 (constant memory RL).
Every successful adaptive context management system uses RL.
Our evolution pipeline (doc 03) should include RL-based optimization, not just LLM-based mutation.

**3. Less is more — for prompts, tools, and context.**
GEPA produces shorter prompts that work better.
<30% of instructions are followed (AGENTIF).
Context rot degrades performance universally (Chroma).
RAG-MCP: 3x accuracy from removing irrelevant tools.
Our architecture should optimize for DENSITY, not VOLUME.

**4. Self-authored knowledge needs a quality gate.**
SkillsBench: self-generated skills provide zero benefit on average.
The Learning Loop from doc 02 must validate that extracted artifacts actually help, not just that they exist.
Multi-model review or benchmark validation should gate artifact acceptance.

**5. Record-and-replay testing is production-ready.**
Block's TestProvider, vcr-langchain, AgentRR, and LangChain's trajectory evaluators prove that our Tier 2 (integration replay) is not speculative — it is already used in production at major companies.

**6. Indiscriminate memory reliably degrades performance.**
Xiong et al. (arXiv:2505.16067): agents strongly mimic retrieved memories when similarity is high, creating error propagation and misaligned experience replay.
Only strict selective addition with evaluation improved performance.
A-MAC (arXiv:2603.04549): without hallucination filtering, agents store and retrieve fabricated information, compounding errors.
SkillsBench: self-generated skills provide zero benefit.
The admission gate is the PRIMARY quality mechanism — what you choose NOT to remember matters more than how you organize what you do remember.
See [doc 03 Memory Security](03-evolution-and-safety.md) and [doc 09 Benchmarks](09-benchmarks-and-performance.md).

**7. Memory poisoning is a real production threat.**
Microsoft documented 31 companies commercially deploying memory poisoning.
OWASP 2026 lists Memory and Context Poisoning as ASI06.
MINJA achieves >95% injection via query-only interaction.
Three baseline protections required: provenance tracking, trust scoring, utility-based temporal decay.
See [doc 03 Memory Security](03-evolution-and-safety.md).

**8. Performance should be measured as delta, not absolute.**
Our metric is how much the agent improves over months of operation on the same task types.
No existing benchmark measures this.
Eight new benchmarks (MemoryAgentBench, BEAM, AMA-Bench, Mem2ActBench, etc.) expose that strong long-context performance does NOT predict strong agentic interactive performance.
See [doc 09 Benchmarks](09-benchmarks-and-performance.md).

**9. RL-trained memory management is the new paradigm.**
Memory-R1 (152 QA pairs), Mem-alpha (generalizes 13x beyond training length), MEM1 (3.5x performance with 3.7x less memory).
Learned CRUD operations (ADD/UPDATE/DELETE/NOOP) outperform all heuristic approaches.
None of the 40 studied projects use learned memory policies yet.
See [persistent memory research](../research/external/2026-03-17-persistent-memory-research-1.md).
