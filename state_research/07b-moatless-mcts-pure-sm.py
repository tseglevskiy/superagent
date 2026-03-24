"""Use case 7b: Moatless MCTS — PURE state machine approach.

Contrast with 07: there the MCTS algorithm was CODE inside the interpreter.
Here the MCTS phases ARE states in the state machine. Every phase transition
is an explicit edge in the transition table. No interpreter, no yields.

Key difference: every I/O-needing phase has its own WAITING state.
The state machine always knows where to resume because the WAITING state
encodes the return address.

States: 19 (vs 8 in 01-07)
Transitions: 31

The MCTS loop is: SELECT → EXPAND → SIMULATE → EVALUATE → BACKPROP → SELECT
Each phase that needs I/O splits into: PHASE → dispatch → PHASE_WAITING → result → NEXT_PHASE
"""

from enum import Enum, auto
from typing import NamedTuple


class S(Enum):
    # --- Outer agent (same as 01) ---
    IDLE = auto()                       # waiting for user/task input
    CALLING_LLM = auto()               # initial LLM call to decide approach
    DISPLAYING = auto()                 # showing final result
    CLEANING_UP = auto()
    EXTRACTING = auto()
    CONSOLIDATING = auto()

    # --- MCTS core loop ---
    MCTS_SELECT = auto()                # pick best expandable node via UCT (pure computation)
    MCTS_EXPAND = auto()                # create child node, clone FileContext (pure)
    MCTS_FEEDBACK = auto()              # generate feedback for re-expansion (needs LLM)
    MCTS_FEEDBACK_WAITING = auto()      # waiting for feedback LLM response

    MCTS_ACTION_GEN = auto()            # ask LLM: what action to take? (needs LLM)
    MCTS_ACTION_GEN_WAITING = auto()    # waiting for action generation LLM response

    MCTS_ACTION_EXEC = auto()           # execute the action (needs file/shell/search)
    MCTS_ACTION_EXEC_WAITING = auto()   # waiting for action execution result

    MCTS_EVALUATE = auto()              # ask LLM: score this action (needs LLM)
    MCTS_EVALUATE_WAITING = auto()      # waiting for value function LLM response

    MCTS_BACKPROP = auto()              # propagate reward up tree (pure)
    MCTS_DISCRIMINATE = auto()          # select best trajectory (needs LLM for debate)
    MCTS_DISCRIMINATE_WAITING = auto()  # waiting for discriminator LLM response


