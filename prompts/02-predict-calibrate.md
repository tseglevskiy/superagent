# Prompt: Predict-Calibrate Knowledge Extraction

## When Used

After an episode is created. Two LLM calls: one to predict, one to extract the delta.
Runs with Haiku.

## Call 1: Prediction

Given the episode topic and existing knowledge, predict what the episode should contain.

```
You have the following knowledge about the topic "{episode_topic}" in the "{domain}" domain:

EXISTING KNOWLEDGE:
{existing_knowledge_statements}

Based on this existing knowledge, predict what a conversation about "{episode_topic}" would typically contain. Write a short paragraph describing the expected content, key facts, and likely outcomes.

If you have no existing knowledge on this topic, respond with: "No prior knowledge."
```

## Call 2: Calibration (Delta Extraction)

Compare the prediction against the actual conversation. Extract ONLY what is genuinely new.

```
You predicted that a conversation about "{episode_topic}" would contain:

PREDICTION:
{prediction}

Here is what the conversation ACTUALLY contained:

ORIGINAL MESSAGES:
{episode_messages}

Extract ONLY the valuable knowledge that exists in the original messages but is MISSING or DIFFERENT from the prediction. Do not extract information that your prediction already covered.

For each piece of new knowledge, apply these tests:
- PERSISTENCE: Will this still be true in 6 months?
- SPECIFICITY: Does it contain concrete, searchable information?
- UTILITY: Can this help with future similar tasks?
- INDEPENDENCE: Can it be understood without the conversation context?

HIGH VALUE: user preferences, workspace structure, file organization patterns, tool preferences, recurring task patterns, specific commands that worked, error patterns and their solutions.

LOW VALUE (skip): temporary emotions, acknowledgments, vague statements, information already in the prediction.

Return JSON:
{
  "observations": [
    {
      "content": "self-contained factual statement",
      "confidence": 0.0-1.0,
      "tags": ["tag1", "tag2"]
    }
  ],
  "prediction_was_accurate": true | false,
  "genuinely_new_count": N
}

If the prediction covered everything, return an empty observations list.
```

## Cold Start Path

When no existing knowledge exists (prediction response is "No prior knowledge"), skip Call 1 and go directly to extraction using the same quality filters:

```
Extract high-value knowledge from this conversation about "{episode_topic}":

MESSAGES:
{episode_messages}

Apply these tests to each candidate:
- PERSISTENCE: Will this still be true in 6 months?
- SPECIFICITY: Does it contain concrete, searchable information?
- UTILITY: Can this help with future similar tasks?
- INDEPENDENCE: Can it be understood without the conversation context?

Return JSON:
{
  "observations": [
    {
      "content": "self-contained factual statement",
      "confidence": 0.0-1.0,
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

## Notes

- Inspired by Nemori's PredictionCorrectionEngine
- The prediction step is what prevents indiscriminate accumulation — only genuinely new knowledge passes through
- confidence scores start at the LLM's assessment and decay over time via utility scoring
- Temperature: 0.3 for prediction, 0.2 for extraction
