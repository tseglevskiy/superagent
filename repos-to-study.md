# GitHub Repos to Study — Ordered by Expected Significance

We are designing a self-evolving agent architecture with Lego-style composable blocks, versioned knowledge artifacts, tree-structured context compression, domain-aware knowledge partitioning, and agent-controlled context management. For each repo below, we need a deep source-code review focused on the specific aspects listed. Please provide commit-pinned file paths, key function signatures, data structures, and algorithmic details.

## Tier 1: Directly Implements Core Architecture Concepts

### 1. sunnweiwei/FoldAgent

arXiv:2510.11967. Branch/return as RL-learned actions for context folding.

**Pay attention to:** The `branch(description, prompt)` and `return(message)` tool implementations — how exactly are they defined as tools the LLM can call? How does FoldGRPO training work — what is the reward signal, how are process rewards computed, and what training data is needed? How does nesting work — can a branch contain another branch, and how is the context tree maintained? What happens to the folded content — is it stored somewhere for potential retrieval, or permanently discarded? How does the 10x context reduction actually manifest — is it measured by active tokens per step, or cumulative across the session?

### 2. gepa-ai/gepa

arXiv:2507.19457. ICLR 2026 Oral. Reflective prompt evolution via genetic algorithms + Pareto selection.

**Pay attention to:** How does GEPA handle LONG system prompts (1000+ tokens) typical of agent systems — does it optimize the whole prompt or segment it? What is the reflection mechanism — how does it analyze full agent trajectories (reasoning + tool calls + results) to produce improvement suggestions? How does Pareto selection balance multiple objectives (accuracy vs prompt length vs cost)? What is the integration API with DSPy — how do you plug GEPA into an existing agent's system prompt? How many evaluation runs are needed per optimization iteration, and what is the total cost for a typical optimization cycle?

### 3. theworldofagents/GCC

arXiv:2508.00031. Git-like context branching with COMMIT/BRANCH/MERGE/CONTEXT.

**Pay attention to:** The three-tier file hierarchy (main.md, commit.md, log.md) — how are these files structured, what goes in each, and who writes/reads them? How does the agent decide when to COMMIT vs when to keep accumulating in log.md? How does BRANCH create isolation — is it a separate conversation, a separate file namespace, or something else? How does MERGE work — is it LLM-driven synthesis, or programmatic? The finding that K=1 (most recent commit only) performs best — what is the retrieval mechanism for older commits when needed? How does this integrate with LLM API calls — is it a wrapper around the provider, a prompt preprocessor, or a tool set?

### 4. agiresearch/A-mem

arXiv:2502.12110. MIT License. NeurIPS 2025. Zettelkasten-inspired agentic memory.

**Pay attention to:** The automatic tag/keyword generation for each memory — what LLM call produces these, and how are they used for retrieval? The dynamic linking mechanism — when a new memory is created, how are connections to existing memories established (embedding similarity threshold? LLM-judged relevance?)? The t-SNE visualization showing emergent clusters — is there any programmatic cluster detection, or are clusters only visible in visualization? How does retrieval work — pure embedding similarity, or does the link graph influence ranking? What is the memory update mechanism — when does an existing memory get modified vs a new one created? How does it scale — what happens with 10,000+ memories?

### 5. nemori-ai/nemori

arXiv:2508.03341. Autonomous episode segmentation from conversation streams.

**Pay attention to:** The episode boundary detection algorithm — what signals does it use to detect when a topic changes (embedding shift? LLM judgment? temporal gap?)? The "Predict-Calibrate Principle" — how does prediction error drive learning, and what exactly is predicted? How does it compare to simple sliding-window approaches in terms of segmentation quality? What is the output format — labeled episodes with metadata? Can it operate incrementally (process one message at a time) or does it need batch processing? How does it handle interleaved topics (user switches between topics and back)?

### 6. letta-ai/letta

arXiv:2310.08560. Already studied deeply in our research. Three-tier memory, shared blocks, tool rules state machine.

