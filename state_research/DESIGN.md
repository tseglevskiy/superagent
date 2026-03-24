# State Machine Design — Concepts, Decisions, Reasoning

Date: 2026-03-22

## Goal

Replace the procedural engine in `superagent/alpha/superagent/engine.py` with a real state machine that can support subagent spawning, parallel execution, and tree-structured context compression — without compromises.

## Starting Point

The alpha MVP has a working CLI chatbot with:
- Stateless disk-first engine (read disk → call LLM → write disk)
- Code-as-action via smolagents AST interpreter (LocalPythonExecutor)
- 4 integration modules (file_edit, shell_exec, web_search, workspace_files)
- Knowledge pipeline (extraction, domain detection, consolidation)
- ~4,100 lines across 18 files

The current engine is procedural: a while-True readline loop in `__main__.py` calls `run_agent_turn()` which calls `run_turn()` in a for-loop. No explicit states, no event queue, no state machine.

## Design Evolution (6 iterations)

### Iteration 1: Extract the current transitions

Mapped the existing procedural code to an explicit state machine.
8 states, 17 transitions. Proved the current behavior is already a state machine — just implicit in the control flow.

### Iteration 2: Add single subagent (WAITING_CHILD)

Added a WAITING_CHILD state to the parent state machine.
spawn_subagent was modeled as a separate tool call that the engine intercepts.

**Problem:** Our agent uses code-as-action. The LLM writes Python, not JSON tool calls. Spawning must happen INSIDE the Python script, not as a separate tool call. The state machine was modeling the wrong abstraction level.

### Iteration 3: Add parallel children (WAITING_CHILDREN)

Extended iteration 2 with fan-out/fan-in. Parent waits for N children.
Engine manages multiple agent instances with round-robin processing.

**Same problem as 2:** Still modeled at the tool-call level, not inside code-as-action.

### Iteration 4: Spawn as blocking function inside code

Recognized that spawn() must be a function the Python script calls, like read() or shell_run().
From the parent's perspective, python_exec just takes longer.

**Problem:** The smolagents AST interpreter is synchronous. When it calls spawn(), it blocks. But the child needs async LLM calls. The parent's asyncio event loop is already running — can't nest asyncio.run(). 

Proposed solution: separate thread per child.

### Iteration 5: Interpreter yields — NO THREADS

**Key decision: no threads, no compromises in the state machine.**

The AST interpreter becomes a coroutine. When it hits spawn(), ask(), or any I/O:
1. Saves execution state (locals, AST position, call stack)
2. Returns a Request to the engine
3. Engine processes the request (runs child, calls LLM, etc.)
4. Engine resumes the interpreter with the result
5. Interpreter continues from where it paused

This requires modifying the smolagents interpreter to support yield/resume — accepted as necessary cost for architectural cleanliness.

New states: WAITING_INNER_LLM (ask() in flight), WAITING_CHILD (spawn() — child running).

### Iteration 6: Typed async dispatchers

Recognized that ALL I/O should be yield points, not just spawn() and ask(). The interpreter should NEVER do I/O — it's pure computation that yields when it needs anything external.

Each I/O type gets its own Dispatcher with configurable concurrency:
- LLMDispatcher (max_concurrent: 5)
- ShellDispatcher (max_concurrent: 3)
- FileDispatcher (max_concurrent: 10)
- HttpDispatcher (max_concurrent: 5)
- AgentDispatcher (max_concurrent: 10)

Multiple agents can have requests in flight simultaneously across different dispatchers. The engine never blocks on I/O — it submits and moves to the next agent.

**Key simplification:** With unified `interpreter_yield` and `io_result` events, we don't need separate states per I/O type. WAITING_INNER_LLM and WAITING_CHILD collapse into one WAITING_IO state.

### Final result: All three use cases have IDENTICAL state machine

```
01-single-agent.py        — user talks, agent reasons and acts
02-single-subagent.py     — agent spawns one child, waits, continues
03-parallel-subagents.py  — agent spawns N children in parallel
```

