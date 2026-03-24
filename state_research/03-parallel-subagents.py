"""Use case 3: Agent spawns multiple children in parallel.

The agent's Python code calls spawn_all(). The AST interpreter yields ONCE.
The engine creates N child agents — each with own state machine, own JSONL.
All children run concurrently (dispatchers handle real async I/O).
When ALL children complete, the engine delivers a list of results.
The parent interpreter resumes and continues with the list.

The state machine is IDENTICAL to 01 and 02.
spawn_all() is just another yield point. One yield, one resume.
The engine and dispatchers handle all the parallelism.

Concurrency:
  - LLMDispatcher may have 5 LLM calls in flight simultaneously
    (one per child, or multiple per child if children also use ask()).
  - ShellDispatcher may have 3 shell commands running.
  - The engine never blocks — it submits to dispatchers and moves on.
  - Results come back as they complete. No waiting in line.
"""

from enum import Enum, auto
from typing import NamedTuple


# States and events: IDENTICAL to 01 and 02.
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


# Transitions: IDENTICAL to 01 and 02.
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

# The point: STILL no new states, STILL no new transitions.
# Single-agent, single-subagent, and parallel-subagents all use
# the SAME state machine. The complexity lives in the engine
# and dispatchers, not in the state machine.


# --- Example trace ---
# User: "compare rate limiting approaches across our competitor docs"
#
# IDLE → user_message → CALLING_LLM
# CALLING_LLM → llm_response_tools → INTERPRETING
#   interpreter runs:
#     docs = find("docs/competitors/*.md")
#     results = spawn_all([(f"analyze rate limiting in {d}", "none") for d in docs])
#       → yield Request(type="spawn_all", payload={tasks: [(...), (...), (...)]})
#
# INTERPRETING → interpreter_yield → WAITING_IO
#   AgentDispatcher creates child-1, child-2, child-3:
#
#   Timeline (concurrent, not sequential):
#     child-1: CALLING_LLM → INTERPRETING → yield(shell) → WAITING_IO
#     child-2: CALLING_LLM → INTERPRETING → yield(ask)   → WAITING_IO
#     child-3: CALLING_LLM → INTERPRETING → yield(shell) → WAITING_IO
#       ShellDispatcher: 2 shell requests in flight simultaneously
#       LLMDispatcher: 1 LLM request in flight
#     child-1: io_result → INTERPRETING → yield(ask)     → WAITING_IO
#       LLMDispatcher: now 2 LLM requests in flight (child-1 + child-2)
#     child-2: io_result → INTERPRETING → done
#     child-3: io_result → INTERPRETING → yield(ask)     → WAITING_IO
#       LLMDispatcher: 2 LLM requests (child-1 + child-3)
#     child-1: io_result → INTERPRETING → done
#     child-3: io_result → INTERPRETING → done
#   All 3 done → AgentDispatcher delivers [result1, result2, result3]
#
# WAITING_IO → io_result → INTERPRETING
#   parent interpreter resumes with list of 3 results, continues:
#     for doc, result in zip(docs, results):
#         print(f"## {doc}\n{result[:300]}\n")
#   interpreter done
# INTERPRETING → interpreter_done → CALLING_LLM
# CALLING_LLM → llm_response_text → DISPLAYING → ... → IDLE
