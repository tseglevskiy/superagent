# Knowledge Reflection — Evolving and Verifying What the Agent Knows

## Why Reflection Is Not Optional

Doc 11 describes HOW knowledge is stored.
This document describes how the agent LOOKS AT its own knowledge and decides:
- Is this still true?
- Does this contradict something else I know?
- Is this generalization still valid?
- Should these two patterns merge into one concept?
- Is something missing that I should know by now?

Without reflection, the Knowledge Store degrades over time.
Old observations become irrelevant.
Generalizations ossify.
Contradictions accumulate silently.
The agent becomes increasingly confident in increasingly outdated beliefs.

Reflection is the mechanism that prevents knowledge rot — the counterpart of memory poisoning defense (doc 03), but for internal decay rather than external attack.

---

## Five Reflection Processes

### 1. Consistency Check — Do My Beliefs Contradict Each Other?

**The problem:** Knowledge is accumulated over months of interaction.
New observations can contradict existing patterns.
New patterns can conflict with existing concepts.
Without explicit checking, the agent might hold two contradictory beliefs simultaneously:
- Pattern A: "always use UTC timestamps in this database"
- Pattern B: "this API returns local time, use as-is"
Both might be correct in their original context but contradictory when applied together.

**When it runs:** Background tier (during idle time), triggered by:
- New pattern created (check against existing patterns in the same domain)
- Cross-domain consolidation (check against all domains)
- Periodic scheduled check (weekly)

**How it works:**
1. For each domain, retrieve all patterns and concepts
2. Present them to the LLM in pairs or small groups: "are any of these contradictory?"
3. For each contradiction found:
   - Trace both artifacts back to their parent observations (using `parent_artifacts` metadata)
   - Determine which is more recent, more validated, or more trusted
   - Create a candidate UPDATE that resolves the contradiction (conditional rule, scope restriction, or retirement of the weaker one)
   - The candidate enters the admission pipeline + shadow testing

**What MemoryAgentBench (ICLR 2026) showed:** No existing system masters conflict resolution — overwriting outdated facts is the hardest memory competency.
Our consistency check is designed specifically for this gap.

### 2. Validity Check — Is This Generalization Still True?

**The problem:** A pattern that was true 3 months ago may no longer be true.
The database schema changed.
The user's preferences shifted.
The API updated its response format.

Generalizations are provisional (as established in doc 10).
They must be continuously tested against reality.

**When it runs:** Two triggers:
- **On use** (instant tier): when a pattern or concept is retrieved and applied, the task outcome feeds back into its utility score. Successful use refreshes the `last_validated` timestamp. Failed use triggers attribution.
- **On decay** (background tier): when `last_validated` is older than a threshold (configurable per domain, default 14 days), the artifact is flagged for validity review.

**How it works for flagged artifacts:**
1. Retrieve the artifact and its parent observations
2. Retrieve the most recent observations in the same domain
3. Ask the LLM: "given these recent observations, is this generalization still valid?"
4. Three outcomes:
   - **Still valid** — refresh `last_validated`, increase utility score
   - **Needs refinement** — create a candidate UPDATE with the refined version
   - **No longer valid** — create a candidate RETIRE

**Connection to SkillsBench:** Self-generated knowledge provides zero benefit if it is not validated.
The validity check is the mechanism that prevents stale knowledge from dragging down performance.

### 3. Gap Detection — What Should I Know That I Do Not?

**The problem:** The agent works in a domain for months but never learns certain patterns because they never caused a visible error.
The gap is invisible — the agent does not know what it does not know.

**When it runs:** Background tier, triggered by:
- Domain growth (new observations accumulate but no new patterns form)
- Task failure in a domain that should have mature knowledge
- Periodic review (monthly)

**How it works:**
1. Compare the domain's knowledge depth against its observation volume:
   - Many observations (>50) but few patterns (<3) → consolidation is overdue
   - Many patterns (>10) but no concepts → abstraction is overdue
   - Successful tasks that used NO domain knowledge → the domain profile is incomplete
2. For each detected gap, generate a REFLECTION prompt:
   - "Here are 47 observations about the statistics domain. What patterns do you see?"
   - "Here are 12 patterns about coding. Are any of these really the same insight?"
3. Proposed patterns/concepts enter the admission pipeline as candidates

**Connection to Nemori Predict-Calibrate:** Predict-Calibrate detects what is genuinely new in a SINGLE episode.
Gap detection asks a broader question: "given EVERYTHING I know, what am I MISSING?"

### 4. Attribution Trace — Why Did This Fail?

**The problem:** A task failed.
The scorecard says: completion=0, errors=2, stuck_events=1.
But which piece of knowledge caused the failure?

**When it runs:** Fast tier (between turns or after task completion), triggered by:
- Task failure (completion=0)
- User rejection
- High error count
- StuckDetector firing

**How it works** (refined from doc 04 and doc 10):

```
Task failed
  → Which lockfile was active? → current.lock
  → Which composition was used? → deep_research_agent@1.0.0
  → Which blocks within the composition were active?
     → research_context_boundary@0.2.1 ← this is where errors occurred
  → What generalization does that block encode?
     → "compress at 50% for research tasks"
  → Trace to parent observations:
     → 15 past research tasks where 50% compression worked
  → Were those observations representative of THIS task?
     → No — they were all simple queries; this task was complex
  → CANDIDATE: create research_context_boundary@0.3.0
     → conditional: 50% for simple, 80% for complex research
  → Candidate enters admission pipeline → shadow testing
```

