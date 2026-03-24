"""Use case 7: Moatless MCTS — tree search over code states.

The most alien architecture in the study. Not a ReAct loop.
Not a pipeline. Not a supervisor. A Monte Carlo Tree Search
where each node is a complete code snapshot with an action,
an observation, and a reward score.

The question: does our state machine still fit?

Answer: YES. The MCTS controller is just CODE that the root
interpreter runs. select/expand/backpropagate are pure computation.
simulate involves ask() and edit() — standard yield points.
The tree lives in interpreter locals. The state machine is unchanged.

Key mapping:
  MCTS select   → pure computation (UCT scoring on in-memory tree)
  MCTS expand   → pure computation (clone node, clone FileContext)
  MCTS simulate → ask() for action generation, edit()/shell_run() for execution,
                   ask() for value function scoring — multiple yields
  MCTS backprop → pure computation (walk up tree, update scores)
  Discriminator → ask_all() for multi-agent debate — one yield

The tree data structure (nodes, FileContext snapshots, rewards)
lives entirely in the interpreter's local variables.
It persists between yields (interpreter state is preserved).
On process restart it's lost — but the tree can be persisted to disk
after each iteration (Moatless already does this).
"""

from enum import Enum, auto
from typing import NamedTuple


# State machine: IDENTICAL to 01-06.
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
# Data model (lives in interpreter locals, not in the state machine)
# ---------------------------------------------------------------------------

class Node:
    """Mirrors Moatless Node. In-memory, managed by interpreter code."""
    node_id: int
    parent: 'Node | None'
    children: list['Node']
    action: str             # what was done
    observation: str        # what happened
    reward: int             # -100 to 100
    visits: int
    value: int              # cumulative reward for backprop
    file_context: dict      # snapshot of code state (cloned per node)
    is_terminal: bool
    is_duplicate: bool
    feedback_data: str | None


# ---------------------------------------------------------------------------
# What the root agent's LLM-generated code looks like
# ---------------------------------------------------------------------------
#
# The LLM receives: "Fix bug X in repository Y. Use tree search to explore
# multiple approaches." The LLM generates an MCTS controller as Python code:

