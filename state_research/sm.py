"""State machine framework — decorator-based transition registration.

Each transition is a standalone function with type hints.
The @transition decorator reads the hints and registers the handler.
The StateMachine builds reduce() from the registry automatically.

Usage:
    machine = StateMachine()

    @machine.transition
    def on_code_done(state: ExecutingCode, event: CodeDone) -> CallingLLM:
        return CallingLLM(messages=state.messages + ..., ...)

    @machine.transition
    def on_llm_text(state: CallingLLM, event: LLMResponseText) -> AwaitingInput:
        return AwaitingInput(messages=state.messages + ..., ...)

    # reduce() is built automatically
    new_state = machine.reduce(current_state, event)
"""

from __future__ import annotations

from typing import Any, Callable, get_type_hints


class InvalidTransition(Exception):
    def __init__(self, state_type: type, event_type: type, valid: list[type]):
        valid_names = [t.__name__ for t in valid]
        super().__init__(
            f"No transition from {state_type.__name__} on {event_type.__name__}. "
            f"Valid events: {valid_names}"
        )


class StateMachine:
    """Decorator-based state machine.

    Register transitions with @machine.transition.
    Call machine.reduce(state, event) to step.
    """

    def __init__(self):
        self._handlers: dict[tuple[type, type], Callable] = {}

    def transition(self, fn: Callable) -> Callable:
        """Register a transition handler. Types inferred from hints.

        @machine.transition
        def handle(state: SomeState, event: SomeEvent) -> NewState:
            return NewState(...)
        """
        hints = get_type_hints(fn)
        params = list(hints.keys())
        if len(params) < 2:
            raise TypeError(f"{fn.__name__}: need type hints for state and event parameters")

        state_type = hints[params[0]]
        event_type = hints[params[1]]

        key = (state_type, event_type)
        if key in self._handlers:
            existing = self._handlers[key].__name__
            raise ValueError(
                f"Duplicate transition: ({state_type.__name__}, {event_type.__name__}) "
                f"already handled by {existing}"
            )

        self._handlers[key] = fn
        return fn

    def reduce(self, state: Any, event: Any) -> Any:
        """Dispatch to the registered handler for (type(state), type(event))."""
        key = (type(state), type(event))
        handler = self._handlers.get(key)
        if handler is None:
            valid = [k[1] for k in self._handlers if k[0] == type(state)]
            raise InvalidTransition(type(state), type(event), valid)
        return handler(state, event)

    def valid_events(self, state: Any) -> list[type]:
        """Return event types valid for the given state."""
        return [k[1] for k in self._handlers if k[0] == type(state)]

    @property
    def transitions(self) -> list[tuple[str, str, str]]:
        """List all registered transitions as (state, event, handler_name)."""
        return [
            (k[0].__name__, k[1].__name__, v.__name__)
            for k, v in self._handlers.items()
        ]
