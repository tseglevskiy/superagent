"""Use case 8: DGM — evolutionary loop that evolves coding agents.

Two-loop architecture: outer Darwinian evolution + inner coding agent.
NOT a ReAct agent — the outer loop is a fixed evolutionary algorithm.
The LLM is a mutation operator, not a reasoning agent.

Our simplification vs real DGM (see D11 in DESIGN.md):
  DGM uses Docker containers, git, patch chains — because it needs
  the modified agent to run pytest, access the filesystem, etc.
  We don't need any of that. The agent's implementation IS a string.
  spawn(code_string) creates a child whose PROGRAM is that string.
  The interpreter IS the sandbox. No Docker, no files, no git.

The outer loop: select parent → diagnose → mutate → evaluate → archive
The inner loop: spawn(agent_code, task) — child runs, returns result

Key mapping to our architecture:
  Outer evolutionary loop = code in the root interpreter
  Diagnosis (o1)          = ask("o1", ...) — yield
  Mutation                = spawn(parent_code, task=diagnosis) — yield, child edits
                            the code string and complete()s with new version
  Evaluation              = spawn_all(new_code, benchmark_tasks) — yield, children
                            run the mutated code on tasks, complete() with results
  Selection, archive      = pure computation (no yields)

The state machine is IDENTICAL to 01-07.
An evolutionary algorithm is just code that calls ask() and spawn().
"""

from enum import Enum, auto
from typing import NamedTuple


# State machine: IDENTICAL to 01-07.
class S(Enum):
    IDLE = auto()
    CALLING_LLM = auto()
    INTERPRETING = auto()
    WAITING_IO = auto()
    DISPLAYING = auto()
    CLEANING_UP = auto()
    EXTRACTING = auto()
    CONSOLIDATING = auto()

class E(Enum):
    user_message = auto()
    llm_response_tools = auto()
    llm_response_text = auto()
    llm_error = auto()
    interpreter_done = auto()
    interpreter_yield = auto()
    interpreter_error = auto()
    io_result = auto()
    io_error = auto()
    max_rounds_hit = auto()
    display_done = auto()
    extraction_needed = auto()
    no_extraction = auto()
    extraction_done = auto()
    consolidation_needed = auto()
    consolidation_done = auto()
    error = auto()

class T(NamedTuple):
    src: S
    event: E
    dst: S
    actions: tuple[str, ...]

transitions: list[T] = [
    T(S.IDLE,           E.user_message,         S.CALLING_LLM,    ("write_user_message", "compile_and_call_llm")),
    T(S.CALLING_LLM,    E.llm_response_tools,   S.INTERPRETING,   ("record_budget", "write_assistant_msg", "start_interpreter")),
    T(S.CALLING_LLM,    E.llm_response_text,    S.DISPLAYING,     ("record_budget", "write_assistant_msg")),
    T(S.CALLING_LLM,    E.llm_error,            S.IDLE,           ("display_error",)),
    T(S.INTERPRETING,   E.interpreter_done,      S.CALLING_LLM,    ("write_tool_results", "compile_and_call_llm")),
    T(S.INTERPRETING,   E.interpreter_yield,     S.WAITING_IO,     ("submit_to_dispatcher",)),
    T(S.INTERPRETING,   E.interpreter_error,     S.CALLING_LLM,    ("write_tool_error", "compile_and_call_llm")),
    T(S.INTERPRETING,   E.max_rounds_hit,        S.DISPLAYING,     ("display_max_rounds",)),
    T(S.WAITING_IO,     E.io_result,             S.INTERPRETING,   ("resume_interpreter",)),
    T(S.WAITING_IO,     E.io_error,              S.INTERPRETING,   ("resume_interpreter_with_error",)),
    T(S.DISPLAYING,     E.display_done,          S.CLEANING_UP,    ()),
    T(S.CLEANING_UP,    E.extraction_needed,     S.EXTRACTING,     ("cleanup_integrations",)),
    T(S.CLEANING_UP,    E.no_extraction,         S.IDLE,           ("cleanup_integrations",)),
    T(S.EXTRACTING,     E.extraction_done,       S.IDLE,           ()),
    T(S.EXTRACTING,     E.consolidation_needed,  S.CONSOLIDATING,  ()),
    T(S.EXTRACTING,     E.error,                 S.IDLE,           ("display_error",)),
    T(S.CONSOLIDATING,  E.consolidation_done,    S.IDLE,           ()),
    T(S.CONSOLIDATING,  E.error,                 S.IDLE,           ("display_error",)),
]


