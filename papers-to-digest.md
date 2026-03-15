# Papers to Digest — Ordered by Expected Significance

## Tier 1: Must Read — Directly Changes Our Architecture

1. **GEPA: Reflective Prompt Evolution** — Agrawal et al., ICLR 2026 Oral. [arXiv:2507.19457](https://arxiv.org/abs/2507.19457). Replaces our multi-optimizer approach with one tool that beats all of them. Produces shorter prompts. Integrated into DSPy.

2. **FoldAgent: Scaling Long-Horizon LLM Agent via Context Folding** — Sun et al., 2025. [arXiv:2510.11967](https://arxiv.org/abs/2510.11967). OUR tree compression idea, already implemented with RL (FoldGRPO). 10x context reduction, 58% SWE-Bench.

3. **Sculptor: Context Management Tools for LLMs** — Li et al., 2025. [arXiv:2508.04664](https://arxiv.org/abs/2508.04664). 8 context-management tools as agent actions. +49.3pp zero-shot. OUR Scenario 4 meta-context, already working.

4. **BATS: Budget-Aware Tool Scaling** — Google Research, 2025. [arXiv:2511.17006](https://arxiv.org/abs/2511.17006). Injecting budget counters into prompts changes agent behavior qualitatively. 40% cost reduction for free.

5. **SkillsBench: Self-Generated Skills Evaluation** — 2026. [arXiv:2602.12670](https://arxiv.org/abs/2602.12670). Critical NEGATIVE result: self-generated skills provide zero benefit. Curated skills add 16.2pp. Changes our Learning Loop.

6. **Agent Behavioral Contracts (ABC)** — Bhardwaj et al., 2026. [arXiv:2602.22302](https://arxiv.org/abs/2602.22302). Formalizes contracts with probabilistic compliance. Detects 5.2-6.8 violations per session that baselines miss. Changes our Tier 1 testing.

7. **GCC: Git Context Controller** — Wu et al., 2025. [arXiv:2508.00031](https://arxiv.org/abs/2508.00031). COMMIT/BRANCH/MERGE/CONTEXT for agent context. Three-tier hierarchy. >80% SWE-Bench Verified.

8. **ReCAP: Recursive LLM Calls via Plan-Ahead Decomposition** — Zhang et al., NeurIPS 2025. [arXiv:2510.23822](https://arxiv.org/abs/2510.23822). Recursive context tree with O(d*L) bound. +32% on Robotouille.

9. **PAACE: Plan-Aware Agent Context Compression** — Yuksel, 2025. [arXiv:2512.16970](https://arxiv.org/abs/2512.16970). Only paper that formally conditions compression on the task plan. 97% of teacher performance at 10x lower cost.

10. **MemAct: Memory as Action** — Zhang et al., 2025. [arXiv:2510.12635](https://arxiv.org/abs/2510.12635). Context curation as RL-trained policy (DCPO). 14B matches 16x larger models. 51% less context.

## Tier 2: Should Read — Validates and Extends Our Design

11. **A-MEM: Agentic Memory for LLM Agents** — Xu et al., NeurIPS 2025. [arXiv:2502.12110](https://arxiv.org/abs/2502.12110). Zettelkasten memory with emergent topic clusters. 154+ citations.

12. **Nemori: Self-Organizing Agent Memory** — Nan et al., 2025. [arXiv:2508.03341](https://arxiv.org/abs/2508.03341). Autonomous episode segmentation. Outperforms Mem0, Zep, MemGPT.

13. **HiAgent: Hierarchical Working Memory Management** — Hu et al., ACL 2025. [arXiv:2408.09559](https://arxiv.org/abs/2408.09559). Subgoal-as-compression-boundary. 2x success rate. Our two-level tree compression validated.

14. **H-MEM: Hierarchical Memory for Long-Term Reasoning** — Sun & Zeng, 2025. [arXiv:2507.22925](https://arxiv.org/abs/2507.22925). Domain → Category → Trace → Episode hierarchy. Validates our DomainProfile.

15. **ExpeL: LLM Agents Are Experiential Learners** — Zhao et al., AAAI 2024. [arXiv:2308.10144](https://arxiv.org/abs/2308.10144). Different domains develop different expertise types. Validates per-domain composition.

16. **ReliabilityBench: Chaos Engineering for LLM Agents** — 2026. [arXiv:2601.06112](https://arxiv.org/abs/2601.06112). 3D reliability surface. "pass@1 overestimates reliability by 20-40%." Adds reliability metrics to our scorecard.

17. **ACON: Agent Context Optimization** — Kang et al., 2025. [arXiv:2510.00615](https://arxiv.org/abs/2510.00615). Task-aware compression via failure-driven optimization. 26-54% token reduction. Distilled compressors retain 95%.

18. **The Complexity Trap** — Lindenbauer et al., NeurIPS DL4Code 2025. [arXiv:2508.21433](https://arxiv.org/abs/2508.21433). Simple observation masking matches LLM summarization. 52% cost reduction. Strong baseline.

19. **MEM1: Learning to Synergize Memory and Reasoning** — Zhou et al., MIT, 2025. [arXiv:2506.15841](https://arxiv.org/abs/2506.15841). RL-trained constant memory. 3.5x performance with 3.7x less memory.

20. **AGENTIF: Benchmarking Instruction Following in Agentic Scenarios** — Qi et al., NeurIPS 2025 DB Spotlight. [arXiv:2505.16944](https://arxiv.org/abs/2505.16944). <30% of instructions followed perfectly. Task-solving and rule-following are decoupled.

## Tier 3: Worth Reading — Reference and Context

21. **ContextBranch: Version Control for LLM Conversations** — 2025. [arXiv:2512.13914](https://arxiv.org/abs/2512.13914). Git-like primitives with formal guarantees. +6.8% context awareness.

22. **SGLang: Efficient Execution of Structured LM Programs** — Zheng et al., NeurIPS 2024. [arXiv:2312.07104](https://arxiv.org/abs/2312.07104). fork/join with RadixAttention. 5x throughput. Makes context cloning cheap.

23. **SUPO: Summarization-Augmented Policy Optimization** — Lu et al., 2025. [arXiv:2510.06727](https://arxiv.org/abs/2510.06727). RL jointly optimizes tool-use AND summarization end-to-end.

24. **AgentSpec: Runtime Enforcement DSL** — Wang et al., ICSE 2026. [arXiv:2503.18666](https://arxiv.org/abs/2503.18666). Prevents unsafe executions in >90% of cases. Millisecond overhead.

25. **Pro2Guard: Proactive Enforcement via Probabilistic Model Checking** — 2025. [arXiv:2508.00500](https://arxiv.org/abs/2508.00500). Predicts safety violations before they occur. PAC guarantees.

26. **MaAS: Multi-Agent Architecture Search via Supernet** — Zhang et al., ICML 2025 Oral. [arXiv:2502.04180](https://arxiv.org/abs/2502.04180). Distribution over architectures. 75% cost reduction.

27. **AFlow: Automating Agentic Workflow Generation** — Zhang et al., ICLR 2025 Oral. [arXiv:2410.10762](https://arxiv.org/abs/2410.10762). MCTS over workflows. 5.7% improvement. Smaller models beat GPT-4o at 4.55% cost.

28. **Agent Contracts** — Ye & Tan, 2026. [arXiv:2601.08815](https://arxiv.org/abs/2601.08815). Formal contract tuple for delegation. 90% token reduction, 525x lower variance.

29. **Focus: Autonomous Context Compression** — 2025. [arXiv:2601.07190](https://arxiv.org/abs/2601.07190). "LLMs do NOT naturally optimize for context efficiency." 22.7% token savings with explicit scaffolding.

30. **Recursive Models for Long-Horizon Reasoning** — Yang et al., 2026. [arXiv:2603.02112](https://arxiv.org/abs/2603.02112). Theoretical proof: recursive decomposition requires exponentially smaller context. 3B recursive model beats frontier LLMs.

31. **IterResearch: Markovian State Reconstruction** — Chen et al., 2025. [arXiv:2511.07327](https://arxiv.org/abs/2511.07327). Workspace reconstruction as MDP. +14.5pp across 6 benchmarks.

32. **EvolveR: Self-Evolving Agents** — Wu et al., 2025. [arXiv:2510.16079](https://arxiv.org/abs/2510.16079). Self-contained experience distillation. No external teacher.

33. **MAPRO: Multi-Agent Prompt Optimization as MAP Inference** — Zhang et al., Amazon, 2025. [arXiv:2510.07475](https://arxiv.org/abs/2510.07475). Topology-aware credit assignment via blame signals. Surpasses MASS.

34. **Chroma: Context Rot** — research.trychroma.com. Performance degrades universally with longer prompts. Hard ceiling on prompt complexity.

35. **Multi-Agent Memory from a Computer Architecture Perspective** — Yu et al., 2026. [arXiv:2603.10062](https://arxiv.org/abs/2603.10062). Memory consistency for multi-agent systems. Identifies the protocol gap we need to address.

36. **LATS: Language Agent Tree Search** — Zhou et al., ICML 2024. [arXiv:2310.04406](https://arxiv.org/abs/2310.04406). MCTS for language agents. 92.7% on HumanEval.

37. **ADAS: Automated Design of Agentic Systems** — Hu et al., ICLR 2025. [arXiv:2408.08435](https://arxiv.org/abs/2408.08435). Meta-agent discovers new agent designs in code.

38. **MASS: Multi-Agent System Search** — Zhou et al., 2025. [arXiv:2502.02533](https://arxiv.org/abs/2502.02533). Joint prompt + topology optimization. "Prompts are the dominant factor."

39. **MemAgent: Reshaping Long-Context LLM with RL-based Memory** — Yu et al., 2025. [arXiv:2507.02259](https://arxiv.org/abs/2507.02259). RL-trained fixed-length memory. 14B extrapolates from 8K to 3.5M.

40. **ARC: Adaptive Runtime Configuration** — 2025. [arXiv:2602.11574](https://arxiv.org/abs/2602.11574). Hierarchical RL dynamically configures agents per-query. 25% higher accuracy.