class E(Enum):
    # --- Outer ---
    user_message = auto()
    llm_decided_mcts = auto()       # LLM decided to use tree search
    llm_response_text = auto()      # LLM responded with text (no MCTS)
    llm_error = auto()

    # --- MCTS loop control ---
    node_selected = auto()          # UCT picked a node
    no_expandable_nodes = auto()    # tree exhausted
    expanded_no_feedback = auto()   # first child, no feedback needed
    expanded_needs_feedback = auto() # 2nd+ child, needs sibling analysis
    feedback_ready = auto()         # feedback LLM responded

    action_generated = auto()       # LLM chose an action
    action_is_duplicate = auto()    # same as a sibling — skip execution
    action_executed = auto()        # file/shell/search returned result
    action_exec_error = auto()      # execution failed

    reward_scored = auto()          # value function scored the action

    search_continues = auto()       # backprop done, not finished yet
    search_finished = auto()        # termination condition met
    single_candidate = auto()       # only one finished trajectory
    multiple_candidates = auto()    # need discriminator
    best_selected = auto()          # discriminator picked winner

    # --- Shared ---
    io_result = auto()              # generic dispatcher result
    io_error = auto()
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
    # === Outer agent: user asks, LLM decides to use MCTS ===
    T(S.IDLE,                   E.user_message,             S.CALLING_LLM,              ("write_user_message", "compile_and_call_llm")),
    T(S.CALLING_LLM,            E.llm_decided_mcts,         S.MCTS_SELECT,              ("record_budget", "init_search_tree")),
    T(S.CALLING_LLM,            E.llm_response_text,        S.DISPLAYING,               ("record_budget", "write_assistant_msg")),
    T(S.CALLING_LLM,            E.llm_error,                S.IDLE,                     ("display_error",)),

    # === MCTS SELECT: pick node via UCT (pure computation) ===
    T(S.MCTS_SELECT,            E.node_selected,            S.MCTS_EXPAND,              ()),
    T(S.MCTS_SELECT,            E.no_expandable_nodes,      S.MCTS_DISCRIMINATE,        ()),  # tree exhausted → discriminate

    # === MCTS EXPAND: create child, clone state (pure) ===
    T(S.MCTS_EXPAND,            E.expanded_no_feedback,     S.MCTS_ACTION_GEN,          ("clone_file_context",)),
    T(S.MCTS_EXPAND,            E.expanded_needs_feedback,  S.MCTS_FEEDBACK,            ("clone_file_context", "submit_feedback_llm")),

    # === MCTS FEEDBACK: analyze siblings, generate guidance (LLM call) ===
    T(S.MCTS_FEEDBACK,          E.io_result,                S.MCTS_ACTION_GEN,          ("store_feedback",)),    # feedback ready → continue
    T(S.MCTS_FEEDBACK,          E.io_error,                 S.MCTS_ACTION_GEN,          ()),                     # feedback failed → continue without it

    # === MCTS ACTION GENERATION: ask LLM what action to take (LLM call) ===
    T(S.MCTS_ACTION_GEN,        E.io_result,                S.MCTS_ACTION_EXEC,         ("parse_action", "check_duplicate")),
    T(S.MCTS_ACTION_GEN,        E.io_error,                 S.MCTS_BACKPROP,            ("set_error_reward",)),  # LLM failed → backprop with negative reward

    # === MCTS ACTION EXECUTION: run action against code (file/shell/search) ===
    T(S.MCTS_ACTION_EXEC,       E.action_is_duplicate,      S.MCTS_BACKPROP,            ("mark_duplicate",)),    # skip exec, backprop with 0
    T(S.MCTS_ACTION_EXEC,       E.io_result,                S.MCTS_EVALUATE,            ("store_observation", "submit_evaluate_llm")),
    T(S.MCTS_ACTION_EXEC,       E.io_error,                 S.MCTS_EVALUATE,            ("store_error_observation", "submit_evaluate_llm")),

    # === MCTS EVALUATE: value function scores the action (LLM call) ===
    T(S.MCTS_EVALUATE,          E.io_result,                S.MCTS_BACKPROP,            ("store_reward",)),
    T(S.MCTS_EVALUATE,          E.io_error,                 S.MCTS_BACKPROP,            ("set_default_reward",)),  # eval failed → use 0

    # === MCTS BACKPROP: propagate reward up tree (pure computation) ===
    T(S.MCTS_BACKPROP,          E.search_continues,         S.MCTS_SELECT,              ("persist_tree",)),       # loop back
    T(S.MCTS_BACKPROP,          E.search_finished,          S.MCTS_DISCRIMINATE,        ("persist_tree",)),       # done → select best

    # === MCTS DISCRIMINATE: pick best trajectory ===
    T(S.MCTS_DISCRIMINATE,      E.single_candidate,         S.DISPLAYING,               ("format_result",)),
    T(S.MCTS_DISCRIMINATE,      E.multiple_candidates,      S.MCTS_DISCRIMINATE_WAITING, ("submit_debate_llm",)),
    T(S.MCTS_DISCRIMINATE,      E.no_expandable_nodes,      S.DISPLAYING,               ("format_best_effort_result",)),  # no finished → best leaf
    T(S.MCTS_DISCRIMINATE_WAITING, E.io_result,             S.DISPLAYING,               ("select_winner", "format_result")),
    T(S.MCTS_DISCRIMINATE_WAITING, E.io_error,              S.DISPLAYING,               ("format_fallback_result",)),

    # === Shared tail (same as 01) ===
    T(S.DISPLAYING,             E.display_done,             S.CLEANING_UP,              ()),
    T(S.CLEANING_UP,            E.extraction_needed,        S.EXTRACTING,               ("cleanup_integrations",)),
    T(S.CLEANING_UP,            E.no_extraction,            S.IDLE,                     ("cleanup_integrations",)),
    T(S.EXTRACTING,             E.extraction_done,          S.IDLE,                     ()),
    T(S.EXTRACTING,             E.consolidation_needed,     S.CONSOLIDATING,            ()),
    T(S.EXTRACTING,             E.error,                    S.IDLE,                     ("display_error",)),
    T(S.CONSOLIDATING,          E.consolidation_done,       S.IDLE,                     ()),
    T(S.CONSOLIDATING,          E.error,                    S.IDLE,                     ("display_error",)),
]


# --- Actions (stubs) ---

def init_search_tree() -> None:
    """Create root Node with task description and empty FileContext."""
    ...

def clone_file_context() -> None:
    """Deep-copy parent's FileContext to child node."""
    ...

def submit_feedback_llm(sibling_actions: list, tree_viz: str) -> None:
    """Send sibling analysis prompt to LLMDispatcher for feedback generation."""
    ...

def store_feedback(feedback_text: str) -> None:
    """Attach feedback to the current child node."""
    ...

def submit_action_gen_llm(history: list, tools: list, feedback: str) -> None:
    """Send action generation prompt to LLMDispatcher."""
    ...

def parse_action(llm_response: str) -> tuple:
    """Parse LLM response into action_name + action_args."""
    ...

def check_duplicate() -> bool:
    """Check if parsed action is identical to a sibling's action."""
    ...

def mark_duplicate() -> None:
    """Set is_duplicate=True on the node. Skip execution."""
    ...

def submit_action_exec(action_name: str, action_args: dict) -> None:
    """Route action to appropriate dispatcher:
    StringReplace → FileDispatcher
    SemanticSearch → SearchDispatcher
    RunTests → ShellDispatcher
    ViewCode → FileDispatcher
    Finish/Reject → no dispatch, handle locally"""
    ...