**Three attribution levels:**
- **Block-level:** which specific block version failed? (comparison: same composition, different block version)
- **Knowledge-level:** which generalization within the block was wrong? (trace to parent observations)
- **Observation-level:** which observations led to the wrong generalization? (were they representative?)

The fix flows UP the hierarchy: new observation → refined pattern → updated block → tested via shadow.

### 5. Cross-Domain Pattern Detection — Is This the Same Insight?

**The problem:** The statistics domain has a pattern: "always validate input data types before aggregation."
The coding domain has a pattern: "always check argument types before function execution."
These are the same insight at a higher abstraction level — but the agent does not know this because they were learned independently.

**When it runs:** Background tier (during idle), triggered by:
- New pattern created in any domain (compare against patterns in other domains)
- Periodic cross-domain review (weekly)

**How it works:**
1. Embed all patterns across all domains
2. Find cross-domain pairs with high similarity (above threshold)
3. For each high-similarity pair, ask the LLM: "are these the same insight expressed differently?"
4. If yes:
   - Create a shared concept in `knowledge/shared/cross_domain_patterns/`
   - Both domain patterns link to the shared concept as their parent
   - The shared concept is available during retrieval in ALL domains
5. The shared concept enters the admission pipeline as a candidate

**Why this is the rarest and most valuable form of learning:**
Cross-domain transfer is what separates a specialist from a generalist.
A specialist knows the patterns within their domain.
A generalist recognizes that patterns from different domains are instances of the same principle.

In the organizational analogy: this is when the VP realizes that the logistics team's "validate shipment data" process and the engineering team's "validate deployment data" process are both instances of "validate inputs before irreversible operations" — and creates a company-wide policy.

---

## The Reflection Schedule

| Process | Tier | Trigger | Frequency | Cost |
|---|---|---|---|---|
| Consistency check | Background | New pattern + periodic | Weekly + on new pattern | Medium (LLM calls to compare pairs) |
| Validity check | Instant + Background | On use + on decay | Continuous + biweekly | Low (on use) to Medium (review) |
| Gap detection | Background | Observation accumulation + periodic | Monthly | Medium (LLM analysis of domain state) |
| Attribution trace | Fast | Task failure | On every failure | Low (deterministic trace + 1 LLM call) |
| Cross-domain detection | Background | New pattern + periodic | Weekly | High (all-pairs comparison across domains) |

All reflection outputs are CANDIDATES — they enter the admission pipeline (doc 03) and must pass gates + shadow testing before affecting the running system.
Reflection never directly modifies knowledge.
It proposes changes.

---

## How Reflection Connects to Consolidation

Consolidation (from doc 10) creates new knowledge: observations → patterns → concepts.
Reflection EVALUATES existing knowledge: is it consistent? still valid? complete? correct?

They are complementary:
- Consolidation is constructive — it builds the hierarchy upward
- Reflection is corrective — it prunes, refines, and connects

Both run during the background tier.
Both produce candidates that enter the admission pipeline.
Both are essential — consolidation without reflection produces an ever-growing pile of unchecked beliefs.
Reflection without consolidation produces nothing new.

The full cycle:
```
Observations accumulate (ADD)
  → Consolidation creates patterns (CONSOLIDATE)
  → Reflection checks patterns for consistency (CONSISTENCY CHECK)
  → Reflection validates patterns against new observations (VALIDITY CHECK)
  → Reflection detects gaps (GAP DETECTION)
  → Task failure triggers attribution (ATTRIBUTION TRACE)
  → Cross-domain patterns are detected (CROSS-DOMAIN)
  → All corrections are candidates → admission → shadow → promotion/rejection
```

---

## Connection to Existing Docs

| Doc | Connection |
|---|---|
| [03 Evolution and Safety](03-evolution-and-safety.md) | All reflection outputs are candidates that pass through the admission pipeline. Reflection is how the agent applies the admission gates to its OWN existing knowledge, not just to new mutations. |
| [04 Measurement](04-measurement.md) | Attribution trace uses the scorecard and the three-cause model. Utility scores from measurement feed validity checks. |
| [05 Parallel Evaluation](05-parallel-evaluation.md) | Every correction proposed by reflection enters shadow testing. The agent does not change its beliefs without evidence. |
| [10 Continuous Learning](10-continuous-learning.md) | Reflection is a background-tier process. Generalizations are provisional — reflection is what tests them. |
| [11 Memory Architecture](11-memory-architecture.md) | Reflection operates over the Knowledge Store hierarchy. The five operations (ADD, CONSOLIDATE, RETRIEVE, UPDATE, RETIRE) are the outcomes of reflection. |

---

## What We Take from Research

| Component | Source |
|---|---|
| Conflict resolution as core competency | MemoryAgentBench (ICLR 2026) — no system masters this |
| Predict-calibrate for novelty detection | Nemori — extract only what existing knowledge does not predict |
| Validity checking via task feedback | AMV-L utility scores — validated on every access |
| Attribution through artifact hierarchy | Moatless FeedbackGenerator — analyze siblings to guide new attempts |
| Cross-domain pattern detection | A-MEM link evolution — neighbor memories update when new ones arrive |
| Self-generated knowledge needs validation | SkillsBench — zero benefit without curation |
| Experience-following property | Xiong et al. — agents mimic retrieved memories, errors propagate |

## What Is New

No existing system has:
1. Explicit consistency checking across a knowledge hierarchy
2. Validity checking with temporal decay and on-use feedback
3. Gap detection comparing observation volume against knowledge depth
4. Cross-domain pattern detection that forms shared concepts
5. ALL reflection outputs treated as candidates requiring admission + shadow testing