**Pay attention to (what we have NOT yet covered):** The git-backed memory mode (Context Repositories) — how does it differ from the standard block mode, and what are the trade-offs? The `ToolRulesSolver` state machine in detail — how are conditional rules evaluated, and how does force_tool_call work when only one tool is allowed? The `CompactionSettings` with four modes — how does the fallback chain actually trigger (what error causes fallback from self_compact_all to self_compact_sliding_window to all)? The `Conversations` API — how does concurrent multi-user access to the same agent work with shared blocks? The Redis distributed locking — what happens when a lock times out mid-operation?

## Tier 2: Validates or Extends Specific Blocks

### 7. glanzz/context-branching

arXiv:2512.13914. ~900 LOC Python SDK for checkpoint/branch/switch/inject.

**Pay attention to:** The content-addressable storage (SHA-256 hashing) — how are conversation states serialized and stored? The `inject` primitive — how does it selectively merge specific messages from one branch into another without breaking conversational coherence? The formal guarantees (branch isolation, checkpoint determinism, injection safety) — how are these enforced in the implementation? Is it provider-agnostic (works with any LLM API), or tied to specific providers?

### 8. MIT-MI/MEM1

arXiv:2506.15841. RL-trained agent with constant memory. 3.5x performance with 3.7x less memory.

**Pay attention to:** The "constant memory" mechanism — what is the fixed-size state representation, and how is it updated each turn? The RL training procedure — what reward signal teaches the agent what to retain vs discard? How does it handle the cold start (first few turns with no accumulated state)? Can the trained memory management policy transfer across different task types, or is it task-specific? What is the computational overhead of the memory update step compared to a standard LLM call?

### 9. BytedTsinghua-SIA/MemAgent

arXiv:2507.02259. RL-trained fixed-length memory buffer. 14B extrapolates from 8K to 3.5M.

**Pay attention to:** The overwrite strategy for the fixed-length memory panel — how does the model decide what to overwrite? The RL training (extended DAPO) — what is the reward function, and how does it handle the multi-turn, context-independent conversation setup? The extrapolation capability — how does a model trained on 32K context generalize to 3.5M without degradation? What is the memory panel format — structured fields, free-form text, or something else? Can this be applied to an existing agent (as a wrapper) or does it require model fine-tuning?

### 10. JetBrains-Research/the-complexity-trap

arXiv:2508.21433. NeurIPS DL4Code 2025. Observation masking vs LLM summarization comparison.

**Pay attention to:** The exact masking strategy — what gets masked (tool observations only? assistant reasoning too?), and what replaces it (placeholder text? nothing?)? The "trajectory elongation" effect — how does LLM summarization mask failure signals and cause agents to persist in unproductive loops? The hybrid approach — how are masking and summarization combined, and what are the rules for when each is used? The cost breakdown — where exactly does the 52% cost reduction come from (fewer tokens in context? fewer LLM calls?)? Does the finding generalize beyond SWE-bench to other agent tasks?

### 11. invariantlabs-ai/testing

ETH Zurich. DSL for temporal ordering constraints on agent traces.

**Pay attention to:** The assertion DSL syntax — how do you express properties like "never call send_email after detecting prompt injection"? How are traces captured — does it require instrumentation of the agent, or does it work with log files? The "stacktraces for agents" concept — how does it localize which step in a multi-step agent trace caused a failure? How does it integrate with pytest — decorator-based, fixture-based, or standalone? Can it express quantitative properties (e.g., "context never exceeds 100K tokens") or only temporal ordering?

### 12. deepankarm/agent-chaos

Composable chaos injectors for AI agents.

**Pay attention to:** The injection mechanism — how does it intercept LLM calls and tool calls to inject failures? The composability — can you combine multiple chaos strategies (e.g., 10% LLM timeout + 5% tool error + data corruption)? The built-in assertions (MaxTotalLLMCalls, AllTurnsComplete, TokenBurstDetection) — how are these implemented? Can it swap the LLM model mid-test (e.g., replace Claude with a 7B model to stress-test error handling)? How does it integrate with existing agent frameworks (LangChain, smolagents, custom)?

