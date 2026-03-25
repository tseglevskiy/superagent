"""Demo: state reducer running the 01-single-agent and 05b-paperqa transition tables.

Three demos:
  1. Pure reduce() — manual stepping through the single-agent trace
  2. Machine.send() — same trace, stateful
  3. Machine.run() — async with action handlers that produce follow-up events
  4. validate() — structural checks on both transition tables
"""

import asyncio
import sys
import os

# Add parent to path so we can import the snippet modules
sys.path.insert(0, os.path.dirname(__file__))

from reducer import reduce, Machine, validate, InvalidTransition

# Import the two transition tables
import importlib
agent_01 = importlib.import_module("01-single-agent")
agent_05b = importlib.import_module("05b-paperqa-pure-sm")


def demo_pure_reduce():
    """Demo 1: Pure functional reduce — the trace from 01-single-agent.py.

    User: "list all PDF files larger than 10MB"
    Expected path: IDLE → CALLING_LLM → INTERPRETING → WAITING_IO → INTERPRETING
                   → CALLING_LLM → DISPLAYING → CLEANING_UP → IDLE
    """
    print("=" * 60)
    print("DEMO 1: Pure reduce() — single agent trace")
    print("=" * 60)

    S = agent_01.S
    E = agent_01.E
    table = agent_01.transitions

    state = S.IDLE

    # Step through the trace manually
    trace = [
        (E.user_message,        "User sends message"),
        (E.llm_response_tools,  "LLM returns code with shell_run"),
        (E.interpreter_yield,   "Interpreter hits shell_run, yields"),
        (E.io_result,           "ShellDispatcher returns find results"),
        (E.interpreter_done,    "Interpreter finishes, tool results ready"),
        (E.llm_response_text,   "LLM responds with text summary"),
        (E.display_done,        "Text shown to user"),
        (E.no_extraction,       "No extraction needed"),
    ]

    for event, description in trace:
        result = reduce(state, event, table)
        print(f"  {result.src.name:15s} --[{event.name}]--> {result.dst.name:15s}  | {description}")
        state = result.dst

    assert state == S.IDLE, f"Expected IDLE, got {state.name}"
    print(f"\n  Final state: {state.name} ✓")


def demo_machine_send():
    """Demo 2: Machine.send() — same trace, stateful wrapper."""
    print("\n" + "=" * 60)
    print("DEMO 2: Machine.send() — stateful stepping")
    print("=" * 60)

    S = agent_01.S
    E = agent_01.E

    m = Machine(agent_01.transitions, initial=S.IDLE)

    # Same trace, but machine tracks state for us
    events = [
        E.user_message, E.llm_response_tools, E.interpreter_yield,
        E.io_result, E.interpreter_done, E.llm_response_text,
        E.display_done, E.no_extraction,
    ]
    for event in events:
        result = m.send(event)

    print(m.trace())
    print(f"\n  Final state: {m.state.name} ✓")

    # Test invalid transition
    try:
        m.send(E.llm_response_text)  # invalid: IDLE doesn't accept llm_response_text
    except InvalidTransition as exc:
        print(f"\n  InvalidTransition caught: {exc}")
        print(f"  Valid events in IDLE: {[e.name for e in exc.valid_events]}")


