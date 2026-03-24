"""Use case 6: PaperQA2 Fake Agent — deterministic research pipeline.

Models PaperQA2's "fake" mode: NO LLM drives tool selection.
The sequence is hardcoded: generate queries → search × N → gather → answer → complete.
The LLM is used only for the work INSIDE each tool (RCS summarization,
answer generation), never for deciding WHAT to do next.

This is a PIPELINE, not a ReAct loop.
The difference from 05: in 05, the LLM decides each turn which tool to call.
Here, the script decides — the LLM only does the heavy lifting within each step.

In our architecture, this means the root agent's LLM is called ONCE to generate
the code, and that code is a fixed script that calls tools in sequence.
Or alternatively: the code is not LLM-generated at all — it's a built-in
recipe/template that the engine runs directly.

The state machine is STILL identical to 01-05.
A pipeline is just an agent whose code happens to be deterministic.

Integration API: same as 05 (PaperIndex, VectorStore, EmbeddingService,
CitationService injected into sandbox). See 05 for yield annotations per tool.
"""

from enum import Enum, auto
from typing import NamedTuple


# State machine: IDENTICAL to 01-05.
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
# The fixed pipeline script
# ---------------------------------------------------------------------------
#
# This is what runs in the interpreter. It's a deterministic sequence,
# not LLM-generated. The engine can inject this as a "recipe."
#
# In PaperQA2, the fake agent bypasses the ToolSelector entirely.
# In our architecture, this is an agent whose "code" is predetermined:

PIPELINE_SCRIPT = """
# Step 1: Generate 3 search queries (one LLM call for query expansion)
queries = ask("haiku",
    f"Generate 3 keyword search queries for: {question}\\n"
    f"Mix broad and narrow. One per line. Temperature=1.0 for diversity."
).strip().split("\\n")

# Step 2: Search for each query
for q in queries[:3]:
    print(paper_search(q.strip()))

# Step 3: Gather evidence for the original question
print(gather_evidence(question))

# Step 4: Generate the answer
print(gen_answer())

# Step 5: Evaluate and complete (one LLM call to judge answer quality)
judgment = ask("haiku",
    f"Does this answer fully address the question?\\n"
    f"Question: {question}\\n"
    f"Respond with only 'yes' or 'no'.")
complete(has_successful_answer="yes" in judgment.lower())
"""

# The engine can run this in two ways:
#
# Option A: "recipe mode" — the engine injects PIPELINE_SCRIPT directly
# into the interpreter when the user triggers a "research" command.
# No CALLING_LLM step needed for the outer agent — go straight to INTERPRETING.
# The LLM calls happen only INSIDE the tools (ask, gather_evidence, gen_answer).
#
# Option B: "prompt mode" — the system prompt tells the LLM to always
# generate this exact pipeline. The LLM's first turn produces approximately
# this script. Then the engine runs it normally.
#
# Option A is more efficient (skips one LLM call) and more deterministic.
# Option B is more flexible (the LLM can deviate if the user's question
# warrants a different approach).


# ---------------------------------------------------------------------------
# Trace — the full pipeline execution
# ---------------------------------------------------------------------------
#
# User: "What are recent advances in quantum error correction?"
#
# IDLE → user_message → CALLING_LLM
#   (Option A: skip CALLING_LLM, inject PIPELINE_SCRIPT directly)
#   (Option B: LLM generates the pipeline script)
# CALLING_LLM → llm_response_tools → INTERPRETING
#
# Interpreter runs PIPELINE_SCRIPT:
#
#   queries = ask("haiku", "Generate 3 keyword searches for: ...")
#     → yield Request(type="llm") → WAITING_IO
#     LLMDispatcher calls haiku → "quantum error correction advances\n..."
#     → io_result → INTERPRETING
#
#   queries = ["quantum error correction advances",
#              "surface code threshold 2025",
#              "fault tolerant quantum computing"]
#
#   paper_search("quantum error correction advances")
#     → yield Request(type="search") → WAITING_IO
#     SearchDispatcher queries tantivy → 8 papers found
#     → io_result → INTERPRETING
#     (prints results + status)
#
#   paper_search("surface code threshold 2025")
#     → yield → WAITING_IO → io_result → INTERPRETING
#
#   paper_search("fault tolerant quantum computing")
#     → yield → WAITING_IO → io_result → INTERPRETING
#
#   gather_evidence("What are recent advances in quantum error correction?")
#     → yield Request(type="embedding") → WAITING_IO → io_result
#     → yield Request(type="vector_search") → WAITING_IO → io_result
#     → yield Request(type="ask_all", 10 chunk summaries)
#       LLMDispatcher runs 4 concurrently → all 10 scored
#     → io_result → INTERPRETING
#     (prints evidence count + top summaries + status)
#
#   gen_answer()
#     → yield Request(type="llm") → WAITING_IO
#     LLMDispatcher calls answer model with contexts + question
#     → io_result → INTERPRETING
#     (prints answer + status)
#
#   judgment = ask("haiku", "Does this answer fully address...?")
#     → yield → WAITING_IO → io_result → INTERPRETING
#
#   complete(has_successful_answer=True)
#     (no yield — sets done flag)
#
# INTERPRETING → interpreter_done → CALLING_LLM
# CALLING_LLM → llm_response_text → DISPLAYING → ... → IDLE
#
# Total LLM calls:
#   1 (query generation) + 10 (RCS chunk scoring) + 1 (gen_answer) + 1 (judgment) = 13
#   vs ToolSelector mode: add ~7 turns of tool selection = ~20 total
#
# The pipeline is cheaper because it skips the tool-selection LLM calls.
# PaperQA2 reports the real agent averages 1.26 searches per question,
# so the pipeline's fixed 3 searches is close to optimal.


# ---------------------------------------------------------------------------
# Key difference from 05 (ToolSelector)
# ---------------------------------------------------------------------------
#
# 05 (ToolSelector):
#   - LLM decides each turn: "which tool should I call?"
#   - Iterative: can adapt based on results
#   - More expensive: ~7 extra LLM calls for tool selection
#   - Better for complex questions requiring adaptive strategy
#
# 06 (Pipeline):
#   - Code decides: fixed sequence, no tool-selection LLM
#   - Deterministic: same question always produces same execution flow
#   - Cheaper: only LLM calls are inside tools
#   - Better for batch processing, benchmarking, simple questions
#
# Both use the same state machine. The difference is what code
# the interpreter runs — LLM-generated vs predetermined.