MCTS_CONTROLLER = """
import copy

# --- Node helpers (pure computation, no yields) ---

def create_root(task):
    return {
        "id": 0, "parent": None, "children": [],
        "action": None, "observation": task, "reward": 0,
        "visits": 0, "value": 0, "terminal": False,
        "duplicate": False, "file_context": {},
        "feedback": None, "messages": [task],
    }

def uct_score(node, parent_visits):
    if node["visits"] == 0:
        return float("inf")
    exploit = node["value"] / node["visits"]
    explore = 1.4 * (log(parent_visits) / node["visits"]) ** 0.5
    return exploit + explore

def select(root):
    # Find the best expandable node via UCT
    best, best_score = None, -float("inf")
    for node in get_expandable(root):
        score = uct_score(node, root["visits"] or 1)
        if score > best_score:
            best, best_score = node, score
    return best

def backpropagate(node):
    reward = node["reward"]
    while node is not None:
        node["visits"] += 1
        node["value"] += reward
        node = node["parent"]

def is_finished(root, max_iterations, max_cost):
    finished = [n for n in all_nodes(root) if n["terminal"]]
    if len(finished) >= 3:
        return True
    if count_nodes(root) >= max_iterations:
        return True
    # could also check cost budget here
    return False

# --- The MCTS loop (yields on LLM calls and action execution) ---

root = create_root(task)
node_counter = 0

while not is_finished(root, max_iterations=30, max_cost=5.0):
    # SELECT (pure computation)
    node = select(root)
    if node is None:
        break

    # EXPAND (pure computation — clone parent state)
    node_counter += 1
    child = {
        "id": node_counter,
        "parent": node,
        "children": [],
        "file_context": copy.deepcopy(node["file_context"]),
        "visits": 0, "value": 0,
        "terminal": False, "duplicate": False,
        "feedback": None,
    }
    node["children"].append(child)

    # FEEDBACK (yield — ask LLM if this is a re-expansion)
    if len(node["children"]) >= 2:
        sibling_summary = summarize_siblings(node["children"][:-1])
        child["feedback"] = ask("haiku",
            f"Previous attempts from this state:\\n{sibling_summary}\\n"
            f"Suggest a DIFFERENT approach. Be specific.")

    # SIMULATE — the action generation (yield — ask LLM)
    history = build_trajectory_messages(child)
    if child["feedback"]:
        history += f"\\nFeedback: {child['feedback']}"
    action_response = ask("sonnet",
        f"Given this code state and history, what is the best next action?\\n"
        f"{history}\\n"
        f"Available actions: FindClass, FindFunction, SemanticSearch, "
        f"StringReplace, ViewCode, RunTests, Finish")

    # SIMULATE — action execution (yield — depends on action type)
    action_name, action_args = parse_action(action_response)
    if action_name == "StringReplace":
        observation = edit(action_args["path"],
                          action_args["old_str"],
                          action_args["new_str"])
    elif action_name == "SemanticSearch":
        observation = web_search(action_args["query"])  # or custom search
    elif action_name == "RunTests":
        observation = shell_run(f"pytest {action_args['test_file']}")
    elif action_name == "ViewCode":
        observation = read(action_args["path"])
    elif action_name == "Finish":
        child["terminal"] = True
        observation = "Finished: " + action_args.get("reason", "")
    else:
        observation = f"Unknown action: {action_name}"

    child["action"] = action_response
    child["observation"] = str(observation)

    # EVALUATE — value function (yield — ask LLM)
    reward_str = ask("haiku",
        f"Score this action -100 to 100.\\n"
        f"Action: {action_name}\\n"
        f"Observation: {str(observation)[:2000]}\\n"
        f"Respond with just the number.")
    child["reward"] = int(reward_str.strip())

    # BACKPROPAGATE (pure computation)
    backpropagate(child)

# --- DISCRIMINATE — select best trajectory ---
finished_nodes = [n for n in all_nodes(root) if n["terminal"]]
if len(finished_nodes) == 0:
    complete("No solution found")
elif len(finished_nodes) == 1:
    complete(get_trajectory_result(finished_nodes[0]))
else:
    # Multi-agent debate (yield — ask_all with N judges)
    candidates = [get_trajectory_patch(n) for n in finished_nodes]
    judgments = ask_all([
        ("haiku", f"Compare these solutions and pick the best:\\n{candidates}")
        for _ in range(5)  # 5 judges
    ])
    best_idx = vote(judgments)
    complete(get_trajectory_result(finished_nodes[best_idx]))
"""


# ---------------------------------------------------------------------------
# Yield point analysis for one MCTS iteration
# ---------------------------------------------------------------------------
#
# One iteration of the MCTS loop:
#   select()      → 0 yields (pure computation)
#   expand()      → 0 yields (pure computation)
#   feedback      → 0 or 1 yield (ask() if re-expansion)
#   simulate-gen  → 1 yield (ask() for action generation)
#   simulate-exec → 1 yield (edit/shell_run/read depending on action)
#   evaluate      → 1 yield (ask() for value function)
#   backpropagate → 0 yields (pure computation)
#
# Total: 2-4 yields per MCTS iteration.
# For 30 iterations: 60-120 yields.
# Plus discrimination at the end: 1 yield (ask_all with 5 judges).
#
# Each yield: INTERPRETING → WAITING_IO → INTERPRETING
# The state machine processes 60-120 yield cycles for one MCTS run.
# No special states needed. Same machine as a simple "list files" command.


