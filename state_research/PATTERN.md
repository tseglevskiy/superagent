# State Reducer Pattern

A specification for building state machines in Python.
Every design decision is explained with reasoning.
Follow this document — do not invent alternatives.


## Core Idea

The entire system is described by three pure functions:

```
reduce: (state, event) → new_state
render: state → UI
enter:  state → event           (the I/O boundary)
```

**reduce** is the brain — it decides the next state based on what happened.
**render** is the view — it derives what the user sees from the current state.
**enter** is the body — it does the actual work and reports what happened.

The runtime loop is:

```python
state = initial_state
while True:
    show(render(state))                   # display UI
    event = await enter(state)            # do I/O, produce event
    state = machine.reduce(state, event)  # pure transition
```

Two kinds of operations: pure (reduce, render) and impure (enter).
They never mix. reduce never does I/O. enter never changes state.


## States

Each state is its own frozen dataclass.
The type IS the state — no enum tags, no discriminator fields.

```python
@dataclass(frozen=True)
class AwaitingInput:
    messages: tuple[dict, ...] = ()
    tokens_used: int = 0
    error: str | None = None

@dataclass(frozen=True)
class CallingLLM:
    messages: tuple[dict, ...]
    tokens_used: int
    round: int
```

### Why separate types, not an enum tag in a shared dataclass

A shared dataclass with a tag field (e.g., `AgentState(tag=CALLING_LLM, ...)`) means
every state carries every field, even irrelevant ones. `AwaitingInput` would have a
`round` field that means nothing. Each state as its own type carries exactly the data
it needs. When you look at `CallingLLM`, you see its data — no guessing.

This is the Python equivalent of Kotlin's sealed classes.

### Why frozen

States are immutable. `reduce()` returns a NEW state — the old one is untouched.
This makes the system predictable: you can log every state, replay transitions,
compare before/after, and never worry about mutation bugs.

### Shared fields

Some fields appear in multiple states (e.g., `messages`, `tokens_used`).
Repeat them. Each state is self-contained. Do not use inheritance or base classes
to share fields — it adds complexity for no benefit in this pattern.

### Naming

State class names describe what the machine is waiting for:
- `AwaitingInput` — waiting for user to type
- `CallingLLM` — waiting for LLM response
- `ExecutingCode` — waiting for interpreter result

Not verbs (`CallLLM`), not past tense (`CalledLLM`), not generic (`Idle`).
The name answers: "what are we waiting for right now?"


## Events

Each event is a frozen dataclass carrying the data that arrived.

```python
@dataclass(frozen=True)
class LLMResponseTools:
    code: str
    assistant_text: str
    tokens: int = 0

@dataclass(frozen=True)
class CodeDone:
    results: list[str]
```

Events describe what happened in the outside world.
They carry all the data the reducer needs to make a decision.
They are produced by the `enter` function (the I/O boundary), never by the reducer.

### When to use one event vs two

Use **separate event types** when the distinction comes from the outside world —
the reducer cannot determine which case applies from state data alone.
The runtime observes the world and picks the right event type.

```python
# Separate events — runtime decides
LLMResponseTools   # LLM returned code
LLMResponseText    # LLM returned text only
LLMError           # LLM call failed
```

Use a **guard clause** (if/else inside the transition function) when the
distinction depends on data already in the state.

```python
# Guard clause — reducer decides
@agent.transition
def on_llm_text(state: CallingLLM, event: LLMResponseText) -> AwaitingInput | Extracting:
    if state.turns_since_extraction >= state.extraction_threshold:
        return Extracting(...)   # guard: state data determines destination
    return AwaitingInput(...)
```

Rule: **if the reducer knows enough to decide, use a guard.
If it needs external observation, use separate events.**


## Transitions

Each transition is a standalone function decorated with `@machine.transition`.
The decorator reads the type hints and registers the handler automatically.

```python
agent = StateMachine()

@agent.transition
def on_code_done(state: ExecutingCode, event: CodeDone) -> CallingLLM:
    msgs = state.messages + ({"role": "tool", "content": "\n".join(event.results)},)
    return CallingLLM(messages=msgs, tokens_used=state.tokens_used, round=state.round)
```

### How dispatch works

The framework maintains a registry: `{(state_type, event_type): handler_function}`.
When `machine.reduce(state, event)` is called, it looks up `(type(state), type(event))`
and calls the matching handler. One pair = one handler. Deterministic.

### Return type

The return type hint documents which states this transition can produce.
Use a union when the transition has a guard clause:

```python
def on_guess(state: WaitingGuess, event: GuessEntered) -> WaitingGuess | Success:
```

The framework does NOT use the return type for dispatch — only the first two
parameter types matter.

### No big match/case block

There is no central `reduce()` function with a giant match/case.
Each transition is independent. Adding a new transition = adding a new function.
Removing a transition = removing a function. No other code changes.

### What a transition function does

1. Reads data from the old state and the event
2. Computes the new state data (pure computation, no I/O)
3. Returns a new state object

That's it. No side effects. No commands. No I/O.


## Render

A pure function from state to UI description.

```python
def render(state: AgentState) -> UI:
    match state:
        case AwaitingInput(tokens_used=t, error=err):
            return UI(status=f"Ready | {t} tokens", prompt="> ", error=err or "")
        case CallingLLM(round=r):
            return UI(status=f"Round {r} | thinking...", spinner=True)
```

