# Session Notes — State Machine Design

Date: 2026-03-23 / 2026-03-24


## Where We Stopped

We have the pattern (PATTERN.md), the framework (sm.py), one working example
(01-single-agent-elm.py), and auto-diagram generation (gen_diagram.py).

Next: model more architectures as state machines using this pattern.
The goal from the old DESIGN.md TODO was to cover ~13 architecturally distinct
agent families. The pattern and tooling are ready — now it is about applying them.


## File Inventory

### Current (use these)

- `PATTERN.md` — the specification. All design decisions explained.
- `sm.py` — the StateMachine framework. Decorator-based transition registration.
- `gen_diagram.py` — auto-generates Mermaid diagrams by importing .py files
  and reading the StateMachine registry + return type hints.
- `01-single-agent-elm.py` — reference example: 5-state ReAct agent.
- `01-single-agent-elm.mmd` / `.svg` — auto-generated diagram.
- `01-interpreter-elm.mmd` / `.svg` — separate interpreter SM diagram
  (hand-written, the interpreter is not yet in the decorator pattern).
- `guess_game.py` — teaching example: guessing game showing the pattern
  in its simplest form (3 states, 2 events, type-per-state, no framework).

### Obsolete (from before the pattern evolved)

- `reducer.py` — old table-driven reducer with enum states. Superseded by sm.py.
- `reducer_demo.py` — demo for the old reducer. Superseded.
- `01-single-agent.py` — old S/E/T enum-based transition table. Superseded by -elm.py.
- `01-single-agent.mmd` / `.svg` — old diagram from old approach.
- `gen_mermaid.py` — old diagram generator for S/E/T transition tables.
- `TODO.md` — old TODO, references deleted DESIGN.md and removed snippets.
- `05b-paperqa-pure-sm.py` and other old snippets were already removed.


## Key Decisions Not in PATTERN.md

These came up in conversation but are not pattern rules — they are design
observations worth remembering.

### Entry actions are determined by the target state

Every transition into CallingLLM needs "call the LLM." Every transition
into ExecutingCode needs "run the interpreter." The entry action is a
property of the STATE, not the transition. The state itself IS the command.
This is why we removed explicit Cmd objects — the runtime just reads
the state type and knows what to do.

### Two independent state machines for the agent

The agent SM (AwaitingInput, CallingLLM, ExecutingCode, Extracting, Consolidating)
and the interpreter SM (Running, WaitingIO, Done, Error) are completely independent.
The agent sees ExecutingCode as an opaque state. The interpreter handles its
own I/O cycle internally. The boundary: StartCode in, CodeDone/CodeError out.

The interpreter SM is not yet in the decorator pattern (01-interpreter-elm.mmd
is hand-written). When we implement it, it will be its own StateMachine instance.

### sm.py does not implement on_enter or delegate yet

PATTERN.md describes `@agent.on_enter(State)` and `agent.delegate(state, machine, mapping)`.
These are not in sm.py. They were designed in conversation but deferred.
When implementing the runtime, add these to sm.py.

### Guard clauses produce multiple edges in diagrams

A transition with return type `A | B` generates two edges in the diagram —
one for each possible target. The gen_diagram.py script handles this by
reading `get_type_hints(fn)["return"]` and checking for union types via
`get_args()`. This is the mechanism that makes guard clauses visible in diagrams.


## Evolution Path (How We Got Here)

1. Started with table-driven FSM: `S` enum, `E` enum, `T(src, event, dst, actions)`.
   Transition table as a list. `reducer.py` did lookup.

2. Recognized the interpreter is a separate SM — split into Agent SM + Interpreter SM.
   Agent sees ExecutingCode as opaque.

3. Switched from enum tags to type-per-state (Kotlin sealed class pattern in Python).
   Each state is a frozen dataclass. Pattern matching on type, not tag field.

4. Moved from explicit Cmd objects to recognizing that entry actions are
   determined by the target state. Removed commands entirely.

5. Introduced `@machine.transition` decorator — each transition is a standalone
   function, auto-registered by type hints. No big match/case reducer.

6. Built `gen_diagram.py` — imports the module, reads the StateMachine registry
   and return type hints, generates Mermaid automatically.


## Architectures To Model Next

From the old DESIGN.md TODO, these architectures should each get a snippet:

- PaperQA2 (research agent with RCS pipeline, multiple LLM prompts)
- Moatless (MCTS tree search over code)
- OpenHands (event-driven with condensers)
- Aider (edit-driven, no tool calling)
- OpenEvolve (evolutionary, population-based)
- FoldAgent (context-folding with branch/return)
- smolagents (code-as-action)
- CrewAI (multi-agent orchestration)
- Letta (memory-first)

Each should follow PATTERN.md, use sm.py, and auto-generate its diagram.
