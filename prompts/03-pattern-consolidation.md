# Prompt: Pattern Consolidation

## When Used

When a domain's observation count exceeds the capacity limit (default 20).
Runs with Haiku during background idle.

## Prompt

```
You are a knowledge analyst. You have {count} observations from the "{domain}" domain. The capacity limit is {limit}. You need to consolidate these into fewer, more general patterns.

OBSERVATIONS:
{observations_yaml}

Your task:
1. Identify groups of observations that describe the same underlying pattern
2. For each group, write ONE generalized statement that captures the pattern
3. The generalization must be MORE useful than any individual observation — it should apply to future similar situations, not just the specific cases observed

Rules:
- Each pattern must be self-contained and actionable
- Each pattern must cover at least 2 observations (no single-observation patterns)
- Observations that do not fit any group should be kept as-is (they are not ready for consolidation)
- The total count of patterns + remaining observations must be under {limit}

Return JSON:
{
  "patterns": [
    {
      "content": "generalized actionable statement",
      "source_observation_ids": ["obs-001", "obs-002", "obs-003"],
      "confidence": 0.0-1.0,
      "tags": ["tag1", "tag2"]
    }
  ],
  "kept_observations": ["obs-007", "obs-012"],
  "discarded_observations": ["obs-004"]
}

kept_observations: IDs of observations that should stay as-is (not enough evidence to generalize).
discarded_observations: IDs of observations that are subsumed by a pattern and can be retired.
```

## Notes

- Runs only when capacity pressure exists — no consolidation when there is room
- The source_observation_ids create the parent→child link in the hierarchy for attribution tracing
- Temperature: 0.3
- discarded_observations get their utility scores set to zero, not physically deleted (for rollback)
