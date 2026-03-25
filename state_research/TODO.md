# State Research TODO

## Next use cases to model

- [ ] **Rework 01-single-agent** — current version uses the universal 8-state machine. Needs to be reworked into an architecture-specific state machine following D13.
- [ ] **Human-in-the-loop as async I/O** — resolved conceptually in DESIGN.md (D9: ask_user() is a yield to HumanDispatcher). Might still want a snippet showing approval flow or subagent asking user.
- [ ] **Coroutines instead of explicit state machine** — the state machine (S, E, T transition table) might be unnecessary boilerplate if the entire agent loop is an async coroutine with await at yield points. Need to think through tradeoffs: visibility/debuggability of explicit transitions vs simplicity of coroutine code.


## Open from DESIGN.md

- [ ] Q1: Rewrite or modify smolagents interpreter?
- [ ] Q2: Streaming LLM responses — events or single async op?
- [ ] Q3: File operations as yield points — worth the overhead?
- [ ] Q4: Budget enforcement — state machine or dispatchers?
- [ ] Q5: Domain detection — separate state or pre-step?


---


Вот полная карта архитектурного разнообразия из нашего исследования. У тебя 4 research agents — это одна семья. Вот остальные, сгруппированные по тому, что архитектурно уникального каждый даёт:

__Event-driven / memory-first:__

- __OpenHands__ — event-sourced loop (EventStream), 11 pluggable condensers, Docker isolation
- __Letta__ — OS-like memory management: core memory always in context, archival retrieved on demand, agent self-edits memory

→ OpenHands — самая развитая event-driven архитектура. Letta — уникальна memory-first подходом.

__Edit-driven (no tool calling):__

- __Aider__ — LLM генерирует edits inline в output, никакого tool API вообще. PageRank repo map.

→ Фундаментально другой transport — стоит включить.

__Tree search (MCTS вместо плоского ReAct):__

- __Moatless__ — select → expand → simulate → backpropagate. Каждый node = полный snapshot кода. LLM-based value function scores actions -100 to 100. UCT selector с 14 score components.

→ Обязательно — единственный agent с tree search вместо линейного loop.

__Evolutionary (популяционная эволюция):__

- __OpenEvolve__ — MAP-Elites + island-based evolution. LLM как mutation operator.
- __Gödel Agent__ — runtime monkey-patching через exec+setattr, без рестартов
- __EvoAgentX__ — эволюция не только промптов, но и DAG-структуры workflow

→ OpenEvolve — лучшие примеры. Gödel Agent уникален runtime-патчингом.

__Self-modifying:__

- __Ouroboros__ — пишет коммиты в свой собственный код, философская конституция, multi-model review
- __BabyAGI__ — database-as-program: Python functions как строки в SQLite, exec() для запуска

→ Ouroboros — если нужен self-modification loop.

__Engine-mediated / multi-agent orchestration:__

- __n8n__ — visual workflow, $fromAI() node composition, LangChain delegation
- __CrewAI__ — role-based Crews + event-driven Flows, inter-agent delegation, A2A protocol

→ CrewAI — самый развитый multi-agent orchestrator.

__Context-folding (RL-learned context management):__

- __FoldAgent__ — branch()/return() tool calls learned via RL. 10x context reduction. Не ReAct, не tree search — третий подход.

→ Архитектурно уникален — единственный agent с RL-learned context management.

__Code-as-action:__

- __smolagents__ — LLM пишет произвольный Python вместо tool calls. AST-based interpreter с allowlists.

→ Принципиально другой action modality.

__Meta-orchestrator:__

- __dmux__ — не agent, а мультиплексор: запускает 11 coding agents в параллельных worktrees через tmux

→ Если framework должен поддерживать orchestration of agents.

__GUI automation:__

- __Agent S__ — visual grounding, screenshots + pyautogui. Two-model architecture: reasoning LLM + grounding model.

→ Если нужно покрыть non-text agents.

__Embodied lifelong learning:__

- __Voyager__ — code as persistent memory, skill library в ChromaDB, новые skills строятся на старых

→ Уникальная "code as memory" архитектура.

---

__Мой рекомендованный минимальный набор для "universal framework"__ (помимо 4 research agents):

2. __OpenHands__ — event-driven loop
3. __Letta__ — memory-first
4. __Aider__ — edit-driven, no tools
6.  __OpenEvolve__ — evolutionary
7. __FoldAgent__ — context-folding
8. __smolagents__ — code-as-action
9. __CrewAI__ — multi-agent orchestration

Это 9 архитектурно различных семей + твои 4 research agents = 13 архитектур. Если framework может выразить все 13, он действительно универсален.


---

## Removed snippets

The following snippets were removed because they all used the identical universal 8-state machine (IDLE, CALLING_LLM, INTERPRETING, WAITING_IO, DISPLAYING, CLEANING_UP, EXTRACTING, CONSOLIDATING) and produced indistinguishable diagrams. Their architectural insights are preserved in DESIGN.md. The remaining snippets (01, 05b, 07b, 09) each have architecture-specific state machines per D13.

- `02-single-subagent.py` - agent spawns one child, waits. Same SM as 01, proved spawn is just a yield.
- `03-parallel-subagents.py` - agent spawns N children. Same SM as 01, proved spawn_all is just a yield.
- `04-open-deep-research.py` - supervisor + parallel researchers. Same SM, proved ODR maps to our model.
- `05-paperqa-toolselector.py` - PaperQA2 ToolSelector with 6 tools. Same SM, tools as yield points in code. Superseded by 05b.
- `06-paperqa-pipeline.py` - PaperQA2 Fake Agent deterministic pipeline. Same SM, pipeline as predetermined code.
- `07-moatless-mcts.py` - MCTS as interpreter code. Same SM, proved MCTS runs on universal machine. Superseded by 07b.
- `08-dgm-evolutionary.py` - DGM evolutionary loop with agent-as-a-string. Same SM, proved evolution is just spawn.
