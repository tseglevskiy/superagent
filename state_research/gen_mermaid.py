#!/usr/bin/env python3
"""Generate Mermaid stateDiagram-v2 from a state_research snippet.

Imports the snippet as a Python module, reads S, E, and transitions,
and writes a .mmd file next to the source.

Usage:
    python3 gen_mermaid.py 01-single-agent.py
    python3 gen_mermaid.py 05b-paperqa-pure-sm.py
    python3 gen_mermaid.py *.py          # all snippets
    python3 gen_mermaid.py --all         # all snippets in this directory
"""

import importlib.util
import sys
from pathlib import Path


def load_module(path: Path):
    """Import a .py file as a module and return it."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extract_title(mod) -> str:
    """Extract a short title from the module docstring's first line."""
    doc = getattr(mod, "__doc__", None)
    if doc:
        first_line = doc.strip().split("\n")[0]
        # Strip "Use case N: " prefix if present
        if first_line.startswith("Use case"):
            _, _, rest = first_line.partition(":")
            return rest.strip().rstrip(".")
        return first_line.rstrip(".")
    return mod.__name__


def generate_mermaid(mod) -> str:
    """Generate Mermaid stateDiagram-v2 from module's S, E, transitions."""
    S = mod.S
    E = mod.E
    transitions = mod.transitions

    title = extract_title(mod)

    lines = [
        "---",
        f'title: "{title}"',
        "---",
        "stateDiagram-v2",
    ]

    # Find the initial state (first member of S enum, typically IDLE)
    initial = list(S)[0]
    lines.append(f"    [*] --> {initial.name}")
    lines.append("")

    # Group transitions by source state for readability
    by_src: dict[str, list] = {}
    for t in transitions:
        by_src.setdefault(t.src.name, []).append(t)

    for src_name in [s.name for s in S]:
        if src_name not in by_src:
            continue
        for t in by_src[src_name]:
            event = t.event.name
            actions = ", ".join(t.actions) if t.actions else ""
            # Build label: event name + actions (if any)
            if actions:
                label = f"{event}<br/>{actions}"
            else:
                label = event
            lines.append(f"    {t.src.name} --> {t.dst.name} : {label}")
        lines.append("")

    return "\n".join(lines)


def process_file(path: Path):
    """Load snippet, generate mermaid, write .mmd file."""
    mod = load_module(path)

    # Check it has the required attributes
    for attr in ("S", "E", "transitions"):
        if not hasattr(mod, attr):
            print(f"  SKIP {path.name}: no '{attr}' attribute")
            return None

    mermaid = generate_mermaid(mod)
    out_path = path.with_suffix(".mmd")
    out_path.write_text(mermaid + "\n")
    print(f"  {path.name} -> {out_path.name}")
    return out_path


def main():
    here = Path(__file__).parent
    all_snippets = sorted(here.glob("[0-9]*.py"))

    if len(sys.argv) < 2 or "--all" in sys.argv:
        files = all_snippets
    else:
        # Support both exact filenames and partial filters (e.g., "09", "paperqa")
        filters = sys.argv[1:]
        files = []
        for f in filters:
            path = here / f if not Path(f).is_absolute() else Path(f)
            if path.exists():
                files.append(path)
            else:
                # Treat as filter string — match against all snippet filenames
                matched = [s for s in all_snippets if f in s.name]
                files.extend(matched)
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for f in files:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        files = unique

    if not files:
        print("No files to process.")
        sys.exit(1)

    print(f"Generating Mermaid diagrams for {len(files)} file(s):")
    generated = []
    for f in files:
        if not f.exists():
            print(f"  SKIP {f}: not found")
            continue
        if f.name == Path(__file__).name:
            continue  # skip self
        result = process_file(f)
        if result:
            generated.append(result)

    print(f"\nDone: {len(generated)} diagram(s) generated.")


if __name__ == "__main__":
    main()
