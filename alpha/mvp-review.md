# Micro-MVP Review: Built vs Planned

Date: 2026-03-18 (original), 2026-03-19 (updated)

---

## 1. What Was Built

~4,100 lines of Python across 18 files (14 core + 4 integration modules). A working CLI chatbot with:

- **Stateless disk-first engine** — read disk, build context, call LLM, write to disk. Kill and restart continues seamlessly.
- **Code-as-action sandbox** — smolagents LocalPythonExecutor with 17+ workspace functions injected via 4 integration modules. 6 API tools: python_exec, memory_update, retire_observation, moan, confirm_knowledge, use_knowledge.
- **Integration module system** — auto-discovery loader (integrations.py) scans integration/ for Python files with register() functions. Drop a file, restart, done. Each module provides functions, system prompt additions, and optional lifecycle hooks (cleanup_step, reset_session).
- **File editing library** (integration/file_edit.py, ~900 lines) — full read/write/edit capabilities: singleton live File handles with write-back buffers, `edit()` with 5-strategy fuzzy matching cascade (exact, line-trimmed, indent-flexible, whitespace-normalized, escape-normalized), `write()`, `insert()`, `replace_lines()`, `edit_regex()`, `append()`, atomic `batch()` for multi-file edits, `delete()`, `move()`, `copy()`, `find()` for glob search. Design report (file_edit.md) compares against OpenHands, Cline, OpenCode, Aider, smolagents.
- **Shell sandbox** (integration/shell_exec.py, ~500 lines) — macOS Seatbelt kernel-enforced sandbox for shell commands. Dynamically generates .sbpl policy profiles: deny-default, workspace-only writes, blocked ~/.dotfiles and ~/Library reads, blocked network by default, .git and .superagent protection, git worktree awareness. Auto-discovers tool paths (conda, nvm, pyenv, cargo, go) via profile system. Design report (shell_exec.md) documents every decision against Codex CLI. Has passing tests (test_shell_sandbox.py).
- **Web search** (integration/web_search.py) — local SearXNG metasearch (DuckDuckGo/Brave/Bing). Two functions: web_search() for formatted text, web_search_json() for structured dicts. Requires SearXNG Docker container.
- **Workspace search** (integration/workspace_files.py) — ripgrep-powered content search with smart-case, word boundaries, context lines, glob filtering. Plus now() timestamp.
- **Working memory** — 4 YAML key-value blocks (persona, workspace_info, user_preferences, current_domain) compiled into XML in the system prompt.
- **Python-first observations** — knowledge stored as .py files with metadata in docstrings. Data structures for facts, comments for insights, functions for operations.
- **Extraction pipeline** — Opus segments conversation into episodes, extracts 1-3 most significant observations per episode. Triggered every 10 user messages.
- **Domain detection** — gpt-4.1-nano classifies each user message. 3-mention threshold before a new domain is created.
- **Consolidation** — when a domain exceeds 20 observations, Opus merges them into fewer patterns. Consumed observations retired.
- **Observations always in context** — all active observations injected into system prompt with ID-suffixed names. No search needed.
- **Function call metrics** — success/failed counters per observation, written immediately to disk.
- **Feedback tools** — moan (write-only pain reports about capability gaps, appended to moans.jsonl), confirm_knowledge and use_knowledge (signal that an observation was validated or essential, appended to signals.jsonl). These provide human-reviewable friction data and knowledge utility signals.
- **Rich system prompt** — detailed guidance for file lookup (auto-search on FileNotFoundError), file reading (process in memory, do not print chunks), writing/creative tasks (decide unique value before gathering data), and feedback tool usage (always moan on capability gaps).

### Current Knowledge Store State

- **5 domains**: project_overview (6 obs), agent_research (8 obs), concept_research (14 obs), tool_evaluation (3 obs), user_preferences (1 obs)
- **32 total active observations** across all domains
- **0 domains have hit consolidation cap** (20) — consolidation untested with real data
- **0 observations have non-zero call metrics** — no functions have been called by the agent yet
- **Extraction pointer**: 27 user messages processed

### Working Memory State

