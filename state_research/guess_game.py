"""Guess-the-number game — state reducer pattern.

Each state is its own type. No tag field — the type IS the state.
Pattern matching on state type + event type.

  reduce: (state, event) → new state
  render: state → UI string
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace


# ---------------------------------------------------------------------------
# States — each is its own type with exactly the data it needs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RequestingRange:
    """Waiting for user to enter the max range."""
    error: str = ""

@dataclass(frozen=True)
class WaitingGuess:
    """Secret chosen, waiting for user to guess."""
    max_range: int
    secret: int
    attempts: int = 0
    hint: str = ""

@dataclass(frozen=True)
class Success:
    """User guessed correctly."""
    secret: int
    attempts: int

State = RequestingRange | WaitingGuess | Success


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RangeEntered:
    n: int

@dataclass(frozen=True)
class GuessEntered:
    n: int

Event = RangeEntered | GuessEntered


# ---------------------------------------------------------------------------
# Reducer — pure function: (state, event) → new state
# ---------------------------------------------------------------------------

def reduce(state: State, event: Event) -> State:
    match (state, event):

        case (RequestingRange(), RangeEntered(n=n)) if n >= 2:
            return WaitingGuess(max_range=n, secret=random.randint(1, n))

        case (RequestingRange(), RangeEntered(n=n)):
            return RequestingRange(error=f"need a number >= 2, got {n}")

        case (WaitingGuess(secret=secret), GuessEntered(n=n)) if n == secret:
            return Success(secret=secret, attempts=state.attempts + 1)

        case (WaitingGuess(), GuessEntered(n=n)):
            hint = "higher" if n < state.secret else "lower"
            return replace(state, attempts=state.attempts + 1, hint=hint)

        case _:
            return state


# ---------------------------------------------------------------------------
# Render — pure function: state → UI string
# ---------------------------------------------------------------------------

def render(state: State) -> str:
    match state:
        case RequestingRange(error=err):
            msg = "Enter the max range (e.g. 100): "
            if err:
                msg = f"  [{err}]\n{msg}"
            return msg

        case WaitingGuess(max_range=r, hint=hint, attempts=a):
            msg = f"Guess a number between 1 and {r}: "
            if hint:
                msg = f"  [try {hint}!]\n{msg}"
            if a > 0:
                msg = f"  (attempt #{a + 1})\n{msg}"
            return msg

        case Success(secret=s, attempts=a):
            return f"\n  Correct! The number was {s}.\n  You got it in {a} attempt(s).\n"

    return ""


# ---------------------------------------------------------------------------
# Game loop
# ---------------------------------------------------------------------------

def parse_input(state: State, raw: str) -> Event | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    match state:
        case RequestingRange():
            return RangeEntered(n)
        case WaitingGuess():
            return GuessEntered(n)
    return None


def main():
    state: State = RequestingRange()
    while not isinstance(state, Success):
        raw = input(render(state))
        event = parse_input(state, raw)
        if event is None:
            print("  [please enter a valid number]")
            continue
        state = reduce(state, event)
    print(render(state))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo():
    print("=" * 50)
    print("DEMO: Scripted guessing game")
    print("=" * 50)

    state: State = RequestingRange()
    print(f"  state: {type(state).__name__}")

    state = reduce(state, RangeEntered(n=10))
    print(f"  RangeEntered(10) → {type(state).__name__}  secret={state.secret}")

    # Force secret to 7
    state = WaitingGuess(max_range=10, secret=7)
    print(f"  (forced secret=7)")

    state = reduce(state, GuessEntered(n=5))
    print(f"  GuessEntered(5)  → {type(state).__name__}  hint={state.hint!r}  attempts={state.attempts}")

    state = reduce(state, GuessEntered(n=8))
    print(f"  GuessEntered(8)  → {type(state).__name__}  hint={state.hint!r}  attempts={state.attempts}")

    state = reduce(state, GuessEntered(n=7))
    print(f"  GuessEntered(7)  → {type(state).__name__}  attempts={state.attempts}")

    print()
    print(render(state))


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        demo()
    else:
        main()