def store_observation(result: str) -> None:
    """Store action result as Observation on the node."""
    ...

def store_error_observation(error: str) -> None:
    """Store error as Observation on the node."""
    ...

def submit_evaluate_llm(action: str, observation: str, file_context: str) -> None:
    """Send value function prompt to LLMDispatcher.
    Includes per-action evaluation criteria and reward scale."""
    ...

def store_reward(reward: int, explanation: str) -> None:
    """Store Reward on the node. Check termination conditions."""
    ...

def set_default_reward() -> None:
    """Use 0 reward when value function fails."""
    ...

def set_error_reward() -> None:
    """Use -100 reward when action generation fails."""
    ...

def backpropagate() -> None:
    """Walk from node to root, increment visits, add reward to value."""
    ...

def check_termination() -> bool:
    """Check: max_cost, max_iterations, max_finished_nodes, reward_threshold."""
    ...

def persist_tree() -> None:
    """Save tree to JSON and log ASCII visualization."""
    ...

def submit_debate_llm(candidates: list) -> None:
    """Send multi-agent debate prompt to LLMDispatcher.
    N agents × N rounds comparing git patches."""
    ...

def select_winner(debate_result: str) -> None:
    """Parse debate consensus into trajectory selection."""
    ...

def format_result(trajectory: list) -> str:
    """Format winning trajectory as the final answer."""
    ...

def format_best_effort_result() -> str:
    """Format best leaf node when no Finish exists."""
    ...

def format_fallback_result() -> str:
    """Format first candidate when debate fails."""
    ...


# ---------------------------------------------------------------------------
# Trace — one full MCTS iteration
# ---------------------------------------------------------------------------
#
# Starting from MCTS_SELECT (iteration 3, tree has 2 nodes):
#
# MCTS_SELECT:
#   action: compute UCT for all expandable nodes
#   UCT(root) = inf (unvisited), UCT(child-0) = 0.65
#   → event: node_selected (root)
#
# MCTS_EXPAND:
#   action: clone root's FileContext to child-2
#   root already has child-0 → this is the 2nd child → needs feedback
#   → event: expanded_needs_feedback
#   actions: clone_file_context, submit_feedback_llm
#
# MCTS_FEEDBACK (waiting for LLM):
#   LLMDispatcher calls haiku: "Previous attempt: SemanticSearch for auth.
#   Suggest different approach."
#   → event: io_result ("Try session management code instead")
#   action: store_feedback
#
# MCTS_ACTION_GEN:
#   action: submit_action_gen_llm (includes stored feedback)
#   LLMDispatcher calls sonnet: "Given state + feedback, what action?"
#   → event: io_result ("FindFunction: check_session")
#   actions: parse_action, check_duplicate (not duplicate)
#
# MCTS_ACTION_EXEC:
#   action: submit_action_exec → SearchDispatcher
#   → event: io_result ("Found check_session in session.py lines 12-45")
#   actions: store_observation, submit_evaluate_llm
#
# MCTS_EVALUATE:
#   LLMDispatcher calls haiku with evaluation criteria for FindFunction:
#     "Score -100 to 100. Criteria: found exact function? relevant to task?"
#   → event: io_result (reward=55, "Found alternative angle, promising")
#   action: store_reward
#
# MCTS_BACKPROP:
#   action: backpropagate (child-2.reward=55, root.visits++, root.value+=55)
#   action: check_termination → not finished (< 3 finished nodes)
#   action: persist_tree
#   → event: search_continues
#
# → MCTS_SELECT (next iteration)


# ---------------------------------------------------------------------------
# Comparison: 07 (interpreter) vs 07b (pure state machine)
# ---------------------------------------------------------------------------
#
# | Dimension              | 07 (interpreter)      | 07b (pure SM)          |
# |------------------------|-----------------------|------------------------|
# | MCTS states            | 0 (hidden in code)    | 13 explicit states     |
# | Total states           | 8                     | 19                     |
# | Total transitions      | 18                    | 31                     |
# | MCTS loop              | Python while loop     | SELECT→...→BACKPROP→SELECT cycle |
# | Tree data structure    | interpreter locals    | engine-managed data    |
# | Visibility             | opaque                | every phase visible    |
# | Debuggability          | print inside code     | state transition log   |
# | Universality           | same SM for all algos | need new states per algo |
# | Interpreter needed     | yes (with yields)     | no                     |
# | New algorithm cost     | write code            | add states + transitions |
#
# The pure SM approach is MORE VISIBLE (you can see "we are in MCTS_EVALUATE")
# but LESS UNIVERSAL (adding a new algorithm means adding new states).
#
# The interpreter approach is MORE UNIVERSAL (any algorithm, same SM)
# but LESS VISIBLE (from outside, it's all just "INTERPRETING").
#
# A hybrid is possible: the interpreter approach (07) with status annotations
# that make the current phase visible without adding states.