- persona: default identity string
- workspace_info: empty (agent never populated it)
- user_preferences: `name: Igor`
- current_domain: tool_evaluation (last detected)

---

## 2. Plan vs Reality: Feature Comparison

### What shipped as planned

| Feature | Plan | Status |
|---|---|---|
| Stateless disk-first engine | Day 1 | Done |
| CLI readline loop | Day 1 | Done |
| Session JSONL persistence | Day 1 | Done |
| Working memory blocks | Day 3 | Done |
| memory_update tool | Day 3 | Done |
| Knowledge store with observations | Day 4 | Done |
| Episode segmentation | Day 4-5 | Done |
| Predict-calibrate extraction | Day 5 | Done |
| Domain detection | Day 6 | Done |
| Consolidation | Day 7 | Done |
| OpenRouter + Ollama providers | Day 1 | Done |
| Verbose debug output | Day 1 | Done |
| File write/edit operations | Day 2 | Done (via file_edit.py integration) |
| Integration module system | (not in plan) | Done - auto-discovery plugin loader |
| Shell sandbox | (not in plan) | Done - macOS Seatbelt kernel enforcement |
| Web search | (not in plan) | Done - SearXNG integration |
| Feedback tools (moan, confirm, use) | (not in plan) | Done - friction and knowledge signals |

### What diverged from the plan

| Aspect | Original Plan | What Was Built | Why |
|---|---|---|---|
| Action modality | 9 separate JSON tools | Code-as-action via smolagents | smolagents research insight: code is more composable than tool calls |
| Observation format | YAML text files | Python .py files | Code-as-knowledge thesis from doc 02. Comments for text, dicts for facts, functions for operations |
| Observation retrieval | knowledge_search tool | Always in context | With cap of 20/domain, total tokens are bounded. Simpler. |
| Extraction model | Haiku (cheap) | Opus (quality) | Haiku/nano produced garbage extractions. Quality requires a strong model. |
| Consolidation trigger | Idle detection (30s timer) | After extraction, if cap exceeded | Foreground is more visible for research. D7 decision. |
| EventBus tiers | 3 async tiers, background queue | Sync-only emit, async unused | Extraction/consolidation run foreground. No background work needed. |
| File operations | API tools (get_file, create_file, replace_lines, replace_file) | Python functions inside sandbox via integration modules | Code-as-action means file ops are function calls in python_exec. file_edit.py provides read/edit/write/insert/replace_lines/batch/delete/move/copy/find with fuzzy matching and atomic writes. |
| Chat model | Claude Sonnet | Claude Opus 4.6 | Originally Haiku for cost, later upgraded to Opus. config.py DEFAULT_CHAT_MODEL is now claude-opus-4.6. |
| Fast model | (not in plan) | gpt-4.1-nano | Domain detection needs speed, not depth. |
| Integration system | (not in plan) | Auto-discovery plugin loader | integrations.py scans integration/ for .py files with register(). Four modules shipped: file_edit, shell_exec, web_search, workspace_files. |
| Shell execution | (not in plan) | macOS Seatbelt kernel sandbox | Inspired by Codex CLI. Every shell command wrapped with sandbox-exec. Deny-default, workspace-only writes, blocked secrets. |
| Web search | (not in plan) | SearXNG metasearch | Local Docker container aggregates DuckDuckGo, Brave, Bing. |
| Feedback tools | (not in plan) | moan, confirm_knowledge, use_knowledge | Write-only friction reports and knowledge utility signals for human review. |

### What was NOT built

| Feature | Plan Section | Status | Notes |
|---|---|---|---|
| 50-task experiment | Day 8-10 | Not done | The primary evaluation phase was never executed |
| Measurement metrics | Day 8-10 | Not built | No task completion tracking, steps/task, cost/task, knowledge reuse rate |
| Session archive search | Design doc | Not built | Deferred per logbook |
| Domain profiles | Day 6 | Not built | profile.yaml per domain was planned but not implemented |
| Lockfile system | Day 1 | Not built | current.lock mentioned in scope but never implemented |
| Budget tracking | engine.py | Stub only | System prompt shows "estimating..." and "$0.00" hardcoded |
| EventBus background processing | Day 7 | Not used | The async queue infrastructure exists but nothing uses it |

