"""Use case 1: Single agent — decorator-based state machine.

Each state is its own type. Each transition is a standalone function.
The @machine.transition decorator auto-registers by type hints.

  machine.reduce(state, event) → new_state
  render(state) → UI
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sm import StateMachine


# ===================================================================
# States — each is its own type
# ===================================================================

@dataclass(frozen=True)
class AwaitingInput:
    """Waiting for user to type."""
    messages: tuple[dict, ...] = ()
    tokens_used: int = 0
    error: str | None = None

@dataclass(frozen=True)
class CallingLLM:
    """Waiting for LLM response."""
    messages: tuple[dict, ...]
    tokens_used: int
    round: int
    turns_since_extraction: int = 0
    extraction_threshold: int = 5

@dataclass(frozen=True)
class ExecutingCode:
    """Waiting for interpreter result."""
    messages: tuple[dict, ...]
    tokens_used: int
    round: int

@dataclass(frozen=True)
class Extracting:
    """Waiting for knowledge extraction."""
    messages: tuple[dict, ...]
    tokens_used: int

@dataclass(frozen=True)
class Consolidating:
    """Waiting for knowledge consolidation."""
    messages: tuple[dict, ...]
    tokens_used: int

AgentState = AwaitingInput | CallingLLM | ExecutingCode | Extracting | Consolidating


# ===================================================================
# Events
# ===================================================================

@dataclass(frozen=True)
class UserMessage:
    text: str

@dataclass(frozen=True)
class LLMResponseTools:
    code: str
    assistant_text: str
    tokens: int = 0

@dataclass(frozen=True)
class LLMResponseText:
    text: str
    tokens: int = 0

@dataclass(frozen=True)
class LLMError:
    error: str

@dataclass(frozen=True)
class CodeDone:
    results: list[str]

@dataclass(frozen=True)
class CodeError:
    error: str

@dataclass(frozen=True)
class ExtractionDone:
    pass

@dataclass(frozen=True)
class ConsolidationNeeded:
    pass

@dataclass(frozen=True)
class ConsolidationDone:
    pass


# ===================================================================
# Transitions — each is a standalone function
# ===================================================================

agent = StateMachine()


def _add_msg(msgs: tuple[dict, ...], role: str, content: str) -> tuple[dict, ...]:
    return msgs + ({"role": role, "content": content},)


@agent.transition
def on_user_message(state: AwaitingInput, event: UserMessage) -> CallingLLM:
    msgs = _add_msg(state.messages, "user", event.text)
    return CallingLLM(messages=msgs, tokens_used=state.tokens_used, round=0)


@agent.transition
def on_llm_tools(state: CallingLLM, event: LLMResponseTools) -> ExecutingCode:
    msgs = _add_msg(state.messages, "assistant", event.assistant_text)
    return ExecutingCode(messages=msgs, tokens_used=state.tokens_used + event.tokens, round=state.round + 1)


@agent.transition
def on_llm_text(state: CallingLLM, event: LLMResponseText) -> AwaitingInput | Extracting:
    msgs = _add_msg(state.messages, "assistant", event.text)
    tokens = state.tokens_used + event.tokens
    turns = state.turns_since_extraction + 1
    if turns >= state.extraction_threshold:
        return Extracting(messages=msgs, tokens_used=tokens)
    return AwaitingInput(messages=msgs, tokens_used=tokens)


@agent.transition
def on_llm_error(state: CallingLLM, event: LLMError) -> AwaitingInput:
    return AwaitingInput(messages=state.messages, tokens_used=state.tokens_used, error=event.error)


@agent.transition
def on_code_done(state: ExecutingCode, event: CodeDone) -> CallingLLM:
    msgs = _add_msg(state.messages, "tool", "\n".join(event.results))
    return CallingLLM(messages=msgs, tokens_used=state.tokens_used, round=state.round)


@agent.transition
def on_code_error(state: ExecutingCode, event: CodeError) -> CallingLLM:
    msgs = _add_msg(state.messages, "tool", f"Error: {event.error}")
    return CallingLLM(messages=msgs, tokens_used=state.tokens_used, round=state.round)


@agent.transition
def on_extraction_done(state: Extracting, event: ExtractionDone) -> AwaitingInput:
    return AwaitingInput(messages=state.messages, tokens_used=state.tokens_used)


@agent.transition
def on_consolidation_needed(state: Extracting, event: ConsolidationNeeded) -> Consolidating:
    return Consolidating(messages=state.messages, tokens_used=state.tokens_used)


@agent.transition
def on_consolidation_done(state: Consolidating, event: ConsolidationDone) -> AwaitingInput:
    return AwaitingInput(messages=state.messages, tokens_used=state.tokens_used)


# ===================================================================
# Render — pure function: state → UI
# ===================================================================

@dataclass
class UI:
    status: str
    prompt: str = ""
    spinner: bool = False
    error: str = ""

def render(state: AgentState) -> UI:
    match state:
        case AwaitingInput(tokens_used=t, error=err):
            return UI(status=f"Ready | {t} tokens", prompt="> ", error=err or "")
        case CallingLLM(round=r):
            return UI(status=f"Round {r} | thinking...", spinner=True)
        case ExecutingCode(round=r):
            return UI(status=f"Round {r} | running code...", spinner=True)
        case Extracting() | Consolidating():
            return UI(status="Organizing knowledge...", spinner=True)
    return UI(status="Unknown")


# ===================================================================
# Demo
# ===================================================================

def demo():
    print("=" * 55)
    print("Single Agent — Decorator-based SM")
    print("=" * 55)

    # Show registered transitions
    print("\n  Registered transitions:")
    for src, evt, fn in agent.transitions:
        print(f"    {src:16s} + {evt:20s} → {fn}")

    state: AgentState = AwaitingInput()

    def step(event, desc):
        nonlocal state
        old = type(state).__name__
        state = agent.reduce(state, event)
        print(f"  {old:16s} + {type(event).__name__:20s} → {type(state).__name__}")

    print("\n  Trace:\n")
    step(UserMessage("list PDFs > 10MB"), "")
    step(LLMResponseTools(code='shell_run("find ...")', assistant_text="Searching.", tokens=150), "")
    step(CodeDone(results=["found: /docs/report.pdf"]), "")
    step(LLMResponseText(text="Found 1 large PDF.", tokens=80), "")

    print(f"\n  Final: {type(state).__name__} | {state.tokens_used} tokens | {len(state.messages)} msgs")

    # Invalid transition
    print("\n  Invalid transition test:")
    try:
        agent.reduce(state, CodeDone(results=[]))
    except Exception as e:
        print(f"    {e}")


if __name__ == "__main__":
    demo()
