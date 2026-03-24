"""Use case 1: Single agent — user talks, agent reasons and acts.

The simplest use case. One agent, one user. The agent receives messages,
calls an LLM, executes Python code via an AST interpreter, and responds.

Architecture:
  - AST interpreter is a coroutine: runs code, yields on any I/O.
  - All I/O goes through typed dispatchers (LLM, shell, file, http).
  - Interpreter never does I/O directly — it yields a Request.
  - Engine routes the Request to a dispatcher, delivers the result back.
  - Between turns: extraction and consolidation run as background phases.

States:
  IDLE → CALLING_LLM → INTERPRETING ⇄ WAITING_IO → CALLING_LLM → ... → IDLE
"""

from enum import Enum, auto
from typing import NamedTuple


class S(Enum):
    IDLE = auto()               # waiting for user input
    CALLING_LLM = auto()        # LLM streaming response
    INTERPRETING = auto()       # AST interpreter running code
    WAITING_IO = auto()         # interpreter yielded, dispatcher working
    DISPLAYING = auto()         # final text shown to user
    CLEANING_UP = auto()        # post-turn: check extraction threshold
    EXTRACTING = auto()         # knowledge extraction pipeline
    CONSOLIDATING = auto()      # knowledge consolidation


class E(Enum):
    user_message = auto()
    llm_response_tools = auto()
    llm_response_text = auto()
    llm_error = auto()
    interpreter_done = auto()
    interpreter_yield = auto()  # interpreter needs external I/O
    interpreter_error = auto()
    io_result = auto()          # dispatcher delivered a result
    io_error = auto()           # dispatcher delivered an error
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
# Yield function reference (see DESIGN.md for full taxonomy)
# ---------------------------------------------------------------------------
#
# Category 2 — I/O yield (yield and resume):
#   ask(model, prompt)       → LLMDispatcher    → resume with text
#   ask_all(tasks)           → LLMDispatcher(N)  → resume with list
#   spawn(task, inherit)     → AgentDispatcher   → resume with child result
#   spawn_all(tasks)         → AgentDispatcher(N) → resume with list
#   shell_run(command)       → ShellDispatcher   → resume with output
#   read(path)               → FileDispatcher    → resume with File
#   write(path, content)     → FileDispatcher    → resume with confirmation
#   edit(path, old, new)     → FileDispatcher    → resume with confirmation
#   web_search(query)        → HttpDispatcher    → resume with results
#   ask_user(prompt)         → HumanDispatcher   → resume with user input
#
# Category 3 — Terminal yield (yield and stop):
#   complete(result)         → TERMINAL: delivers result, never resumes
#     Root agent interactive: show result, wait for next task
#     Root agent autonomous: print and exit
#     Subagent: deliver to parent as spawn() return value
#
# All Category 2 yields produce the same state transition:
#   INTERPRETING → interpreter_yield → WAITING_IO → io_result → INTERPRETING
#
# complete() produces:
#   INTERPRETING → interpreter_done → CALLING_LLM → llm_response_text → DISPLAYING → IDLE
#   (The engine checks the done flag and skips the actual LLM call.)


# --- Example trace ---
# User: "list all PDF files larger than 10MB"
#
# IDLE → user_message → CALLING_LLM
# CALLING_LLM → llm_response_tools → INTERPRETING
#   interpreter runs: `results = shell_run("find . -name '*.pdf' -size +10M")`
#     → yield Request(type="shell", payload={command: "find ..."})
# INTERPRETING → interpreter_yield → WAITING_IO
#   ShellDispatcher executes, delivers result
# WAITING_IO → io_result → INTERPRETING
#   interpreter resumes, runs: `print(results)`
#   → interpreter done
# INTERPRETING → interpreter_done → CALLING_LLM
# CALLING_LLM → llm_response_text → DISPLAYING → display_done → CLEANING_UP
# CLEANING_UP → no_extraction → IDLE
