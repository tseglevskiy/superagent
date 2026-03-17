# Prompt: Episode Segmentation

## When Used

After a conversation reaches the buffer threshold (default 10 messages).
Runs with Haiku (cheap, fast).

## Input

A numbered transcript of recent messages.

## Prompt

```
You are a conversation analyst. Your task is to group the following numbered messages into topically coherent episodes.

An episode is a set of messages about the same topic or task. Messages within an episode may not be consecutive — users frequently interleave topics (ask about files, switch to a script question, return to files).

Group by TOPICAL COHERENCE, not by chronological order. Within each group, preserve the original message order.

Split when you detect:
- Topic change (different subjects, events, or tasks)
- Intent transition (from asking to commanding, from browsing to editing)
- Temporal gap (>5 minutes between messages)
- Structural signal ("by the way", "another thing", "also")

When in doubt, split. Target 3-10 messages per episode.

MESSAGES:
{numbered_transcript}

Return JSON:
{
  "episodes": [
    {
      "indices": [1, 2, 5, 8],
      "topic": "short description of what this episode is about",
      "domain_hint": "file-organization" | "data-cleanup" | "scripting" | "content-search" | "other"
    }
  ]
}
```

## Notes

- Inspired by Nemori's BatchSegmenter with non-consecutive index groups
- domain_hint is advisory — the domain detection system uses it as one signal among others
- Temperature: 0.2 for consistency
- The numbered format lets the LLM reference specific messages without quoting them