Note: Write operations were listed as "not built" in the original review but have since been implemented via file_edit.py integration (write, edit, insert, replace_lines, edit_regex, append, batch, delete, move, copy).

---

## 3. Observation Quality Assessment

I read all 32 observations. Here is the assessment.

### Good observations (high value, project-specific)

These capture real knowledge that would help the agent work faster next time:

- **obs-d55a1c30** (edit_format_taxonomy) — rich cross-product comparison data structure with sources. Exactly what the extraction should produce.
- **obs-6ed3ab4b** (persistent_memory_patterns) — taxonomy with key finding about most agents lacking memory. Source-cited.
- **obs-f97db2c8** (letta_code) — structured product profile with commit hash, repo, features. Reusable.
- **obs-864dd05f** (research_project_stats) — concrete numbers: 38 projects, 7 categories with counts. Useful for any "how many" question.
- **obs-689ec753** (infrastructure_agent_signals) — criteria list for classification. Analytical, not just factual.
- **obs-4c792000**, **obs-6cee40ab**, **obs-e1561365** (GAP observations) — three observations that identify missing research artifacts. Valuable for guiding future work.
- **obs-97c11580** (terminology gap) — "persistent memory" not "long term memory". Practical search tip.

### Mediocre observations (partial value, redundant, or stale)

- **obs-271fbb63** (agent_categories) — lists are stale. The data structure shows old categories from an earlier version of AGENTS.md. Would need retirement.
- **obs-a2b3b8e9** (agentic_loop_types) — subset of obs-1dfbeff2 and obs-31bb9ebb. Three observations cover the same taxonomy at different completeness levels.
- **obs-c55350d4** and **obs-38407fb2** and **obs-1faa40dc** — three separate Cline observations with overlapping info. Prime consolidation target.
- **obs-0ec51dc9** (get_product_docs / get_concept_docs functions) — trivial path-construction functions. The plan explicitly says to skip "generic utility functions any programmer could write."
- **obs-a90bcb43** (project_structure dict) — records r/ and superagent/ as "needs exploration." Already explored. Stale.

### Pattern: redundancy within domains

- **agent_research**: 3 observations about Cline (obs-1faa40dc, obs-38407fb2, obs-c55350d4) that overlap significantly. Plus 2 about Claude Code classification (obs-8dc4cf3b, obs-689ec753) that are complementary but could merge.
- **concept_research**: 3 observations about agentic loop taxonomy (obs-1dfbeff2, obs-31bb9ebb, obs-a2b3b8e9) at different granularity. Plus 3 GAP observations about edit formats (obs-4c792000, obs-6cee40ab, obs-e1561365) that are variations on the same finding.
- **project_overview**: obs-271fbb63 and obs-864dd05f both count projects but with different numbers (old vs new data).

### Assessment summary

| Rating | Count | % |
|---|---|---|
| Good (high-value, project-specific) | 12 | 38% |
| Mediocre (partial value or redundant) | 14 | 44% |
| Low (trivial, stale, or should retire) | 6 | 19% |

**Key issue: predict-calibrate is not deduplicating effectively.** The same taxonomy (agentic loop types) appears in 3 separate observations extracted at different times. The warm-path prompt retrieves existing knowledge and asks for deltas, but the LLM is still producing overlapping content. This is the #1 extraction quality problem.

**Positive signal:** The Python-first format works well. Data structures (dicts, lists) are more useful than English prose. The GAP observations are genuinely valuable — they capture what is missing, not just what exists. Source file paths are consistently included.

---

## 4. Success Criteria Evaluation

### Minimum: Pipeline runs for 50 tasks. Observations accumulate. At least 2 domains discovered. No crashes.

**Partially met.**
- Pipeline runs: yes, 27 user messages processed without crashes.
- Observations accumulate: yes, 32 observations across 5 domains.
- Domains discovered: yes, 5 domains (exceeds the 2 minimum).
- No crashes: yes, stable operation.
- **NOT met**: only 27 tasks, not 50. The 50-task experiment was never executed.

