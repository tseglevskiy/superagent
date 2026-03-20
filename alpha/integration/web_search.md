# web_search.py - Design Report

## What This Is

A Python integration module that gives the agent web search capabilities through a locally-running SearXNG instance. SearXNG is a privacy-respecting metasearch engine that aggregates results from DuckDuckGo, Brave, and Bing.

Two functions are injected into the agent's sandbox namespace:
- `web_search(query)` — returns formatted text (for reading and reasoning)
- `web_search_json(query)` — returns `list[dict]` (for programmatic filtering and extraction)

The agent writes Python code that calls these functions. The HTTP call to SearXNG happens in the host Python process, outside the sandbox — the agent never touches networking directly.

## Why Local SearXNG

Using a local metasearch instance instead of calling search APIs directly:

- **No API keys** — DuckDuckGo, Brave, and Bing results without managing credentials for each
- **Single endpoint** — one local URL aggregates multiple engines; adding or removing engines is a config change, not a code change
- **No rate limits** — local instance, no quotas
- **Privacy** — queries stay on the local machine, never routed through third-party aggregators
- **Deterministic infrastructure** — the agent assumes SearXNG is running at `localhost:8080`; if it's not, the function raises `ConnectionError` immediately rather than degrading silently

The trade-off: requires a Docker container running alongside the agent. This is an infrastructure concern, not the agent's — the integration raises on failure and does not attempt recovery.

## How It Works

### Architecture

```
Agent sandbox (smolagents)
  │
  │  web_search("query")     ← Python function call
  │
  ▼
Host Python (integration module)
  │
  │  urllib.request.urlopen() ← stdlib HTTP, no dependencies
  │
  ▼
SearXNG container (localhost:8080)
  │
  │  Fans out to DuckDuckGo, Brave, Bing
  │
  ▼
Search results (JSON)
```

### Request flow

1. Agent calls `web_search("query")` or `web_search_json("query")` in python_exec
2. The function (running in host Python) builds a URL: `http://localhost:8080/search?q=query&format=json`
3. `urllib.request.urlopen()` sends the request with a 15-second timeout
4. SearXNG fans out to its configured engines, merges and ranks results
5. The function parses the JSON response and returns formatted text or structured dicts

### Error handling

No fallbacks, no retries, no silent degradation. If something is wrong, the agent gets an exception:

- **Empty/blank query** → `ValueError("query must be a non-empty string")`
- **Bad parameters** → `ValueError` (num_results < 1, pageno < 1)
- **SearXNG not running** → `ConnectionError("SearXNG unreachable at http://localhost:8080: ...")`
- **Timeout** → `ConnectionError` (urllib wraps timeouts in `URLError`)
- **SearXNG error response** → `RuntimeError("SearXNG returned HTTP 500: ...")` (HTTPError handled distinctly from connection failures)
- **Invalid JSON response** → `RuntimeError("SearXNG returned invalid JSON: ...")`

All exceptions use `raise ... from e` to preserve the original traceback chain. The response body is read with a 5 MB safety cap and the HTTP connection is always closed via `try/finally`.

The agent sees the traceback in its python_exec output and can decide what to do — retry, skip, or tell the user.

## API Reference

### `web_search(query, **kwargs) -> str`

Returns a formatted multi-line string:

```
Web search: python asyncio tutorial (10 results)

1. Python asyncio — Complete Guide
   https://example.com/asyncio-guide
   A comprehensive tutorial covering async/await, event loops, and tasks...
   [via duckduckgo, brave]

2. ...
```

### `web_search_json(query, **kwargs) -> list[dict]`

Returns a list of result dicts, each with:

| Key         | Type       | Description                          |
|-------------|------------|--------------------------------------|
| `title`     | str        | Result title                         |
| `url`       | str        | Result URL                           |
| `content`   | str        | Snippet / description                |
| `engines`   | list[str]  | Which engines returned this result   |
| `score`     | float      | SearXNG relevance score              |
| `category`  | str        | Result category                      |
| `published` | str        | Publication date (if available)      |

### Shared parameters

| Parameter      | Type | Default     | Description                                              |
|----------------|------|-------------|----------------------------------------------------------|
| `query`        | str  | (required)  | Search query                                             |
| `num_results`  | int  | 10          | Max results to return                                    |
| `categories`   | str  | `"general"` | Comma-separated: general, news, images, videos, files    |
| `engines`      | str  | None        | Override engines: duckduckgo, brave, bing                |
| `language`     | str  | `"en"`      | Language code                                            |
| `pageno`       | int  | 1           | Page number for pagination                               |
| `timeout`      | int  | 15          | Request timeout in seconds                               |

## Design Decisions

### 1. Two functions, not one

`web_search` returns pre-formatted text — the agent can print it and reason about the results immediately without parsing. `web_search_json` returns structured data — the agent can filter by engine, sort by score, extract URLs into a list, or iterate programmatically.

Most searches are "look something up and tell me about it" — formatted text is the right default. But research workflows need structured access: "search for X, take the top 3 URLs, fetch and compare them." Having both avoids forcing the agent to parse formatted text or format raw dicts.

### 2. stdlib only (urllib, not requests)

The integration uses `urllib.request` instead of `requests` or `httpx`. This adds zero dependencies beyond what Python ships with. The environment.yml only installs openai, ollama, pyyaml, tiktoken, and smolagents — adding requests just for one HTTP GET would be wasteful.

The trade-off: urllib's API is more verbose than requests. But `_search_raw()` encapsulates all of it in one place — the public functions never touch urllib directly.

### 3. Raise on failure, never degrade

Both functions raise exceptions instead of returning error strings or empty lists. This is deliberate:

- The agent sees the exception in its python_exec traceback and can make an informed decision
- Silent degradation (returning `[]`) would cause the agent to conclude "no results exist" and give the user a wrong answer
- Error strings mixed into the return type (`str` that might be an error or might be results) force the agent to parse defensively

Three exception types, each with a distinct meaning: `ValueError` for bad input (empty query, invalid parameters), `ConnectionError` for infrastructure problems (SearXNG down, timeout), `RuntimeError` for server-side issues (HTTP errors, invalid JSON). All use `raise ... from e` to preserve the original cause.

### 4. No caching, no state

The integration is stateless — no `cleanup_step`, no `reset_session`, no result cache. Every call hits SearXNG, which hits the upstream engines.

This is the right starting point. Caching search results introduces staleness (news queries, rapidly changing topics) and complexity (cache invalidation, TTL, memory pressure). If caching becomes necessary, it belongs in SearXNG's own configuration, not in this integration.

### 5. Hardcoded localhost:8080

The SearXNG URL is a module constant, not configurable via environment variables or config files. This is intentional for the current setup where SearXNG always runs locally on the same machine.

If the deployment model changes (remote SearXNG, multiple instances), this becomes a one-line change to read from `os.environ` or the config system.
