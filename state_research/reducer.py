"""State reducer pattern — pure functional core + stateful machine wrapper.

The reducer is a pure function: (state, event, table) → (new_state, actions).
No mutation, no side effects. The Machine wraps it with an event queue,
action dispatch, and transition history.

Works directly with existing S, E, T definitions from the snippet files.

Usage:
    from reducer import reduce, Machine, InvalidTransition

    # Pure functional — you manage state yourself
    result = reduce(S.IDLE, E.user_message, transitions)
    assert result.dst == S.CALLING_LLM
    assert result.actions == ("write_user_message", "compile_and_call_llm")

    # Stateful machine — manages state, queues events, dispatches actions
    m = Machine(transitions, initial=S.IDLE)
    result = m.send(E.user_message)
    assert m.state == S.CALLING_LLM

    # With action handlers that produce follow-up events
    async def compile_and_call_llm(ctx):
        response = await call_llm(ctx.messages)
        if response.has_tool_calls:
            return E.llm_response_tools
        return E.llm_response_text

    m = Machine(transitions, initial=S.IDLE, handlers={
        "compile_and_call_llm": compile_and_call_llm,
    })
    await m.run(E.user_message)  # runs until no more events
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, NamedTuple, Protocol, TypeVar


# ---------------------------------------------------------------------------
# Types — work with any S, E, T that follow the convention
# ---------------------------------------------------------------------------

class TransitionRow(Protocol):
    """Structural type for transition rows. Matches the T NamedTuple."""
    @property
    def src(self) -> Enum: ...
    @property
    def event(self) -> Enum: ...
    @property
    def dst(self) -> Enum: ...
    @property
    def actions(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class ReduceResult:
    """Immutable result of a single reduce step."""
    src: Enum
    event: Enum
    dst: Enum
    actions: tuple[str, ...]


class InvalidTransition(Exception):
    """No matching transition for (state, event) pair."""
    def __init__(self, state: Enum, event: Enum, valid_events: list[Enum] | None = None):
        self.state = state
        self.event = event
        self.valid_events = valid_events or []
        valid = ", ".join(e.name for e in self.valid_events) if self.valid_events else "none"
        super().__init__(
            f"No transition from {state.name} on {event.name}. "
            f"Valid events in {state.name}: [{valid}]"
        )


class AmbiguousTransition(Exception):
    """Multiple transitions match the same (state, event) pair."""
    def __init__(self, state: Enum, event: Enum, count: int):
        self.state = state
        self.event = event
        self.count = count
        super().__init__(
            f"Ambiguous: {count} transitions from {state.name} on {event.name}. "
            f"Transition table must be deterministic."
        )


# ---------------------------------------------------------------------------
# Pure reducer — the functional core
# ---------------------------------------------------------------------------

# Build a lookup dict on first call, cache it for subsequent calls.
# Key: (src, event) → (dst, actions). Deterministic: exactly one match.
_cache: dict[int, dict[tuple, ReduceResult]] = {}


def _build_lookup(table: list | tuple) -> dict[tuple, ReduceResult]:
    """Build a (src, event) → ReduceResult lookup from a transition table."""
    table_id = id(table)
    if table_id in _cache:
        return _cache[table_id]

    lookup: dict[tuple, ReduceResult] = {}
    for t in table:
        key = (t.src, t.event)
        if key in lookup:
            raise AmbiguousTransition(t.src, t.event, 2)
        lookup[key] = ReduceResult(src=t.src, event=t.event, dst=t.dst, actions=t.actions)

    _cache[table_id] = lookup
    return lookup


def reduce(state: Enum, event: Enum, table: list | tuple) -> ReduceResult:
    """Pure reducer: (state, event, table) → ReduceResult.

    No side effects. No mutation. Returns the new state and the actions
    to execute. Raises InvalidTransition if no matching row exists.
    Raises AmbiguousTransition if multiple rows match (on first build).
    """
    lookup = _build_lookup(table)
    key = (state, event)
    result = lookup.get(key)
    if result is None:
        # Collect valid events for this state — useful for error messages
        valid = sorted(
            [k[1] for k in lookup if k[0] == state],
            key=lambda e: e.value,
        )
        raise InvalidTransition(state, event, valid)
    return result


def valid_events(state: Enum, table: list | tuple) -> list[Enum]:
    """Return all events that are valid in the given state."""
    lookup = _build_lookup(table)
    return sorted(
        [k[1] for k in lookup if k[0] == state],
        key=lambda e: e.value,
    )


# ---------------------------------------------------------------------------
# Validation helpers — check a transition table for structural problems
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Results of validating a transition table."""
    unreachable_states: set[Enum] = field(default_factory=set)
    terminal_states: set[Enum] = field(default_factory=set)
    dead_events: set[Enum] = field(default_factory=set)
    total_states: int = 0
    total_events: int = 0
    total_transitions: int = 0
    ok: bool = True

    def __str__(self) -> str:
        lines = [
            f"States: {self.total_states}, Events: {self.total_events}, "
            f"Transitions: {self.total_transitions}",
        ]
        if self.unreachable_states:
            names = ", ".join(s.name for s in self.unreachable_states)
            lines.append(f"  Unreachable states (never a dst): {names}")
        if self.terminal_states:
            names = ", ".join(s.name for s in self.terminal_states)
            lines.append(f"  Terminal states (never a src): {names}")
        if self.dead_events:
            names = ", ".join(e.name for e in self.dead_events)
            lines.append(f"  Dead events (defined but unused): {names}")
        if self.ok:
            lines.append("  OK")
        return "\n".join(lines)