### Good: Patterns form correctly. Agent uses knowledge by task 30+. Steps decrease.

**Not evaluated.** Consolidation has not triggered (no domain at 20+). No measurement of knowledge reuse or step reduction exists. The agent has all 32 observations in context but we have no data on whether it references them in later turns.

### Great: Python scripts become reusable. Cross-domain patterns emerge.

**Not evaluated.** No observation functions have been called (all call metrics are 0/0). The functions that exist (get_product_docs, get_concept_docs) are trivial. No cross-domain patterns have been detected because consolidation has not run.

---

## 5. Architecture Assessment

### What works well

1. **Stateless disk-first design** — the core architectural decision is clean and correct. Kill and restart works. The JSONL + YAML + .py file structure is simple and inspectable.

2. **Code-as-action** — smolagents sandbox is a good choice. The agent writes Python that calls workspace functions. More composable than individual tool calls. The ripgrep-powered search is particularly well-designed (smart-case, word boundaries, context lines, glob filtering).

3. **Python-first observations** — better than YAML text. Data structures are directly usable. The exec-and-alias pattern (exec whole body, export with ID suffix) solves the namespace collision problem elegantly.

4. **Foreground pipeline** — making extraction and consolidation visible was the right call for a research project. You can see exactly what the pipeline produces.

5. **Atomic writes** — proper write-to-temp-then-rename everywhere. No corruption risk.

6. **Integration module system** — the auto-discovery plugin architecture (integrations.py) is clean and extensible. Drop a .py file in integration/, restart, done. Each module self-registers its functions, system prompt additions, and lifecycle hooks. Four production-quality modules shipped.

7. **File editing library** — file_edit.py is the most sophisticated component. The 5-strategy fuzzy matching cascade handles real LLM errors (indentation, whitespace, escapes) that other agents force retries on. Singleton live File handles with write-back buffers, mtime-based freshness detection, atomic batch operations. The design report compares against 5 other agents.

8. **Shell sandbox** — shell_exec.py provides Codex CLI-grade kernel-enforced sandboxing via macOS Seatbelt. Deny-default policy, workspace-only writes, blocked secrets (~/.ssh, ~/Library), .git protection with git-worktree awareness, auto-discovered tool paths via profile system. This is among the strongest sandboxing in the 36 projects studied.

9. **Feedback tools** — moan, confirm_knowledge, and use_knowledge provide structured signals that existing agents lack. Friction reports (moans.jsonl) are actionable for API improvement. Knowledge signals (signals.jsonl) provide ground truth on which observations are actually useful.

### What needs work

1. **Empty workspace_info** — the agent never populated the workspace_info memory block despite having the memory_update tool. This suggests the system prompt does not strongly enough instruct the agent to use working memory proactively.

2. **Observations always in context** — works at 32 observations (maybe 3-5K tokens). Will NOT work at 100+ observations. The design acknowledges this (Q3 in logbook) but there is no fallback implemented. With 5 domains at cap 20, theoretical max is 100 observations in context — borderline.

3. **Budget tracking is a stub** — the system prompt claims to show context usage and session cost, but both are hardcoded placeholders. Misleading.

4. **README is stale** — references .md memory files that were replaced with .yaml. Does not mention extraction, consolidation, domains, observations, integration modules, file editing, shell sandbox, web search, or feedback tools.

5. **EventBus is dead code** — the entire async tier (on_async, run_background, _bg_queue) is unused. The sync emit is used only for LLM call/tool call events, and nothing listens to those events. The EventBus could be removed entirely without affecting functionality.

6. **All three LLM tiers use Opus** — config.py sets DEFAULT_CHAT_MODEL, DEFAULT_CONSOLIDATION_MODEL both to claude-opus-4.6. Only domain detection uses gpt-4.1-nano. Running Opus for every chat turn is expensive. The original plan used Haiku for chat. The upgrade was likely during debugging, but the cost implications for a 50-task experiment are significant.

---

## 6. Testing Strategy

### What to test

The system has no tests. Here is a priority-ordered testing plan.

#### Tier 1: Unit tests (high value, easy to write)

These test isolated components with no LLM calls.