# ---------------------------------------------------------------------------
# The evolutionary loop — agent-as-a-string model
# ---------------------------------------------------------------------------
#
# The agent's implementation IS a string. No files, no Docker, no git.
# spawn(code) creates a child whose PROGRAM is that code string.
# The child runs in its own interpreter — natural isolation.

EVOLUTIONARY_LOOP = """
import json, random, math

# --- Archive: list of (agent_code_string, score) ---

archive = [(INITIAL_AGENT_CODE, 0.20)]

def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))

def select_parent(archive, method="score_child_prop"):
    if method == "score_child_prop":
        children_count = {}  # track how many times each was selected
        weights = [sigmoid(score) / (1 + children_count.get(i, 0))
                   for i, (code, score) in enumerate(archive)]
    elif method == "score_prop":
        weights = [sigmoid(10 * (score - 0.5)) for _, score in archive]
    elif method == "best":
        return max(archive, key=lambda x: x[1])
    else:
        return random.choice(archive)
    total = sum(weights)
    probs = [w / total for w in weights]
    return random.choices(archive, weights=probs, k=1)[0]


max_generations = 80

for generation in range(max_generations):
    parent_code, parent_score = select_parent(archive)

    # DIAGNOSE: what should improve? (yield → LLMDispatcher)
    diagnosis = ask("o1",
        f"Analyze this coding agent and propose ONE high-impact improvement.\\n"
        f"Agent code:\\n{parent_code}\\n"
        f"Current score: {parent_score}\\n"
        f"Return JSON: improvement_proposal, implementation_suggestion, problem_description")

    # MUTATE: spawn the agent to edit ITSELF (yield → AgentDispatcher)
    # The child receives parent_code as its program AND the diagnosis as its task.
    # The child is a coding agent that reads the code, modifies it, and
    # complete()s with the new version.
    new_code = spawn(parent_code,
        task=f"Implement this improvement to your own code:\\n{diagnosis}")

    # EVALUATE: spawn the mutated code on benchmark tasks (yield → AgentDispatcher)
    # Each child runs new_code as its program on a benchmark issue
    benchmark_tasks = select_benchmark_issues(parent_score)
    eval_results = spawn_all([
        (new_code, issue) for issue in benchmark_tasks
    ])

    # SCORE (pure computation)
    passed = sum(1 for r in eval_results if "PASS" in r)
    new_score = passed / len(eval_results)

    # ARCHIVE UPDATE (pure computation)
    if new_score >= parent_score - 0.1:  # noise leeway
        archive.append((new_code, new_score))

    print(f"Generation {generation}: archive={len(archive)}, "
          f"best={max(s for _, s in archive):.3f}, "
          f"this={new_score:.3f}")

best_code, best_score = max(archive, key=lambda x: x[1])
complete(json.dumps({
    "best_score": best_score,
    "archive_size": len(archive),
    "generations": max_generations,
    "best_code": best_code,
}))
"""


# ---------------------------------------------------------------------------
# Three types of spawn in one loop
# ---------------------------------------------------------------------------
#
# 1. MUTATION spawn:
#    new_code = spawn(parent_code, task=diagnosis)
#    The child's PROGRAM is parent_code. Its TASK is "improve yourself."
#    The child reads its own code (which IS parent_code), modifies it,
#    and complete()s with the modified version.
#    Result: a new code string.
#
# 2. EVALUATION spawn:
#    results = spawn_all([(new_code, issue) for issue in issues])
#    Each child's PROGRAM is new_code. Its TASK is a benchmark issue.
#    The child tries to solve the issue using its built-in capabilities.
#    complete()s with PASS/FAIL and a solution.
#    Result: list of pass/fail strings.
#
# 3. DIAGNOSIS ask:
#    diagnosis = ask("o1", f"Analyze:\n{parent_code}")
#    Not a spawn — just a single LLM call. o1 analyzes the code
#    and returns a structured improvement proposal.