# ---------------------------------------------------------------------------
# Full trace — first 3 MCTS iterations
# ---------------------------------------------------------------------------
#
# User: "Fix the authentication bypass in auth.py"
#
# IDLE → user_message → CALLING_LLM
# CALLING_LLM → llm_response_tools → INTERPRETING
#   interpreter starts running MCTS_CONTROLLER
#
# --- Iteration 1 (first path — no feedback, no siblings) ---
#   select: root (only node) — no yield
#   expand: create child-0, clone state — no yield
#   simulate-gen: ask("sonnet", "what action?")
#     → yield → WAITING_IO → LLMDispatcher → io_result → INTERPRETING
#     result: "SemanticSearch: find authentication validation code"
#   simulate-exec: web_search("authentication validation auth.py")
#     → yield → WAITING_IO → HttpDispatcher → io_result → INTERPRETING
#     result: "Found: auth.py lines 45-78, validate_token function"
#   evaluate: ask("haiku", "score this action")
#     → yield → WAITING_IO → LLMDispatcher → io_result → INTERPRETING
#     result: "65" (found relevant code)
#   backpropagate: child-0.reward=65, root.visits=1 — no yield
#
# --- Iteration 2 (expand from child-0, go deeper) ---
#   select: child-0 (only expandable) — no yield
#   expand: create child-1, clone child-0's state — no yield
#   simulate-gen: ask("sonnet", "what action? history: searched, found validate_token")
#     → yield → WAITING_IO → io_result → INTERPRETING
#     result: "StringReplace in auth.py: fix the token validation"
#   simulate-exec: edit("auth.py", old_code, new_code)
#     → yield → WAITING_IO → FileDispatcher → io_result → INTERPRETING
#   evaluate: ask("haiku", "score: edited auth.py")
#     → yield → WAITING_IO → io_result → INTERPRETING
#     result: "40" (edit looks reasonable but no tests run)
#   backpropagate: child-1.reward=40 — no yield
#
# --- Iteration 3 (re-expand root — try different approach) ---
#   select: root (UCT says: try branching from root) — no yield
#   expand: create child-2, clone ROOT's state (not child-0's!) — no yield
#   feedback: len(root.children)==2, so generate feedback
#     ask("haiku", "Previous: searched for auth validation. Suggest DIFFERENT approach")
#     → yield → WAITING_IO → io_result → INTERPRETING
#     result: "Try looking at the session management code instead"
#   simulate-gen: ask("sonnet", "what action? Feedback: try session management")
#     → yield → WAITING_IO → io_result → INTERPRETING
#     result: "FindFunction: check_session"
#   simulate-exec: web_search("check_session function")
#     → yield → WAITING_IO → io_result → INTERPRETING
#   evaluate: ask("haiku", "score: found check_session")
#     → yield → WAITING_IO → io_result → INTERPRETING
#     result: "55" (alternative angle, promising)
#   backpropagate: child-2.reward=55 — no yield
#
# ... iterations 4-30 continue, branching and deepening ...
# ... some branches reach Finish, others dead-end ...
#
# --- Discrimination ---
#   3 finished nodes found
#   ask_all([("haiku", "compare patches") x 5])
#     → yield → WAITING_IO → LLMDispatcher (5 concurrent) → io_result → INTERPRETING
#   vote: solution from child-1's subtree wins
#   complete(winning_patch)
#     → TerminalException
#
# INTERPRETING → interpreter_done → CALLING_LLM
# CALLING_LLM → llm_response_text → DISPLAYING → ... → IDLE


# ---------------------------------------------------------------------------
# Why it fits without changes
# ---------------------------------------------------------------------------
#
# The MCTS loop is just CODE. The tree is a data structure in locals.
# UCT scoring, node selection, expansion, backpropagation — all pure
# computation. No yields needed. The interpreter handles them instantly.
#
# The only yields are:
#   - ask() for action generation (LLM decides what to do)
#   - edit()/shell_run()/read() for action execution (modify code, run tests)
#   - ask() for value function (LLM scores the action)
#   - ask() for feedback (LLM guides re-expansion)
#   - ask_all() for discrimination (multi-agent debate)
#
# All standard Category 2 yields. Same INTERPRETING ⇄ WAITING_IO cycle.
# The state machine doesn't know it's running MCTS. It just sees yields.
#
# The tree search "intelligence" lives in the ALGORITHM (UCT, backprop,
# feedback injection), not in the state machine. The state machine provides
# the EXECUTION SUBSTRATE (yield/resume for I/O), and the algorithm runs
# on top of it.
#
# This is the strongest validation of the architecture: an algorithm
# that has NOTHING to do with ReAct loops — borrowed from game-playing AI —
# runs on the same 8-state, 18-transition machine as a simple chatbot.