1. **knowledge.py** — the most complex module
   - `KnowledgeStore.add()` → verify .py file created with correct metadata in docstring
   - `KnowledgeStore.retire()` → verify retired flag set, excluded from load_all_active
   - `KnowledgeStore.search()` → FTS5 search returns matching observations
   - `KnowledgeStore.record_call()` → verify counters increment in file
   - `_parse_metadata()` → extract metadata from docstring correctly
   - `_build_source()` → round-trip: build source, parse metadata, verify fields match
   - `sanitize_name()` → edge cases: spaces, special chars, empty string

2. **memory.py** — key-value operations
   - `update_entry()` → set, update, delete operations
   - `update_entry()` → read-only block rejection
   - `update_entry()` → capacity limit enforcement
   - `compile_blocks_xml()` → XML output format correctness
   - `ensure_block_files()` → creates defaults, does not overwrite existing

3. **integration/workspace_files.py** — path validation and search
   - `_validate_path()` → rejects absolute paths, rejects path traversal (../../..)
   - `_validate_path()` → allows valid relative paths
   - `ripgrep()` — needs rg installed, test basic pattern matching, glob filtering, context lines

4. **integration/file_edit.py** — the largest module, needs thorough testing
   - `edit()` exact match → single match works, multiple match raises MultipleMatchError
   - `edit()` fuzzy cascade → line-trimmed, indent-flexible, whitespace-normalized, escape-normalized
   - `edit()` dotdotdot → wildcard matching with ... patterns
   - `write()` → creates new file, raises on existing unless overwrite=True
   - `insert()` → inserts after line number, edge cases (line 0, line -1)
   - `batch()` → atomic multi-file: all succeed or all rollback
   - `batch()` nesting → inner batch is transparent
   - File handle singleton → same path always returns same object
   - mtime check → FileModifiedError on external modification
   - `find()` → glob patterns, depth limiting, >100 result limit
   - `_find_similar()` → suggestion quality for NoMatchError
   - NOTE: shell_exec.py already has test_shell_sandbox.py with passing tests

5. **atomicfile.py** — write safety
   - Verify temp file created then renamed
   - Verify content matches after write

6. **config.py** — configuration loading
   - Default values when no config file
   - ENV var overrides
   - CLI arg overrides

#### Tier 2: Integration tests (moderate value, need temp dirs)

These test component interactions without LLM calls.

1. **engine.py** — session management
   - `append_message()` + `load_history()` round-trip
   - `new_session()` → archives current, creates new
   - `compile_system_prompt()` → includes memory blocks, observations, function stubs

2. **tools.py** — tool registry and dispatch
   - `build_registry()` → 6 tools registered (python_exec, memory_update, retire_observation, moan, confirm_knowledge, use_knowledge)
   - `dispatch("python_exec", ...)` → executes code, returns output
   - `_load_observation_symbols()` → loads functions with ID suffix into sandbox
   - metrics wrapper → success/failure counters update on disk

3. **extraction.py** — message counting and pointer
   - `_count_user_messages()` → counts only user role messages
   - `_load_messages_since()` → loads messages after pointer
   - `_read_pointer()` / `_write_pointer()` → round-trip

4. **domain.py** — threshold logic
   - New domain requires 3 mentions before creation
   - Existing domain detected with confidence >= 0.5
   - `_get_existing_domains()` → scans disk correctly

#### Tier 3: End-to-end tests (high value, need LLM, expensive)

These test the full pipeline with real LLM calls.

1. **Cold start smoke test** — fresh sandbox, one user message, verify response written to JSONL
2. **Extraction smoke test** — 10 user messages, verify extraction runs and produces observations
3. **Consolidation smoke test** — manually create 21+ observations in a domain, trigger consolidation, verify patterns created and observations retired
4. **Domain detection smoke test** — 3 messages about the same topic, verify domain created
5. **Knowledge reuse test** — create observations with functions, verify agent can call them in python_exec

### Test infrastructure needed