# ---------------------------------------------------------------------------
# Yield point analysis
# ---------------------------------------------------------------------------
#
# Per generation:
#   ask("o1", diagnosis)           → 1 yield (LLMDispatcher, slow — o1)
#   spawn(mutation)                → 1 yield (AgentDispatcher, child runs ReAct loop)
#     child internally: ~10-20 yields (ask for reasoning, complete with new code)
#   spawn_all(evaluation × N)      → 1 yield (AgentDispatcher, N children parallel)
#     each child internally: ~5-15 yields (ask, edit, complete with result)
#   selection + archive update     → 0 yields
#
# Total per generation: 3 outer yields + ~50-100 inner yields across children
# For 80 generations: ~4,000-8,000 total yields
# Same state machine: INTERPRETING ⇄ WAITING_IO


# ---------------------------------------------------------------------------
# What makes this architecturally unique
# ---------------------------------------------------------------------------
#
# 1. AGENT-AS-A-STRING:
#    The "source code" is a variable. The mutation is an LLM call that
#    returns a modified string. The evaluation is spawning a child whose
#    behavior IS that string. No files, no Docker, no git.
#
# 2. THREE LEVELS OF NESTING:
#    Root (evolutionary loop) → Mutation child (editing code) → (internal yields)
#    Root → Evaluation children (running benchmarks) → (internal yields)
#    The root never sees the children's internal yields.
#
# 3. NO LLM DRIVES THE OUTER LOOP:
#    The evolutionary algorithm is CODE, not LLM reasoning.
#    Selection, archive update, termination — all deterministic.
#    The LLM is used only for diagnosis and mutation.
#
# 4. SELF-REFERENTIAL:
#    The coding agent modifies its own code string.
#    The modified version is evaluated by spawning it.
#    From the state machine's perspective: just spawn() → result.
#
# 5. PORTABLE MUTATIONS:
#    Each mutant is a self-contained code string.
#    No patch chains, no Docker images, no git history.
#    The archive IS a list of strings.


# ---------------------------------------------------------------------------
# Full trace — one generation
# ---------------------------------------------------------------------------
#
# User: "Evolve a coding agent for 80 generations"
#
# IDLE → user_message → CALLING_LLM
# CALLING_LLM → llm_response_tools → INTERPRETING
#   interpreter starts running EVOLUTIONARY_LOOP
#
# --- Generation 0 ---
#
#   select_parent → (INITIAL_AGENT_CODE, 0.20) — no yield
#
#   ask("o1", "analyze and propose improvement...")
#     → yield → WAITING_IO → LLMDispatcher (o1, slow) → io_result → INTERPRETING
#     result: {"improvement_proposal": "add retry logic when edit fails"}
#
#   spawn(INITIAL_AGENT_CODE, task="implement retry logic")
#     → yield → WAITING_IO
#     AgentDispatcher creates child-1:
#       child-1's PROGRAM = INITIAL_AGENT_CODE
#       child-1's TASK = "implement retry logic"
#       child-1 runs its ReAct loop:
#         ask("sonnet", "how should I add retry logic to my own code?")
#           → yield → io_result
#         # child reads its own code, reasons about it, produces modified version
#         new_version = parent_code.replace("def forward(", "def forward_with_retry(")
#         complete(new_version)
#     → io_result → INTERPRETING
#     new_code = "...modified agent code string..."
#
#   spawn_all([(new_code, "fix bug in django/auth.py"),
#              (new_code, "fix bug in flask/routing.py"),
#              ...])
#     → yield → WAITING_IO
#     AgentDispatcher creates eval-1, eval-2, ..., eval-N:
#       each child's PROGRAM = new_code
#       each child's TASK = a benchmark issue
#       children run in parallel, each doing ReAct:
#         ask → edit → ask → complete("PASS") or complete("FAIL")
#     → io_result → INTERPRETING
#     eval_results = ["PASS", "FAIL", "PASS", ...]
#
#   new_score = 0.25 (3/12 passed)
#   archive.append((new_code, 0.25))
#
# --- Generation 1 ---
#   select_parent → (new_code, 0.25) — highest score, 0 children
#   ... same pattern ...
#
# --- Generation 79 ---
#   ... archive has ~60 variants, best score ~0.50 ...
#   complete(best variant)
#
# INTERPRETING → interpreter_done → CALLING_LLM
# CALLING_LLM → llm_response_text → DISPLAYING → ... → IDLE