### 13. confident-ai/deepeval

~5k stars. 50+ metrics including tool correctness and plan adherence.

**Pay attention to:** The agent-specific metrics (tool correctness, argument validation, efficiency, plan adherence) — how are these computed, and what data do they need? The `@observe` decorator — how does it trace agent calls, retrievers, and tool usage at the component level? The regression testing capability — how does it compare test runs across versions and detect degradation? Can it be used in CI/CD pipelines with quality gates (block merge if quality drops)? How does it handle non-determinism in agent outputs for regression comparison?

## Tier 3: Useful Reference Implementations

### 14. stanfordnlp/dspy

arXiv:2310.03714. DSPy framework with GEPA integration.

**Pay attention to:** The GEPA integration (`dspy.GEPA`) — how does it connect to the optimization loop? The `Signature` abstraction — how do typed input/output contracts compile into prompts? The MIPROv2 optimizer — how does Bayesian optimization work for prompt tuning, and what is the evaluation budget? Can DSPy optimize an entire agent system prompt (not just a single module), and how?

### 15. FoundationAgents/AFlow

arXiv:2410.10762. ICLR 2025 Oral. MCTS over code-represented workflows.

**Pay attention to:** The workflow representation as code — what language/format, and how is it parsed for MCTS? The MCTS search — what is the value function, how are workflows evaluated, and what is the branching factor? The finding that smaller models beat GPT-4o at 4.55% cost — what specific workflow optimizations enable this? Can AFlow discover fundamentally new workflow structures (e.g., add a feedback loop that was not in the seed), or only optimize existing ones?

### 16. bingreeky/MaAS

arXiv:2502.04180. ICML 2025 Oral. Supernet over agentic architectures.

**Pay attention to:** The "supernet" concept — how is the distribution over architectures parameterized? The query-dependent subnetwork sampling — how does the controller decide which architecture to use for a given input? The 75% cost reduction — where does the saving come from (simpler architectures for easy queries? fewer agents?)? The cross-dataset transferability — does a supernet trained on one benchmark generalize to others without retraining?

### 17-30. Additional repos

For repos 17-30, provide standard deep-dive coverage: key source files, main data structures, integration points, and any surprising implementation details. These are:

- **LeapLabTHU/ExpeL** (arXiv:2308.10144, AAAI 2024) — focus on how different expertise types emerge for different domains
- **SunzeY/SEAgent** (arXiv:2508.04700) — focus on the specialist-to-generalist training strategy
- **Edaizi/EvolveR** (arXiv:2510.16079) — focus on self-distillation without external teacher
- **microsoft/LLMLingua** (arXiv:2310.05736) — focus on the question-aware LongLLMLingua variant and AutoGen integration
- **geekan/MetaGPT** (arXiv:2308.00352) — focus on the shared message pool publish-subscribe implementation
- **amosjyng/vcr-langchain** — focus on how non-network tool interactions are recorded and replayed
- **MemTensor/MemOS** (arXiv:2507.03724) — focus on the MemCube abstraction and memory scheduling
- **getzep/graphiti** (arXiv:2501.13956) — focus on community-based topic namespace detection
- **MaartenGr/BERTopic** (arXiv:2203.05794) — focus on the online/incremental mode with partial_fit and merge_models
- **online-ml/river** — focus on DBSTREAM clustering for streaming data without specifying K
- **promptfoo/promptfoo** — focus on agent tracing, trajectory assertions, and CI/CD quality gates
- **ryoungj/ToolEmu** (arXiv:2309.15817) — focus on model-swapping for red-teaming and the adversarial emulator
- **eth-sri/ToolFuzz** — focus on the fuzzing strategy for agent tool inputs
- **Shichun-Liu/Agent-Memory-Paper-List** — living reference, check for papers published after March 2026
