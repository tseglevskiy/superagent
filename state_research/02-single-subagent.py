"""Use case 2: Agent spawns a child and waits for its result.

The agent's Python code calls spawn(). The AST interpreter yields.
The engine creates a child agent instance — same state machine, own JSONL.
The child runs to completion. The engine delivers the result back.
The parent interpreter resumes and continues with the result.

The state machine is IDENTICAL to 01-single-agent.py.
spawn() is just another yield point — like shell_run() or ask().
The AgentDispatcher handles the child lifecycle.

The child is a full agent: own LLM calls, own tool execution,
own interpreter yields. It can call read(), shell_run(), ask() — anything.
The child terminates via complete(result) — this is how it delivers
its result to the parent. Without complete(), the child would enter
IDLE and wait for user input that will never come.
Recursive: the child can spawn() too, creating a grandchild.
"""

from enum import Enum, auto
from typing import NamedTuple


# States and events: IDENTICAL to 01.
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


# Transitions: IDENTICAL to 01.
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

# The point: NO new states, NO new transitions.
# The child is invisible to the parent's state machine.
# It's just a longer WAITING_IO.


# --- Example trace ---
# User: "research quantum error correction in depth"
#
# IDLE → user_message → CALLING_LLM
# CALLING_LLM → llm_response_tools → INTERPRETING
#   interpreter runs:
#     result = spawn("research quantum error correction 2025")
#       → yield Request(type="spawn", payload={task: "...", inherit: "summary"})
#
# INTERPRETING → interpreter_yield → WAITING_IO
#   AgentDispatcher creates child agent "child-1":
#     child-1 IDLE → user_message → CALLING_LLM
#     child-1 CALLING_LLM → llm_response_tools → INTERPRETING
#       child interpreter: `papers = shell_run("find . -name '*.md' ...")`
#         → yield Request(type="shell", ...)
#     child-1 INTERPRETING → interpreter_yield → WAITING_IO
#       ShellDispatcher runs, delivers result
#     child-1 WAITING_IO → io_result → INTERPRETING
#       child interpreter: `summary = ask("haiku", f"summarize: {papers}")`
#         → yield Request(type="llm", ...)
#     child-1 INTERPRETING → interpreter_yield → WAITING_IO
#       LLMDispatcher calls haiku, delivers result
#     child-1 WAITING_IO → io_result → INTERPRETING
#       child interpreter: `complete(summary)`
#         → TerminalException("Here is a summary of...")
#         → child-1 is DONE, result delivered to parent
#   AgentDispatcher delivers child-1 result to parent
#
# WAITING_IO → io_result → INTERPRETING
#   parent interpreter resumes with child result, continues:
#     print(f"Research findings:\n{result[:1000]}")
#   interpreter done
# INTERPRETING → interpreter_done → CALLING_LLM
# CALLING_LLM → llm_response_text → DISPLAYING → ... → IDLE