def demo_machine_run():
    """Demo 3: Machine.run() — async with action handlers.

    Action handlers simulate the agent: each handler returns the next event,
    so the machine runs the full trace autonomously.
    """
    print("\n" + "=" * 60)
    print("DEMO 3: Machine.run() — async with action handlers")
    print("=" * 60)

    S = agent_01.S
    E = agent_01.E

    # Simulate a simple scenario: user message → LLM returns text → done
    call_count = 0

    def write_user_message(ctx):
        print("    [action] write_user_message")
        return None  # no follow-up event

    def compile_and_call_llm(ctx):
        nonlocal call_count
        call_count += 1
        print(f"    [action] compile_and_call_llm (call #{call_count})")
        if call_count == 1:
            return E.llm_response_tools  # first call: LLM returns code
        return E.llm_response_text  # second call: LLM returns text

    def record_budget(ctx):
        print("    [action] record_budget")
        return None

    def write_assistant_msg(ctx):
        print("    [action] write_assistant_msg")
        return None

    def start_interpreter(ctx):
        print("    [action] start_interpreter")
        # Simulate: interpreter runs, finishes immediately (no I/O)
        return E.interpreter_done

    def write_tool_results(ctx):
        print("    [action] write_tool_results")
        return None

    def display_done_handler(ctx):
        print("    [action] display_done_handler")
        return E.display_done

    def cleanup_integrations(ctx):
        print("    [action] cleanup_integrations")
        return None

    handlers = {
        "write_user_message": write_user_message,
        "compile_and_call_llm": compile_and_call_llm,
        "record_budget": record_budget,
        "write_assistant_msg": write_assistant_msg,
        "start_interpreter": start_interpreter,
        "write_tool_results": write_tool_results,
        "cleanup_integrations": cleanup_integrations,
    }

    m = Machine(agent_01.transitions, initial=S.IDLE, handlers=handlers)

    # Manually enqueue display_done after DISPLAYING (no handler for that)
    original_dispatch = m.dispatch

    async def patched_dispatch(event):
        result = await original_dispatch(event)
        # After arriving at DISPLAYING, enqueue display_done
        if m.state == S.DISPLAYING:
            m.enqueue(E.display_done)
        # After arriving at CLEANING_UP, enqueue no_extraction
        if m.state == S.CLEANING_UP:
            m.enqueue(E.no_extraction)
        return result

    m.dispatch = patched_dispatch

    async def run():
        steps = await m.run(E.user_message)
        print(f"\n  Ran {len(steps)} steps autonomously")
        print(m.trace())
        print(f"\n  Final state: {m.state.name} ✓")

    asyncio.run(run())


def demo_validate():
    """Demo 4: Structural validation of transition tables."""
    print("\n" + "=" * 60)
    print("DEMO 4: validate() — structural checks")
    print("=" * 60)

    # Validate 01-single-agent
    print("\n  01-single-agent:")
    report = validate(
        agent_01.transitions,
        state_enum=agent_01.S,
        event_enum=agent_01.E,
        initial=agent_01.S.IDLE,
    )
    for line in str(report).split("\n"):
        print(f"    {line}")

    # Validate 05b-paperqa
    print("\n  05b-paperqa-pure-sm:")
    report = validate(
        agent_05b.transitions,
        state_enum=agent_05b.S,
        event_enum=agent_05b.E,
        initial=agent_05b.S.IDLE,
    )
    for line in str(report).split("\n"):
        print(f"    {line}")


def demo_paperqa_trace():
    """Demo 5: PaperQA2 trace — a complete research cycle."""
    print("\n" + "=" * 60)
    print("DEMO 5: PaperQA2 trace — search → gather → answer")
    print("=" * 60)

    S = agent_05b.S
    E = agent_05b.E

    m = Machine(agent_05b.transitions, initial=S.IDLE)

    # A typical PaperQA2 session:
    # 1. User asks question
    # 2. LLM decides to search papers
    # 3. Search + add papers
    # 4. LLM decides to gather evidence
    # 5. RCS pipeline: embed → search → score → filter
    # 6. LLM decides to generate answer
    # 7. Generate + citations
    # 8. LLM decides: complete (certain)
    trace = [
        E.user_question,                # → DECIDING
        E.llm_chose_paper_search,       # → SEARCHING_INDEX
        E.index_results,                # → ADDING_PAPERS
        E.papers_added,                 # → DECIDING
        E.llm_chose_gather_evidence,    # → EMBEDDING_QUESTION
        E.question_embedded,            # → SEARCHING_VECTORS
        E.chunks_retrieved,             # → SCORING_CHUNKS
        E.chunks_scored,                # → FILTERING_EVIDENCE
        E.evidence_filtered,            # → DECIDING
        E.llm_chose_gen_answer,         # → GENERATING_ANSWER
        E.answer_generated,             # → BUILDING_CITATIONS
        E.citations_resolved,           # → DECIDING
        E.llm_chose_complete_certain,   # → DISPLAYING
        E.display_done,                 # → IDLE
    ]

    for event in trace:
        m.send(event)

    print(m.trace())
    print(f"\n  Final state: {m.state.name} ✓")
    print(f"  Total steps: {len(m.history)}")


if __name__ == "__main__":
    demo_pure_reduce()
    demo_machine_send()
    demo_machine_run()
    demo_validate()
    demo_paperqa_trace()
    print("\n" + "=" * 60)
    print("All demos passed.")
    print("=" * 60)
