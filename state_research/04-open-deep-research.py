"""Use case 4: Research agent — supervisor + parallel researchers.

Models the Open Deep Research 3-tier architecture using our state machine.
One parent agent (supervisor) spawns N researcher children in parallel,
assesses coverage, spawns more for gaps, compresses and writes final report.

The state machine is IDENTICAL to 01-03.
The supervisor is just an agent whose LLM-generated code calls spawn_all().
Each researcher is a child agent whose code calls web_search() and ask().

Three tiers map to our architecture:
  Tier 1 (main pipeline): the supervisor agent's code flow
  Tier 2 (supervisor loop): the supervisor's LLM reasoning + spawn_all() yields
  Tier 3 (researcher loop): each child agent's LLM reasoning + web_search() yields

Context isolation is natural: each child has its own state machine, own JSONL,
own interpreter. The supervisor only sees compressed results from spawn_all().
"""

from enum import Enum, auto
from typing import NamedTuple


# State machine: IDENTICAL to 01-03.
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
# What the SUPERVISOR agent's LLM-generated code looks like
# ---------------------------------------------------------------------------
#
# The supervisor is the root agent. The user asks a question.
# The supervisor's LLM writes code like this:
#
#   # Round 1: decompose and research in parallel
#   brief = "quantum error correction in 2025"
#   sub_topics = ask("haiku", f"Decompose into 3 research sub-topics: {brief}")
#   topics = sub_topics.strip().split("\n")
#
#   results = spawn_all([(t, "none") for t in topics])
#
#   # Assess coverage
#   all_findings = "\n---\n".join(results)
#   gaps = ask("haiku", f"Given these findings:\n{all_findings}\n\nWhat gaps remain?")
#
#   if "no gaps" not in gaps.lower():
#       # Round 2: fill gaps
#       gap_topics = gaps.strip().split("\n")
#       more = spawn_all([(g, "none") for g in gap_topics])
#       all_findings += "\n---\n" + "\n---\n".join(more)
#
#   # Final report — complete() signals task done
#   report = ask("sonnet", f"Write a research report:\n{all_findings}")
#   complete(report)


# ---------------------------------------------------------------------------
# What each RESEARCHER child agent's LLM-generated code looks like
# ---------------------------------------------------------------------------
#
# Each researcher is a child agent. It gets the sub-topic as its task.
# The researcher's LLM writes code like this:
#
#   # Broad search first
#   results = web_search(f"quantum error correction {topic} 2025")
#   relevant = ask("haiku", f"Which of these are relevant?\n{results}")
#
#   # Targeted follow-up
#   details = web_search(f"{topic} surface codes threshold improvements 2025")
#
#   # Compress findings and deliver to parent
#   summary = ask("haiku",
#       f"Compress these findings, preserve ALL sources:\n{results}\n{details}")
#   complete(summary)


# ---------------------------------------------------------------------------
# Full trace
# ---------------------------------------------------------------------------
#
# User: "Research quantum error correction advances in 2025"
#
# === SUPERVISOR (root agent) ===
# IDLE → user_message → CALLING_LLM
#   supervisor LLM generates code with ask() + spawn_all() + ask()
# CALLING_LLM → llm_response_tools → INTERPRETING
#   interpreter: sub_topics = ask("haiku", "Decompose...")
#     → yield Request(type="llm") → WAITING_IO
#     LLMDispatcher calls haiku → "1. Surface codes\n2. ..."
#     → io_result → INTERPRETING
#   interpreter: topics = ["Surface codes", "Logical qubits", "Fault tolerance"]
#   interpreter: results = spawn_all([(t, "none") for t in topics])
#     → yield Request(type="spawn_all", tasks=[...]) → WAITING_IO
#
#     === RESEARCHER child-1 ("Surface codes") ===
#     IDLE → user_message → CALLING_LLM
#       researcher LLM generates code with web_search() + ask()
#     CALLING_LLM → llm_response_tools → INTERPRETING
#       interpreter: results = web_search("surface codes 2025")
#         → yield Request(type="http") → WAITING_IO
#         HttpDispatcher calls SearXNG → search results
#         → io_result → INTERPRETING
#       interpreter: details = web_search("surface codes threshold")
#         → yield Request(type="http") → WAITING_IO
#         HttpDispatcher calls SearXNG → more results
#         → io_result → INTERPRETING
#       interpreter: summary = ask("haiku", "Compress findings...")
#         → yield Request(type="llm") → WAITING_IO
#         LLMDispatcher calls haiku → compressed summary
#         → io_result → INTERPRETING
#       interpreter: complete(summary)
#         → TerminalException("Surface codes summary...")
#         → child-1 is DONE, result delivered to parent
#
#     === RESEARCHER child-2 and child-3 run CONCURRENTLY ===
#     (same pattern, different topics, different search queries)
#     LLMDispatcher may have 3 haiku calls in flight simultaneously
#     HttpDispatcher may have 2 web searches in flight simultaneously
#
#   All 3 children done → AgentDispatcher delivers results list
#   → io_result → INTERPRETING
#
#   interpreter: all_findings = "\n---\n".join(results)
#   interpreter: gaps = ask("haiku", "What gaps remain?")
#     → yield Request(type="llm") → WAITING_IO
#     → io_result → INTERPRETING
#   interpreter: "implementation challenges" identified as gap
#   interpreter: more = spawn_all([("implementation challenges", "none")])
#     → yield Request(type="spawn_all") → WAITING_IO
#
#     === RESEARCHER child-4 ("implementation challenges") ===
#     (same pattern as above)
#     → result: "Implementation challenges summary..."
#
#   → io_result → INTERPRETING
#   interpreter: report = ask("sonnet", "Write research report...")
#     → yield Request(type="llm") → WAITING_IO
#     LLMDispatcher calls sonnet (expensive model for final synthesis)
#     → io_result → INTERPRETING
#   interpreter: complete(report)
#     → TerminalException with the report
#     → root agent signals task completion to UI
#
# → DISPLAYING (with completion marker) → ... → IDLE


# ---------------------------------------------------------------------------
# How this maps to Open Deep Research's 3 tiers
# ---------------------------------------------------------------------------
#
# ODR Tier 1 (Main pipeline):
#   clarify → brief → supervisor → report
#   In our model: the supervisor agent's code flow.
#   Clarification = ask("haiku", "need clarification?")
#   Brief creation = ask("haiku", "create research brief from question")
#   Report = ask("sonnet", "write final report from findings")
#   All are yield points in the same interpreter.
#
# ODR Tier 2 (Supervisor loop):
#   think → delegate → reflect → repeat
#   In our model: the supervisor's LLM reasons, its code calls
#   spawn_all() (delegate), then ask() (reflect on coverage),
#   then conditionally spawn_all() again (more researchers for gaps).
#   The loop is in the CODE, not in the state machine.
#
# ODR Tier 3 (Researcher loop):
#   search → think → search → compress
#   In our model: each child agent's LLM generates code that calls
#   web_search() (search), ask() (think/compress).
#   The ReAct loop is in the child agent's state machine:
#   CALLING_LLM → INTERPRETING → WAITING_IO → INTERPRETING → ... → IDLE
#
# Context isolation:
#   Each child has own JSONL, own interpreter, own state.
#   spawn_all() returns only the complete() result from each child.
#   The supervisor never sees raw search results — only compressed summaries.
#   This is exactly ODR's ResearcherOutputState boundary.