8 states, 18 transitions. Unchanged across use cases. The complexity of subagents and parallelism lives in the engine and dispatchers, not in the state machine.

## Yield Function Taxonomy

Every function the interpreter can call falls into one of three categories:

### Category 1: Pure Computation (no yield)

Functions that compute a result from their arguments without external I/O.
The interpreter calls them and gets the result immediately.

Examples: `json.dumps()`, `re.findall()`, `len()`, string operations, math.

### Category 2: I/O Yield (yield and resume)

Functions that need an external system. The interpreter yields a Request,
the engine routes it to a dispatcher, the dispatcher delivers the result,
the engine resumes the interpreter.

```
ask(model, prompt)          → LLMDispatcher      → resume with text
ask_all([(model, prompt)])  → LLMDispatcher (N)   → resume with list of texts
spawn(task, inherit)        → AgentDispatcher     → resume with child result
spawn_all(tasks)            → AgentDispatcher (N) → resume with list of results
shell_run(command)          → ShellDispatcher     → resume with output
read(path)                  → FileDispatcher      → resume with File object
write(path, content)        → FileDispatcher      → resume with confirmation
edit(path, old, new)        → FileDispatcher      → resume with confirmation
web_search(query)           → HttpDispatcher      → resume with results
ask_user(prompt)            → HumanDispatcher     → resume with user input
```

All behave identically from the state machine's perspective:
INTERPRETING → interpreter_yield → WAITING_IO → io_result → INTERPRETING

A single function call may yield multiple times internally. For example,
`gather_evidence()` (PaperQA2 pattern) yields for embedding, then vector search,
then parallel LLM scoring. Three yields in one call. The state machine handles
this naturally — it doesn't count or care.

### Category 3: Terminal Yield (yield and stop)

One function: `complete(result)`. The interpreter yields the result and
NEVER resumes. The agent instance is done.

```
complete("here are my findings")  → TERMINAL — agent delivers result and stops
```

For the **root agent** in interactive mode: `complete()` shows the result to the
user with completion formatting (e.g., "task done" button). The session stays alive.
The user can continue in the same context or start fresh.

For the **root agent** in autonomous mode: `complete()` prints the result and
terminates the process.

For a **subagent**: `complete()` delivers the result string to the parent agent.
The parent's interpreter resumes with this string as the return value of `spawn()`.
The child instance is cleaned up.

Without `complete()`, subagents have no termination mechanism. A child that
produces a text response would enter IDLE and wait for user input — but there
is no user. `complete()` is how the child says "I'm done, take my result."

### The Human as a Dispatcher

`ask_user(prompt)` is an I/O yield like any other. The interpreter pauses,
the HumanDispatcher shows the prompt and waits for input, the interpreter
resumes with the user's response.

For the **root agent**: this is the normal chat interaction — show message,
wait for input. Same as typing at the CLI prompt.

For a **subagent**: this enables human-in-the-loop for children. A UI showing
a tree of agents can render each subagent's `ask_user()` as a form. The parent
continues working while one child waits for human approval. Other children
keep running — there's no global block.

Most subagents will never call `ask_user()`. But the architecture doesn't
prohibit it. The dispatcher handles routing — the state machine doesn't know
or care whether the I/O target is an LLM, a shell, or a human.

### The Turn Boundary

In the standard ReAct loop (Cline, Claude Code, our agent):
- The LLM generates code → interpreter runs it → results go back to the LLM
- The LLM decides: generate more code (→ INTERPRETING) or respond with text (→ DISPLAYING)
- The LLM responding with text is NOT `complete()` — it's a mid-task message

The distinction:
- **Text response** (llm_response_text): "I found 12 files matching your pattern..."
  The session continues. The user sees the message and can respond.
- **Completion** (complete()): "Task done. Here's the final report."
  The task is finished. UI shows completion state. User can accept or continue.

Both lead to IDLE (waiting for user input). The difference is semantic —
it's a signal to the UI and to the subagent lifecycle, not to the state machine.

## Key Decisions

### D1: No threads, ever