```
superagent/alpha/tests/
  conftest.py              — fixtures: tmp_dir, mock config, sample observations
  test_knowledge.py        — tier 1: knowledge store CRUD, metadata, FTS5
  test_memory.py           — tier 1: block read/write, capacity, XML rendering
  test_file_edit.py        — tier 1: fuzzy matching, batch, singleton handles, mtime
  test_workspace_files.py  — tier 1: path validation, ripgrep
  test_atomicfile.py       — tier 1: atomic write safety
  test_config.py           — tier 1: config loading, env overrides
  test_engine.py           — tier 2: session JSONL, system prompt compilation
  test_tools.py            — tier 2: registry, dispatch, observation symbol loading
  test_extraction.py       — tier 2: message counting, pointer management
  test_domain.py           — tier 2: threshold logic, domain scanning
  test_e2e.py              — tier 3 (marked slow, optional)
```

Note: shell_exec.py already has test_shell_sandbox.py at the superagent/ root level.

Run with: `pytest superagent/alpha/tests/ -v`
Skip expensive tests: `pytest -m "not slow"`

**Estimated effort: 1-2 days for Tier 1+2. Tier 3 is ongoing.**

---

## 7. What To Do Next

### Option A: Run the 50-task experiment now

**What:** Execute the original Day 8-10 plan. 50 real tasks across 3 phases (cold start, domain formation, knowledge reuse). Measure everything.

**Pros:** This is what the MVP was built to test. We have 32 observations from organic use — now we need systematic data. The experiment will reveal whether extraction quality improves with predict-calibrate, whether consolidation produces useful patterns, and whether the agent actually gets faster. Write operations are now available via file_edit.py, so the full use case can be tested.

**Cons:** Budget tracking and measurement metrics are still missing. Running the experiment without metrics means we would be eyeballing results. The default chat model is now Opus, which will be expensive for 50 tasks — consider downgrading to Haiku or Sonnet for the experiment.

**Prerequisite:** At minimum, add basic per-turn logging (tokens, tool calls, cost) to a metrics file.

### Option B: Fix extraction quality first

**What:** Address the #1 quality problem: predict-calibrate is not deduplicating. 3 observations about agentic loop taxonomy, 3 about Cline, 3 about edit format gaps.

**Approach:**
1. Make the warm-path prompt more aggressive about rejecting overlapping content
2. Add a post-extraction deduplication step using embedding similarity
3. Consider: should extraction receive ALL existing observations for the domain, not just search results?
4. Test with the existing 27 messages: wipe observations, re-extract, compare

**Effort:** 1 day

### ~~Option C: Add write operations~~ DONE

~~**What:** Implement create_file, replace_lines, replace_file as sandbox functions.~~

Implemented via file_edit.py integration module. The agent now has full file editing capabilities: read, edit (with fuzzy matching), write, insert, replace_lines, edit_regex, append, batch (atomic multi-file), delete, move, copy, find.

### Option D: Write tests first

**What:** Implement Tier 1 and Tier 2 tests before changing anything else. Establish a safety net. Should now also cover file_edit.py (fuzzy matching, batch atomicity, mtime checks) and shell_exec.py (policy generation, denial detection). The shell sandbox already has test_shell_sandbox.py which can serve as a starting point.

**Effort:** 1-2 days

### Option E: Add measurement infrastructure

**What:** Build the metrics pipeline from the Day 8-10 plan:
- Per-turn: tokens in/out, model, tool calls, cost, duration
- Per-session: task count, total cost
- Per-task: completion (manual label), steps, cost
- Knowledge: observations created, retired, functions called, domains active
- Feedback: moan count by category, confirm/use signal count

Write to a metrics JSONL that can be analyzed with pandas.

**Effort:** 0.5-1 day

### Option F: Downgrade chat model for cost control

**What:** Change DEFAULT_CHAT_MODEL back to claude-3.5-haiku or claude-sonnet-4.6 for the chat tier. Keep Opus only for extraction/consolidation where quality matters. The current config runs Opus for every chat turn, which is unnecessarily expensive for tool-calling interactions.

**Effort:** 5 minutes (one line in config.py)

### Recommended sequence

