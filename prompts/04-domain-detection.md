# Prompt: Domain Detection

## When Used

After each user message (fast tier). Classifies the current task into a domain.
Runs with Haiku (single fast call).

## Prompt

```
Classify this user request into one of the existing domains, or suggest a new domain.

EXISTING DOMAINS:
{domain_list_with_descriptions}

USER REQUEST:
{user_message}

RECENT CONTEXT (last 3 messages):
{recent_context}

Return JSON:
{
  "domain": "existing-domain-name" | "NEW",
  "new_domain_name": "name-if-new",
  "new_domain_description": "one-sentence description if new",
  "confidence": 0.0-1.0
}

Rules:
- Use an existing domain if the request clearly fits (confidence > 0.7)
- Suggest NEW only if the request does not fit any existing domain
- Domain names are lowercase-hyphenated: "file-organization", "data-cleanup", "scripting"
- If unsure, use the most general existing domain rather than creating a new one
```

## When a New Domain Is Created

A new domain is NOT created on the first mention.
It requires stability: 3+ tasks classified as the same new domain before a DomainProfile is created.
Until then, observations are stored under "uncategorized".

## Notes

- Temperature: 0.0 (deterministic classification)
- The domain_list includes each domain's description from profile.yaml
- If no domains exist yet (cold start), all domains start as NEW suggestions
- The confidence score helps the system decide whether to load domain-specific blocks into working memory