Threads introduce races, locks, debugging nightmares. The state machine must be single-threaded with async I/O via asyncio. The interpreter cooperatively yields — no preemption.

### D2: The interpreter is a coroutine

The smolagents AST interpreter will be modified (or rewritten) to support yield points. When the interpreter encounters a yield function (ask, spawn, shell_run, read, etc.):
1. It raises a YieldException containing a Request
2. The engine catches it, routes to the appropriate dispatcher
3. When the result arrives, the engine calls interpreter.resume(result)
4. The interpreter restores its state and continues

This is the core architectural investment. Without it, we'd need threads.

### D3: All I/O is a yield point

The interpreter never does I/O directly. Every external operation — LLM call, shell command, file read, web search, subagent — goes through the same yield/resume mechanism. This gives us:
- Consistent error handling for all I/O
- The ability to profile every external call
- Future parallelism: multiple agents' I/O requests processed concurrently
- Testability: mock any dispatcher to test interpreter behavior

### D4: Dispatchers own concurrency

Each dispatcher type decides its own concurrency limit. The engine doesn't need to know. LLM calls can be 5-parallel (limited by provider rate limits). Shell commands 3-parallel (limited by local resources). Agent spawns 10-parallel (they're lightweight — the bottleneck is downstream). The engine just submits and waits for callbacks.

### D5: One state machine for all use cases

spawn() is just another yield point, like shell_run(). The state machine doesn't know or care whether the I/O request is a file read (microseconds) or a child agent running 50 LLM calls (minutes). It's all INTERPRETING → WAITING_IO → INTERPRETING.

### D6: The LLM code controls the execution pattern

Sequential spawning:
```python
a = spawn("topic A")   # yield, wait, resume
b = spawn("topic B")   # yield, wait, resume
```

Parallel spawning:
```python
results = spawn_all([("topic A", "summary"), ("topic B", "summary")])
# one yield, engine runs both concurrently, one resume with list
```

The LLM decides the execution pattern through the code it writes. The engine supports both.

### D7: Disk-first property preserved

On restart, the state machine starts in IDLE. The session JSONL has all messages. The interpreter state is lost (any in-progress Python script is abandoned). This is acceptable — the LLM will re-plan on the next turn.

### D8: complete() is the termination mechanism

Every agent instance — root or child — terminates via `complete(result)`.
This is the ONLY way a subagent delivers its result to the parent.
Without it, a child that finishes would enter IDLE and wait for user input that will never come.

For the root agent, `complete()` is the task boundary: it signals the UI to show the result with completion formatting and offer "start new task."
The session stays alive — the user can continue or start fresh.

In autonomous mode, `complete()` means exit the process.

This is consistent with how every studied agent handles termination:
Cline (`attempt_completion`), PaperQA2 (`complete`), OpenHands (`AgentFinishAction`).

### D9: The human is a dispatcher, not a special case

`ask_user()` is an I/O yield like `ask()` or `shell_run()`.
The HumanDispatcher shows the prompt (CLI input, web form, IDE panel) and delivers the user's response as an io_result.