1. **F: Downgrade chat model** (5 min) — stop burning Opus tokens on routine chat turns
2. **E: Metrics** (0.5 day) — cannot evaluate anything without measurement
3. **B: Fix extraction** (1 day) — the pipeline is the thing we are testing, fix it before running the experiment
4. **A: Run the 50-task experiment** (2-3 days) — write operations are ready, measure properly
5. **D: Tests** (ongoing) — add tests as bugs are found during the experiment

Total: ~4 days to a proper evaluation. (Option C is already done.)

---

## 8. Specific Bugs and Issues Found

1. **obs-271fbb63 has stale data** — agent_categories dict lists old categories that do not match current AGENTS.md. The extraction did not notice the data was from an older version of the file.

2. **obs-a90bcb43 marks r/ and superagent/ as "needs exploration"** — they were explored later but the observation was not retired. The agent did not use retire_observation to clean up.

3. **workspace_info memory block is empty** — the agent never proactively stored workspace structure despite exploring the directory. The system prompt instruction to "update keys as you learn more" is too weak.

4. **README.md references .md memory files** — should be .yaml. Documentation is stale.

5. **Budget section in system prompt** — "estimating..." and "$0.00" are misleading. Either implement or remove.

6. **search_files observation is partially wrong** — obs-6bf334b4 says "does NOT support a recursive parameter" — but search_files is always recursive by design (ripgrep walks dirs). The observation confuses the search_files function (which has no recursive param because it is always recursive) with list_dir (which has recursive).

7. **Three agentic_loop_types variables** — obs-a2b3b8e9, obs-1dfbeff2, obs-31bb9ebb all define `agentic_loop_types` as a top-level variable. After exec-and-alias, they become `agentic_loop_types_a2b3b8e9`, `agentic_loop_types_1dfbeff2`, `agentic_loop_types_31bb9ebb` — three copies of roughly the same data in the sandbox namespace.

---

## 9. Key Learnings from the Build

1. **Model quality matters enormously for extraction.** Haiku/nano produced garbage. Opus produces reasonable results. This is a fixed cost — you cannot save money on the model that distills your knowledge.

2. **Deduplication is harder than extraction.** Getting the LLM to produce observations is easy. Getting it to NOT produce observations that overlap with existing ones is the real challenge. The predict-calibrate mechanism works in theory but the warm-path prompt needs significant tuning.

3. **Python-first observations are a win.** Data structures are more useful than English prose. `persistent_memory_patterns = {'memory-first': [...], ...}` beats "There are 6 patterns of persistent memory." Source paths as comments work well.

4. **Code-as-action via smolagents is clean.** The sandbox provides real isolation. The function injection pattern is simple. The LLM writes reasonable Python most of the time. (Note: the chat model is now Opus, not Haiku as originally planned — this should be downgraded for cost before the 50-task experiment.)

5. **Observations-in-context scales better than expected.** 32 observations in the system prompt is fine. The theoretical cap of ~100 (5 domains x 20) should also be manageable. The knowledge_search removal was the right simplification.

6. **The agent does not proactively learn.** Despite having memory_update, the agent rarely uses it. The system prompt needs stronger nudges, or a post-turn reflection step that explicitly asks "what should I remember from this interaction?"

7. **The integration module system exceeded the plan.** The original 14-doc.md plan had no plugin architecture. The integration loader was a pragmatic addition that turned out to be the right separation of concerns: core agent logic in superagent/, workspace capabilities in integration/. Four production-quality modules shipped (file_edit, shell_exec, web_search, workspace_files), each with its own design report. The system prompt assembles dynamically from module contributions.

8. **Kernel-enforced sandboxing is achievable without containers.** shell_exec.py proves that macOS Seatbelt provides Codex CLI-grade security with zero infrastructure overhead. The dynamically-generated policy profiles, deny-after-allow ordering, and git worktree awareness are non-trivial but the result is a single .py file with no dependencies beyond macOS itself.

9. **Fuzzy matching is essential for LLM-driven file editing.** file_edit.py's 5-strategy cascade (exact, line-trimmed, indent-flexible, whitespace-normalized, escape-normalized) handles the most common LLM errors automatically. Only 3 of 33 projects in the research study implement fuzzy matching — the rest force retries that waste turns and tokens. The research directly informed the implementation.