def validate(
    table: list | tuple,
    state_enum: type[Enum] | None = None,
    event_enum: type[Enum] | None = None,
    initial: Enum | None = None,
) -> ValidationReport:
    """Validate structural properties of a transition table.

    If state_enum / event_enum are provided, checks for unused members.
    If initial is provided, it's excluded from unreachable checks.
    """
    lookup = _build_lookup(table)  # also checks for ambiguity

    src_states = {t.src for t in table}
    dst_states = {t.dst for t in table}
    all_states = src_states | dst_states
    used_events = {t.event for t in table}

    report = ValidationReport(
        total_states=len(all_states),
        total_events=len(used_events),
        total_transitions=len(table),
    )

    # States that appear as dst but never as src — terminal/sink states
    report.terminal_states = dst_states - src_states

    # States that appear as src but never as dst — unreachable (except initial)
    unreachable = src_states - dst_states
    if initial and initial in unreachable:
        unreachable.discard(initial)
    report.unreachable_states = unreachable

    # Events defined in the enum but never used in any transition
    if event_enum:
        all_defined_events = set(event_enum)
        report.dead_events = all_defined_events - used_events

    report.ok = not (report.unreachable_states or report.dead_events)
    return report


# ---------------------------------------------------------------------------
# Machine — stateful wrapper with event queue and action dispatch
# ---------------------------------------------------------------------------

# Action handler signature:
#   sync:  def handler(context) -> Event | None
#   async: async def handler(context) -> Event | None
# Returning an Event enqueues it as the next event.
# Returning None means no follow-up event.

ActionHandler = Callable[..., Any]  # sync or async, returns Event | None


@dataclass
class StepRecord:
    """One step in the machine's history."""
    src: Enum
    event: Enum
    dst: Enum
    actions: tuple[str, ...]


class Machine:
    """Stateful state machine with event queue and action dispatch.

    The machine wraps the pure reduce() function with:
    - Mutable current state
    - FIFO event queue
    - Action handler registry (handlers return follow-up events)
    - Transition history for debugging/tracing
    """

    def __init__(
        self,
        table: list | tuple,
        initial: Enum,
        handlers: dict[str, ActionHandler] | None = None,
        context: Any = None,
    ):
        self._table = table
        self._state = initial
        self._handlers = handlers or {}
        self._context = context
        self._queue: list[Enum] = []
        self._history: list[StepRecord] = []

        # Pre-build lookup on init — catches AmbiguousTransition early
        _build_lookup(table)

    @property
    def state(self) -> Enum:
        return self._state

    @property
    def context(self) -> Any:
        return self._context

    @context.setter
    def context(self, value: Any) -> None:
        self._context = value

    @property
    def history(self) -> list[StepRecord]:
        return list(self._history)

    @property
    def pending_events(self) -> list[Enum]:
        return list(self._queue)

    def valid_events(self) -> list[Enum]:
        """Events that are valid in the current state."""
        return valid_events(self._state, self._table)

    # --- Synchronous API ---

    def send(self, event: Enum) -> ReduceResult:
        """Process one event synchronously. No action dispatch.

        Updates state, records history, returns the result.
        Use this when you handle actions yourself.
        """
        result = reduce(self._state, event, self._table)
        self._history.append(StepRecord(
            src=result.src, event=result.event,
            dst=result.dst, actions=result.actions,
        ))
        self._state = result.dst
        return result

    def enqueue(self, event: Enum) -> None:
        """Add an event to the queue."""
        self._queue.append(event)

    # --- Async API with action dispatch ---

    async def dispatch(self, event: Enum) -> ReduceResult:
        """Process one event: reduce + execute action handlers.

        Each handler can return a follow-up Event, which is enqueued.
        Returns the reduce result (does NOT process follow-up events).
        """
        result = self.send(event)

        for action_name in result.actions:
            handler = self._handlers.get(action_name)
            if handler is None:
                continue  # unhandled action — skip silently

            # Call handler — support both sync and async
            if asyncio.iscoroutinefunction(handler):
                follow_up = await handler(self._context)
            else:
                follow_up = handler(self._context)

            # If handler returns an Event, enqueue it
            if follow_up is not None and isinstance(follow_up, Enum):
                self._queue.append(follow_up)

        return result

    async def run(self, event: Enum | None = None, max_steps: int = 1000) -> list[StepRecord]:
        """Process events until the queue is empty.

        Starts with the given event (if any), then drains the queue.
        Each step: reduce → execute handlers → handlers may enqueue events.
        Returns the list of steps executed.

        Safety: stops after max_steps to prevent infinite loops.
        """
        steps: list[StepRecord] = []

        if event is not None:
            self._queue.append(event)

        step_count = 0
        while self._queue and step_count < max_steps:
            next_event = self._queue.pop(0)
            result = await self.dispatch(next_event)
            steps.append(self._history[-1])
            step_count += 1

        if step_count >= max_steps:
            raise RuntimeError(
                f"Machine.run() hit max_steps={max_steps}. "
                f"State={self._state.name}, queue={[e.name for e in self._queue]}"
            )

        return steps

    # --- Debug ---

    def trace(self) -> str:
        """Human-readable trace of all transitions so far."""
        lines = []
        for i, step in enumerate(self._history):
            actions = ", ".join(step.actions) if step.actions else "-"
            lines.append(
                f"  {i:3d}. {step.src.name} --[{step.event.name}]--> "
                f"{step.dst.name}  ({actions})"
            )
        return "\n".join(lines)