This unifies:
- Normal chat interaction (root agent asking the user)
- Approval flows (agent asking "should I proceed?")
- Subagent human-in-the-loop (child agent asking for clarification)
- Clarification questions (Open Deep Research's `clarify_with_user`)

The engine and state machine don't know or care that the I/O target is human.
The dispatcher handles routing, formatting, and timeout.

### D10: Algorithms as code, not as states

07 vs 07b tested two approaches to MCTS: algorithm phases as interpreter code
(8 states, UCT/backprop in Python) vs algorithm phases as explicit state machine
states (19 states, each MCTS phase a transition). The interpreter approach won.

Reason: the pure SM approach requires new states for every algorithm. MCTS
needs SELECT, EXPAND, FEEDBACK, ACTION_GEN, ACTION_EXEC, EVALUATE, BACKPROP,
DISCRIMINATE. An evolutionary loop needs different states. A research pipeline
needs yet another set. Each algorithm doubles the state machine size.

The interpreter approach: any algorithm is just code. MCTS, evolution,
pipelines, ReAct loops — all run inside INTERPRETING and yield when they
need I/O. The state machine stays at 8 states forever. The complexity lives
in the CODE, not in the STATES.

Tradeoff: less visibility (from outside, it's all "INTERPRETING"). Mitigated
by interpreter status annotations or logging.

### D11: Agent-as-a-string enables zero-infrastructure evolution

DGM uses Docker containers, git, patch chains, and a complex container lifecycle
to safely run self-modifying agents. Our architecture simplifies this radically:

- The agent's implementation IS a string (the code the interpreter runs)
- spawn(code_string) creates a child whose PROGRAM is that string
- The child runs in its own interpreter — natural isolation, no Docker needed
- The child can modify the string and complete() with the new version
- The parent receives the modified string and can spawn it for evaluation

The entire DGM evolutionary loop collapses to:
```python
agent_code = INITIAL_CODE  # a string
for generation in range(80):
    parent_code, _ = select(archive)
    diagnosis = ask("o1", f"Analyze and improve:\n{parent_code}")
    new_code = spawn(parent_code, task=f"Improve:\n{diagnosis}")
    score = evaluate(new_code, benchmarks)  # spawn on benchmark tasks
    archive.append((new_code, score))
```

No Docker. No git. No patch files. No container lifecycle. The mutation is
an LLM call that returns a modified string. The evaluation is spawning a child
whose behavior IS that string. This works because:
- The interpreter provides isolation (no open(), no os, no subprocess)
- spawn() provides a fresh state for each child
- complete() provides the return mechanism
- The string is portable — spawn it anywhere

DGM's infrastructure solved "how to safely run modified code." Our interpreter
already solves that problem. The evolutionary algorithm is ~15 lines.

### D12: Each distinct prompt is a distinct state

If the ENGINE selects a different prompt or model for a step, that step is
a different state. If the LLM always gets the same prompt and decides itself
what to do, that is one state.

Cline: one prompt ("you are a coding agent") → one LLM state (CALLING_LLM).
The same system prompt every turn. The LLM decides what tool to call.

PaperQA2: four prompts → four LLM states:
- DECIDING: "pick a tool" + tool schemas (agent_llm)
- SCORING_CHUNKS: "score this chunk 0-10 for: {question}" (summary_llm)
- GENERATING_ANSWER: "answer using this evidence" (llm)
- FORCE_ANSWERING: same prompt as GENERATING_ANSWER (llm)

Open Deep Research: three prompts → three LLM states:
- Supervisor reasoning (research_model)
- Researcher reasoning (research_model, different prompt)
- Compression (compression_model)

This principle determines whether an agent needs the universal 8-state machine
(one prompt, one LLM state) or an architecture-specific expanded machine
(multiple prompts, multiple LLM states). The b-variants (05b, 07b) expand
the machine because they model architectures with multiple distinct prompts.

### D13: The state machine IS the architecture, not an underlying layer

The state machine must express the architecture of each agent, not hide it.
If you draw a diagram from the transition table, you should see the product's
architecture — its pipeline stages, its decision points, its feedback loops.

The universal 8-state machine (01-08) is a useful proof that one engine CAN
run any algorithm. But it fails D12 and this requirement: all architectures
look identical (INTERPRETING ⇄ WAITING_IO). The diagram shows nothing about
what makes PaperQA2 different from Moatless or DGM.

The b-variants (05b, 07b) are the correct direction: the state machine IS
the architecture specification. DECIDING → SEARCHING_INDEX → ADDING_PAPERS
is PaperQA2. MCTS_SELECT → MCTS_EXPAND → MCTS_EVALUATE is Moatless.
You see it in the diagram.

This means: new snippets should follow the b-variant pattern by default.
States are cheap. The diagram is the documentation.

The interpreter approach (D10) remains valid for code WITHIN a state —
complex pure computation like UCT scoring or archive selection runs inside
a transition action. But the I/O-bearing phases (LLM calls, searches,
scoring) must be visible as distinct states.

## Use Case Catalog

Ten snippets demonstrate that the same state machine handles all architectures.
Each file has the identical S, E, T definitions. The differences are in the
code the interpreter runs and which yield functions it calls.

| File | Architecture Pattern | Yield Functions Used |
|---|---|---|
| `01-single-agent.py` | Single ReAct agent, user chats | shell_run, read, ask_user |
| `02-single-subagent.py` | Parent spawns one child, waits | spawn, ask, complete |
| `03-parallel-subagents.py` | Parent spawns N children in parallel | spawn_all, ask |
| `04-open-deep-research.py` | Supervisor + parallel researchers with coverage | spawn_all, ask, web_search, complete |
| `05-paperqa-toolselector.py` | LLM-driven tool selection, 6 research tools | paper_search, gather_evidence, gen_answer, complete |
| `05b-paperqa-pure-sm.py` | Same PaperQA2 as 05, architecture-specific SM (D12) | (pure SM: 14 states, each prompt a state) |
| `06-paperqa-pipeline.py` | Deterministic pipeline, no tool-selection LLM | paper_search, gather_evidence, gen_answer, ask, complete |
| `07-moatless-mcts.py` | MCTS tree search over code states | ask, edit, shell_run, ask_all, complete |
| `07b-moatless-mcts-pure-sm.py` | Same MCTS as 07, but with explicit SM states per phase | (pure SM, no interpreter) |
| `08-dgm-evolutionary.py` | Darwinian evolution of coding agents | ask, spawn, spawn_all, shell_run, complete |

07 vs 07b is an explicit comparison: interpreter approach (algorithm as code,
8 states) vs pure state machine approach (algorithm phases as states, 19 states).
The interpreter approach won for universality — see D10.

### How to write a new snippet (D13 style)

New snippets follow the b-variant pattern: the state machine IS the architecture.
The diagram should reveal what makes this product unique.

1. Define **persistent state** — infrastructure surviving across sessions
   (search indexes, vector stores, API clients). Draft classes or comments.
2. Define **session state** as a Python `@dataclass` — everything accumulated
   during one run beyond LLM messages (evidence, scores, tool history, cost).
   If nothing beyond messages, say so explicitly.
3. Define **states** — each distinct prompt or I/O-bearing phase is a state (D12).
   Pure computation phases can be states too if they are architecturally significant.
4. Define **events** — what triggers each transition.
5. Define **transitions** — the transition table IS the architecture specification.
6. Annotate each state: which dispatcher handles it, or "pure computation."
7. Write a trace showing one complete execution path through the states.

See `05b-paperqa-pure-sm.py` for the reference example with persistent state,
SessionState dataclass, architecture-specific states, and yield annotations.

## Architecture Components

### State Machine (per agent instance)

```
S = {IDLE, CALLING_LLM, INTERPRETING, WAITING_IO,
     DISPLAYING, CLEANING_UP, EXTRACTING, CONSOLIDATING}

E = {user_message, llm_response_tools, llm_response_text, llm_error,
     interpreter_done, interpreter_yield, interpreter_error,
     io_result, io_error, max_rounds_hit, display_done,
     extraction_needed, no_extraction, extraction_done,
     consolidation_needed, consolidation_done, error}
```

### Interpreter

Modified smolagents AST interpreter with yield/resume support.

Category 2 yield functions (I/O — yield and resume):
ask(), ask_all(), spawn(), spawn_all(), shell_run(), read(), write(),
edit(), web_search(), ask_user().
Each raises YieldException(Request(...)).
resume(result) restores state and injects the result.

Category 3 yield function (terminal — yield and stop):
complete(result). Raises TerminalException(result).
The interpreter never resumes. The result is delivered to the parent
(for subagents) or to the UI (for the root agent).

### Dispatchers

```
LLMDispatcher       — async LLM calls, max_concurrent configurable
ShellDispatcher     — sandboxed shell via Seatbelt, max_concurrent configurable
FileDispatcher      — file read/write/edit, max_concurrent configurable
HttpDispatcher      — web search, HTTP calls, max_concurrent configurable
AgentDispatcher     — creates child agent instances, delegates to engine
HumanDispatcher     — shows prompts, waits for user input, delivers response
```

### Engine

Manages multiple AgentInstance objects (parent + children).
Each has: id, state, event_queue, interpreter_state, session_file, parent_id.
Single asyncio event loop. Processes events from agents, routes I/O to dispatchers.
Children run first (depth-first priority).
When a child reaches IDLE, its result is pushed to the parent's event queue.

## How spawn_all Works (Technical Detail)

The LLM writes: `results = spawn_all([("topic A", "s"), ("topic B", "s")])`

1. Interpreter evaluates args: list of 2 task tuples
2. Interpreter hits `spawn_all` — recognized as yield function
3. Interpreter saves state (locals, AST position where `results` assignment is pending)
4. Raises `YieldException(Request(type="spawn_all", payload={tasks: [...]}))`
5. Engine catches it, state → WAITING_IO
6. Engine calls AgentDispatcher.submit() — creates child-1 and child-2
7. Both children start in IDLE, get user_message events
8. Engine processes their events (LLM calls, tool execution, etc.)
9. Children's I/O goes through dispatchers concurrently
10. child-1 finishes → engine records result
11. child-2 finishes → engine records result, all done
12. Engine delivers `io_result(["result1", "result2"])` to parent
13. Parent state → INTERPRETING, engine calls `interpreter.resume(["result1", "result2"])`
14. Interpreter restores state, `results = ["result1", "result2"]`
15. Interpreter continues executing the rest of the script

## Open Questions

### Q1: Rewrite or modify smolagents interpreter?

The smolagents LocalPythonExecutor is ~1000 lines. It already walks the AST node by node. Adding yield support means:
- Detecting calls to yield functions
- Saving the execution state (the hard part — need to serialize partial AST traversal)
- Restoring and continuing

Option A: Fork and modify LocalPythonExecutor. Keep the existing AST walking logic, add yield checkpoints.

Option B: Write our own interpreter from scratch, purpose-built for yield/resume. Simpler but more work upfront.

Decision deferred until we study the smolagents interpreter internals in detail.

### Q2: What about streaming LLM responses?

The main agent turn streams tokens to the terminal as they arrive. In the state machine, CALLING_LLM represents this streaming phase. Should streaming be modeled as a series of events (token_chunk) or as one async operation that completes with the full response?

Current alpha: streaming is handled inside run_turn() with an on_token callback. The state machine probably doesn't need to see individual tokens — just the final LLM response.

### Q3: File operations as yield points — worth it?

File operations (read, write, edit) are local and fast (microseconds). Making them yield points adds complexity for near-zero benefit in the single-agent case. The benefit is: consistency (all I/O is uniform), profiling (every operation goes through the engine), and future remote file systems.

Possible compromise: file operations yield in the interpreter (for state machine cleanliness) but the FileDispatcher completes synchronously (no actual async overhead). The yield/resume happens, but instantly.

### Q4: Budget and cost tracking

Each dispatcher knows the cost of its operations (LLM: tokens, Shell: time, File: ops). The engine aggregates. Where does budget enforcement live — in the state machine (a BUDGET_EXCEEDED event) or in the dispatchers (refuse to submit if budget is exhausted)?

### Q5: Domain detection

Currently domain detection runs before each turn via a separate fast LLM call. In the state machine, this could be:
- A separate DETECTING_DOMAIN state (as in the early iterations)
- A dispatcher call that happens as part of CALLING_LLM preparation
- Removed entirely and handled by the interpreter

Leaning toward: part of the compile_and_call_llm action, not a separate state. It's a pre-step, not a user-visible phase.

## Implementation Plan (Not Started)

1. Study smolagents LocalPythonExecutor internals — assess yield/resume feasibility
2. Prototype yield/resume in a standalone test
3. Implement the state machine engine with transition table
4. Implement dispatchers (LLM first, then shell, file, http)
5. Wire up the interpreter to yield instead of calling I/O directly
6. Replace the current engine.py and __main__.py
7. Add spawn() and spawn_all() as yield functions
8. Test: single agent works, single child works, parallel children work
