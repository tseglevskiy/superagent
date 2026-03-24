"""Use case 5: PaperQA2 ToolSelector — LLM-driven research with 6 tools.

Models PaperQA2's default mode: a single agent with a ReAct loop.
The LLM sees 6 tools and picks which to call at each step.

Key architectural point: the tools wrap EXTERNAL SUBSYSTEMS (search engine,
vector store, citation APIs). These subsystems are accessed through an
integration API. Some tool calls produce multiple yields internally.

The state machine is IDENTICAL to 01-04.
"""

from enum import Enum, auto
from typing import NamedTuple


# State machine: IDENTICAL to 01-04.
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
# Integration API — external subsystems available in the sandbox
# ---------------------------------------------------------------------------
#
# These services are initialized BEFORE the agent loop starts.
# They persist across all tool calls within a session.
# The agent accesses them through the functions below.

class PaperIndex:
    """Wraps tantivy full-text search engine. Pre-built from paper directory."""
    def search(self, query: str, top_k: int = 8, year_range: str = None) -> list:
        """YIELDS → SearchDispatcher (tantivy query)."""
        ...
    def add_papers(self, papers: list) -> None:
        """YIELDS → FileDispatcher (parse + chunk + embed each paper)."""
        ...

class VectorStore:
    """Wraps embedding index. Papers added by paper_search are auto-indexed."""
    def similarity_search(self, query_embedding: list, top_k: int = 10) -> list:
        """YIELDS → SearchDispatcher (vector similarity)."""
        ...

class EmbeddingService:
    """Wraps embedding model."""
    def embed(self, text: str) -> list:
        """YIELDS → EmbeddingDispatcher."""
        ...

class CitationService:
    """Wraps 4 external APIs: Semantic Scholar, Crossref, Unpaywall, OpenAlex."""
    def hydrate(self, doc) -> dict:
        """YIELDS → HttpDispatcher (parallel API calls)."""
        ...

# These are injected into the sandbox at session start:
#   index = PaperIndex(paper_directory)
#   vectors = VectorStore()
#   embeddings = EmbeddingService(model="text-embedding-3-small")
#   citations = CitationService()
#   session = {"question": question, "contexts": [], "cost": 0.0}


# ---------------------------------------------------------------------------
# The 6 tools — sandbox functions that use the integration API
# ---------------------------------------------------------------------------
# Annotations show which calls YIELD (→) and which are pure computation (=).

def paper_search(query: str, min_year: int = None, max_year: int = None) -> str:
    """Search for papers and add them to the working collection.

    → index.search(query, year_range)         # YIELD: tantivy search
    → index.add_papers(results)               # YIELD: parse + chunk + embed
    = format results + status string           # pure
    """
    ...

def gather_evidence(question: str) -> str:
    """RCS pipeline: retrieve chunks, score each with LLM, filter.

    → embeddings.embed(question)              # YIELD: compute query vector
    → vectors.similarity_search(embedding)    # YIELD: find top-k chunks
    → ask_all([(model, score_prompt(chunk))    # YIELD: parallel LLM calls
               for chunk in top_k_chunks])    #   (up to 10 concurrent)
    = filter score > 0, sort by score          # pure
    = format evidence count + status string    # pure

    Three yields in one function call. The state machine cycles
    INTERPRETING → WAITING_IO → INTERPRETING three times.
    """
    ...

def gen_answer() -> str:
    """Synthesize answer from accumulated evidence.

    = sort contexts by score, take top 5      # pure
    = serialize contexts with citation keys    # pure
    → ask(model, question + contexts)          # YIELD: answer LLM call
    = parse citation keys, build bibliography  # pure
    = format answer + status string            # pure
    """
    ...

def reset() -> str:
    """Clear all gathered evidence.

    = session["contexts"] = []                 # pure — no yield
    = return status string                     # pure
    """
    ...

def complete(has_successful_answer: bool) -> str:
    """Terminate the agent loop.

    = set done flag                            # pure — no yield (Category 3: terminal)
    """
    ...

def think(reflection: str) -> str:
    """Record reasoning without side effects.

    = return f"Recorded: {reflection}"         # pure — no yield
    """
    ...


# ---------------------------------------------------------------------------
# What the ToolSelector agent's code looks like across multiple turns
# ---------------------------------------------------------------------------
#
# Each LLM turn produces ONE tool call. The ReAct loop is:
#   CALLING_LLM → INTERPRETING → CALLING_LLM → INTERPRETING → ...
#
# Turn 1:  print(paper_search("quantum error correction 2025"))
#            → 2 yields (search + add_papers)
# Turn 2:  print(paper_search("surface code threshold improvements"))
#            → 2 yields
# Turn 3:  print(gather_evidence("what threshold improvements were achieved?"))
#            → 3 yields (embed + vector_search + ask_all)
# Turn 4:  print(paper_search("fault tolerant quantum computing recent"))
#            → 2 yields
# Turn 5:  print(gather_evidence("what are the main fault tolerance approaches?"))
#            → 3 yields
# Turn 6:  print(gen_answer())
#            → 1 yield (answer LLM)
# Turn 7:  complete(has_successful_answer=True)
#            → 0 yields (terminal)
#
# Total: 7 LLM turns × 1 tool each = 7 tool calls
# Total yields: 2+2+3+2+3+1+0 = 13 yield cycles through the state machine
# Plus 7 CALLING_LLM yields for the agent's own reasoning = 20 total


# ---------------------------------------------------------------------------
# Status string as coverage assessment
# ---------------------------------------------------------------------------
#
# Every tool appends to its return value:
#   "Status: Paper Count=12 | Relevant Papers=5 | Current Evidence=8 | Current Cost=$0.12"
#
# Computed from session state (pure, no yield):
#   paper_count = len(index.papers)
#   relevant = len([c for c in session["contexts"] if c.score > 0])
#   evidence = len(session["contexts"])
#   cost = session["cost"]
#
# The LLM reads this in every tool response and adjusts strategy.
# No special state machine support — it's just text in the output.


# ---------------------------------------------------------------------------
# Failover on truncation
# ---------------------------------------------------------------------------
#
# If max_rounds_hit and gen_answer was never called:
#   force gen_answer() → 1 more yield (answer LLM)
# Then display result + complete.