In a real application, `UI` could be a widget tree (Flutter), JSX (React),
Composable (Android), or HTML. Here it is a plain dataclass.

There is no `DISPLAYING` state. The UI is always derived from whatever
the current state is. Every state has a visual representation.


## Entry Actions (The I/O Boundary)

When the machine enters a new state, something must happen in the real world.
The entry action is the function that does that work and produces the next event.

Every state has exactly one entry action. It is either:
- **An async function** — a single I/O operation (LLM call, user input)
- **A sub-state-machine** — a multi-step process with its own states

There is no third category.

### Async function entry

```python
@agent.on_enter(CallingLLM)
async def enter_calling_llm(state: CallingLLM) -> LLMResponseTools | LLMResponseText | LLMError:
    response = await llm.call(state.messages)
    if response.has_tools:
        return LLMResponseTools(code=response.code, ...)
    return LLMResponseText(text=response.text, ...)

@agent.on_enter(AwaitingInput)
async def enter_awaiting_input(state: AwaitingInput) -> UserMessage:
    text = await get_user_input()
    return UserMessage(text=text)
```

### Sub-SM entry (delegation)

When the entry action is a multi-step process with its own internal states,
it is a separate state machine. The runtime:

1. Creates the sub-SM with an initial state derived from the parent state
2. Runs the sub-SM to a terminal state (its own reduce/enter cycle)
3. Maps the terminal state to a parent event

```python
agent.delegate(
    state=ExecutingCode,
    machine=interpreter,
    initial=lambda s: Running(code=s.code),
    mapping={
        Done:  lambda s: CodeDone(results=s.results),
        Error: lambda s: CodeError(error=s.error),
    },
)
```

The parent SM knows nothing about the sub-SM's internal states.
It just sees `ExecutingCode` → eventually → `CodeDone` or `CodeError`.


## When to Extract a Separate State Machine

A group of states should be extracted into a separate SM when:

1. **Independence** — the states form a self-contained cycle that does not
   need to know about the parent's concerns. The interpreter handles I/O
   (RUNNING ⇄ WAITING_IO) without knowing about LLMs, users, or extraction.

2. **Reusability** — the same cycle could be used by different parents.
   The interpreter SM works identically whether called by a single agent,
   a subagent, or a test harness.

3. **Multiple instances** — the parent may need to run multiple copies
   concurrently. The interpreter SM can be instantiated many times.

4. **Clean boundary** — the parent only cares about the final result,
   not the internal steps. The parent sends one thing in (code) and
   gets one thing back (results or error).

Do NOT extract a separate SM when:
- The states are tightly coupled to the parent's data
- There is only one caller and no reuse prospect
- The "sub-SM" has only one state (just use an async function)

### The litmus test

Ask: "Does the parent need to know about the internal states?"
If no → extract. If yes → keep in the parent.

The agent does not need to know that the interpreter does
RUNNING → WAITING_IO → RUNNING → DONE. It only needs CodeDone.
So the interpreter is a separate SM.

The agent DOES need to know about CallingLLM vs ExecutingCode
because they have different data and different event sets.
So they stay in the agent SM.


## The Runtime

The runtime is the only impure component. It connects the pure pieces:

```python
state = AwaitingInput()
while True:
    show(render(state))
    event = await machine.enter(state)
    state = machine.reduce(state, event)
```

For sub-SM delegation, the runtime runs the sub-SM's own loop to completion
before producing the parent event. The parent SM is paused while the sub-SM runs.

The runtime also handles:
- Error recovery (if enter() throws, produce an error event)
- Logging (log every state transition)
- Persistence (save state to disk for crash recovery)


## Modeling Rules

### Each distinct prompt is a distinct state

When modeling an architecture as a state machine, count the distinct prompts
or models the system uses. Each one is a separate state.

Simple agent (one prompt, LLM decides what to do): one LLM state.
Research agent (four prompts for different phases): four LLM states.

This rule determines whether an architecture needs 3 states or 15.

### The state machine IS the architecture

The diagram generated from the registered transitions should reveal the
product's architecture — its pipeline stages, decision points, feedback loops.

`AwaitingInput → CallingLLM ⇄ ExecutingCode` is a simple ReAct agent.
`Deciding → SearchingIndex → AddingPapers → Deciding` is PaperQA2.
`Selecting → Expanding → Evaluating → Backpropagating` is MCTS.

If two different architectures produce the same diagram, the model is wrong —
something is hidden.

### Every state waits for something external

A state represents the machine waiting for an event from the outside world.
The machine does not distinguish between waiting for a human, an LLM,
a shell command, or a child state machine — they are all external I/O.

If a state does not wait for anything external, it is not a state —
it is a computation that belongs inside a transition function.


## Summary of Rules

1. States are frozen dataclasses. The type IS the state.
2. Events are frozen dataclasses carrying data from the outside world.
3. Transitions are standalone functions with `@machine.transition`.
4. The reducer is pure — no I/O, no side effects, no commands.
5. Render is pure — state → UI. No DISPLAYING state.
6. Entry actions produce the next event. They are either async functions or sub-SMs.
7. Separate events for external observations. Guard clauses for state-data decisions.
8. Extract a sub-SM when the states are independent, reusable, and the parent only needs the final result.
9. No enum tags. No tag fields. No big match/case reducers. No commands/actions.
10. The runtime loop: render → enter → reduce. Pure and impure never mix.
