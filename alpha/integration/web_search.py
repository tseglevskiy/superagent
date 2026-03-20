"""Web search via local SearXNG instance.

Integration module providing web search through a locally-running
SearXNG metasearch engine (DuckDuckGo, Brave, Bing).

Endpoint: http://localhost:8080/search?q=QUERY&format=json

Error convention: public functions return error strings (never raise)
so the agent can handle failures gracefully in sandbox code.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SEARXNG_BASE = os.environ.get("SEARXNG_BASE", "http://localhost:8080")
DEFAULT_TIMEOUT = 15  # seconds
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB safety cap on response size


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _search_raw(
    query: str,
    *,
    categories: str = "general",
    engines: str | None = None,
    language: str = "en",
    pageno: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Call SearXNG JSON API and return the parsed response.

    Raises:
        ConnectionError: SearXNG is unreachable or refused the connection.
        RuntimeError: SearXNG returned an error status or unparseable response.
    """
    params: dict[str, str] = {
        "q": query,
        "format": "json",
        "categories": categories,
        "language": language,
        "pageno": str(pageno),
    }
    if engines:
        params["engines"] = engines

    url = f"{SEARXNG_BASE}/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"SearXNG returned HTTP {e.code}: {e.reason}"
        ) from e
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"SearXNG unreachable at {SEARXNG_BASE}: {e.reason}"
        ) from e

    try:
        body = resp.read(MAX_RESPONSE_BYTES)
    finally:
        resp.close()

    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"SearXNG returned invalid JSON: {e}") from e


def _validate_params(query: str, num_results: int, pageno: int) -> str | None:
    """Validate common parameters. Returns error string or None."""
    if not query or not query.strip():
        return "Error: query must be a non-empty string"
    if num_results < 1:
        return f"Error: num_results must be >= 1, got {num_results}"
    if pageno < 1:
        return f"Error: pageno must be >= 1, got {pageno}"
    return None


def _safe_search(
    query: str,
    *,
    num_results: int = 10,
    categories: str = "general",
    engines: str | None = None,
    language: str = "en",
    pageno: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any] | str:
    """Validate params, call SearXNG, return parsed dict or error string."""
    err = _validate_params(query, num_results, pageno)
    if err:
        return err
    try:
        data = _search_raw(
            query,
            categories=categories,
            engines=engines,
            language=language,
            pageno=pageno,
            timeout=timeout,
        )
    except ConnectionError as e:
        log.warning("web search connection error: %s", e)
        return f"Error: {e}"
    except RuntimeError as e:
        log.warning("web search runtime error: %s", e)
        return f"Error: {e}"
    except Exception as e:
        log.exception("web search unexpected error")
        return f"Error: web search failed: {e}"
    return data


# ---------------------------------------------------------------------------
# Public API (injected into sandbox)
# ---------------------------------------------------------------------------


def web_search(
    query: str,
    *,
    num_results: int = 10,
    categories: str = "general",
    engines: str | None = None,
    language: str = "en",
    pageno: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Search the web via local SearXNG. Returns formatted results.

    Powered by a local SearXNG instance aggregating DuckDuckGo, Brave, and Bing.
    Returns "Error: ..." string on failure (never raises).

    Args:
        query:       Search query string (must be non-empty).
        num_results: Max results to return (>= 1). Default 10.
        categories:  Comma-separated: general, news, images, videos, files. Default "general".
        engines:     Override default engines. Comma-separated: duckduckgo, brave, bing.
        language:    Language code. Default "en".
        pageno:      Page number for pagination (>= 1). Default 1.
        timeout:     Request timeout in seconds. Default 15.

    Returns:
        Formatted string with title, URL, and snippet for each result,
        or "Error: ..." string if the search failed.

    Examples::

        print(web_search("python asyncio tutorial"))
        print(web_search("rust memory safety", num_results=5))
        print(web_search("latest AI news", categories="news"))
        print(web_search("site:github.com agentic loop"))
    """
    data = _safe_search(
        query,
        num_results=num_results,
        categories=categories,
        engines=engines,
        language=language,
        pageno=pageno,
        timeout=timeout,
    )
    if isinstance(data, str):
        return data  # error string

    log.debug("web_search query=%r results=%d", query, len(data.get("results", [])))

    results = data.get("results", [])
    if not results:
        return f"No results for: {query}"

    results = results[:num_results]
    parts = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = r.get("content", "")
        engine = ", ".join(r.get("engines", []))
        line = f"{i}. {title}\n   {url}\n   {snippet}"
        if engine:
            line += f"\n   [via {engine}]"
        parts.append(line)

    header = f"Web search: {query} ({len(results)} results)"
    return header + "\n\n" + "\n\n".join(parts)


def web_search_json(
    query: str,
    *,
    num_results: int = 10,
    categories: str = "general",
    engines: str | None = None,
    language: str = "en",
    pageno: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]] | str:
    """Search the web and return raw result dicts for programmatic use.

    Each dict has keys: title, url, content, engines, score, category, published.
    Returns "Error: ..." string on failure (never raises).

    Args:
        query:       Search query string (must be non-empty).
        num_results: Max results to return (>= 1). Default 10.
        categories:  Comma-separated: general, news, images, videos, files.
        engines:     Override engines. Comma-separated: duckduckgo, brave, bing.
        language:    Language code. Default "en".
        pageno:      Page number (>= 1). Default 1.
        timeout:     Request timeout in seconds. Default 15.

    Returns:
        List of result dicts, or "Error: ..." string if the search failed.

    Examples::

        results = web_search_json("LLM agent architectures")
        if isinstance(results, str):
            print(results)  # error
        else:
            for r in results:
                print(r["title"], r["url"])
    """
    data = _safe_search(
        query,
        num_results=num_results,
        categories=categories,
        engines=engines,
        language=language,
        pageno=pageno,
        timeout=timeout,
    )
    if isinstance(data, str):
        return data  # error string

    log.debug("web_search_json query=%r results=%d", query, len(data.get("results", [])))

    results = data.get("results", [])[:num_results]
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "engines": r.get("engines", []),
            "score": r.get("score", 0),
            "category": r.get("category", ""),
            "published": r.get("publishedDate", ""),
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
## Web Search

Requires a local SearXNG instance (aggregates DuckDuckGo, Brave, Bing).
On failure both functions return "Error: ..." strings (never raise).

web_search(query, ...)                   — Search the web. Returns formatted string with title, URL, snippet per result.
web_search_json(query, ...)              — Same search, returns list[dict] for programmatic use (or "Error: ..." string on failure).

Both support: num_results (default 10), categories ("general", "news", "images", "videos", "files"),
engines (override: "duckduckgo", "brave", "bing"), language (default "en"), pageno (default 1),
timeout (default 15s).

Examples:
  print(web_search("python asyncio tutorial"))
  print(web_search("latest LLM papers", categories="news", num_results=5))
  results = web_search_json("agentic AI frameworks")
  if isinstance(results, str):
      print(results)  # error
  else:
      for r in results: print(r["title"], r["url"])
"""


# ---------------------------------------------------------------------------
# Integration registration
# ---------------------------------------------------------------------------


def register(workspace: Path) -> dict:
    """Integration protocol: return metadata and functions."""
    return {
        "name": "web_search",
        "functions": {
            "web_search": web_search,
            "web_search_json": web_search_json,
        },
        "system_prompt": SYSTEM_PROMPT,
    }
