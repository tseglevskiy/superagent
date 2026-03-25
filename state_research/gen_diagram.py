#!/usr/bin/env python3
"""Generate Mermaid stateDiagram-v2 from a decorator-based state machine.

Imports the Python file, finds StateMachine instances, reads registered
transitions + return type hints, and writes a .mmd file.

Usage:
    python3 gen_diagram.py 01-single-agent-elm.py
    python3 gen_diagram.py guess_game.py
    python3 gen_diagram.py --all
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import get_args, get_type_hints

from sm import StateMachine


def load_module(path: Path):
    """Import a .py file as a module."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod  # register before exec (Python 3.14 dataclass needs this)
    spec.loader.exec_module(mod)
    return mod


def find_machines(mod) -> dict[str, StateMachine]:
    """Find all StateMachine instances in a module."""
    machines = {}
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, StateMachine):
            machines[name] = obj
    return machines


def extract_return_types(fn) -> list[type]:
    """Extract target state types from a transition function's return hint.

    Handles:
      -> CallingLLM                     → [CallingLLM]
      -> WaitingGuess | Success         → [WaitingGuess, Success]
      -> AwaitingInput | Extracting     → [AwaitingInput, Extracting]
    """
    hints = get_type_hints(fn)
    ret = hints.get("return")
    if ret is None:
        return []

    # Check if it's a union type (X | Y)
    args = get_args(ret)
    if args:
        return list(args)

    # Single type
    return [ret]


def extract_title(mod) -> str:
    """Extract title from module docstring."""
    doc = getattr(mod, "__doc__", None)
    if doc:
        first_line = doc.strip().split("\n")[0]
        if first_line.startswith("Use case"):
            _, _, rest = first_line.partition(":")
            return rest.strip().rstrip(".")
        return first_line.rstrip(".")
    return mod.__name__


def generate_mermaid(machine: StateMachine, title: str) -> str:
    """Generate Mermaid stateDiagram-v2 from a StateMachine's registry."""

    lines = [
        "---",
        f'title: "{title}"',
        "---",
        "stateDiagram-v2",
    ]

    # Collect all states and edges
    all_states: set[str] = set()
    edges: list[tuple[str, str, str]] = []  # (src, dst, event)

    for (state_type, event_type), handler in machine._handlers.items():
        src = state_type.__name__
        event = event_type.__name__
        all_states.add(src)

        targets = extract_return_types(handler)
        if not targets:
            # No return hint — skip (shouldn't happen with our pattern)
            continue

        for target in targets:
            dst = target.__name__
            all_states.add(dst)
            edges.append((src, dst, event))

    # Find initial state
    dst_states = {dst for _, dst, _ in edges}
    src_states = {src for src, _, _ in edges}
    # Prefer: state that is source but never destination
    initial_candidates = src_states - dst_states
    if not initial_candidates:
        # All states are both — use heuristic: "Awaiting*" or first alphabetically
        initial_candidates = {s for s in src_states if s.startswith("Awaiting")}
    if not initial_candidates:
        initial_candidates = src_states
    initial = sorted(initial_candidates)[0]
    lines.append(f"    [*] --> {initial}")
    lines.append("")

    # Group edges by source for readability
    by_src: dict[str, list[tuple[str, str]]] = {}
    for src, dst, event in edges:
        by_src.setdefault(src, []).append((dst, event))

    for src in sorted(by_src.keys()):
        for dst, event in by_src[src]:
            lines.append(f"    {src} --> {dst} : {event}")
        lines.append("")

    # Find terminal states (appear as dst but never as src)
    terminal = dst_states - src_states
    for t in sorted(terminal):
        lines.append(f"    {t} --> [*]")

    return "\n".join(lines)


def process_file(path: Path):
    """Load module, find machines, generate mermaid for each."""
    mod = load_module(path)
    machines = find_machines(mod)

    if not machines:
        print(f"  SKIP {path.name}: no StateMachine instances found")
        return []

    title = extract_title(mod)
    generated = []

    for name, machine in machines.items():
        if len(machines) > 1:
            suffix = f"-{name}"
            full_title = f"{title} ({name})"
        else:
            suffix = ""
            full_title = title

        mermaid = generate_mermaid(machine, full_title)
        out_path = path.with_suffix("").with_name(path.stem + suffix + ".mmd")
        out_path.write_text(mermaid + "\n")
        print(f"  {path.name} → {out_path.name}  ({len(machine._handlers)} transitions)")
        generated.append(out_path)

    return generated


def main():
    here = Path(__file__).parent
    all_snippets = sorted(here.glob("[0-9]*-elm.py"))

    if len(sys.argv) < 2 or "--all" in sys.argv:
        files = all_snippets
    else:
        files = []
        for f in sys.argv[1:]:
            path = here / f if not Path(f).is_absolute() else Path(f)
            if path.exists():
                files.append(path)
            else:
                matched = [s for s in all_snippets if f in s.name]
                files.extend(matched)
        seen = set()
        files = [f for f in files if f not in seen and not seen.add(f)]

    if not files:
        print("No files to process.")
        sys.exit(1)

    print(f"Generating diagrams for {len(files)} file(s):")
    generated = []
    for f in files:
        if f.name == Path(__file__).name:
            continue
        result = process_file(f)
        generated.extend(result)

    print(f"\nDone: {len(generated)} diagram(s) generated.")


if __name__ == "__main__":
    main()
