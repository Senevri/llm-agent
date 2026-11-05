import httpx2
import asyncio
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse
import trafilatura  # Better than BeautifulSoup for article extraction
from ddgs import DDGS
import time
from functools import lru_cache

@dataclass
class WebResult:
    url: str
    title: str
    snippet: str
    content: Optional[str] = None
    score: float = 0.0

class WebSearchTool:
    def __init__(self, max_results: int = 5, fetch_content: bool = True):
        self.max_results = max_results
        self.fetch_content = fetch_content
        self.cache = {}
        self.client = httpx2.AsyncClient(timeout=10.0)

    async def search(self, query: str, fetch_content: bool = None) -> str:
        """Main entry point for agent tool calls."""
        should_fetch = fetch_content if fetch_content is not None else self.fetch_content

        # 1. Search
        results = await self._search_duckduckgo(query)

        if not results:
            return "No search results found."

        # 2. Fetch content (if enabled)
        if should_fetch:
            results = await self._fetch_and_extract(results)

        # 3. Format for agent (token-efficient)
        return self._format_results(results, query)

    async def _search_duckduckgo(self, query: str) -> List[WebResult]:
        """DuckDuckGo search with fallback."""
        try:
            # Run sync DDGS in thread pool
            loop = asyncio.get_event_loop()
            with DDGS() as ddgs:
                results = await loop.run_in_executor(
                    None,
                    lambda: list(ddgs.text(query, max_results=self.max_results * 2))
                )

            return [
                WebResult(
                    url=r['href'],
                    title=r['title'],
                    snippet=r['body'],
                    score=1.0 - (i * 0.1)  # Simple rank decay
                )
                for i, r in enumerate(results)
            ]
        except Exception as e:
            return []

    async def _fetch_and_extract(self, results: List[WebResult]) -> List[WebResult]:
        """Fetch and extract content from URLs."""
        tasks = [self._fetch_url(r) for r in results]
        fetched = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out failures
        valid = [r for r in fetched if isinstance(r, WebResult) and r.content]

        # Sort by content length (prefer substantial content)
        valid.sort(key=lambda r: len(r.content or ""), reverse=True)

        return valid[:self.max_results]

    async def _fetch_url(self, result: WebResult) -> WebResult:
        """Fetch single URL with caching."""
        if result.url in self.cache:
            result.content = self.cache[result.url]
            return result

        try:
            response = await self.client.get(
                result.url,
                headers={'User-Agent': 'Mozilla/5.0 (Agent Search Bot)'},
                follow_redirects=True
            )
            response.raise_for_status()

            # Extract main content (trafilatura is much better than BS4 for articles)
            content = trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=True,
                no_fallback=False
            )

            if content:
                # Truncate to avoid context bloat
                result.content = content[:8000]
                self.cache[result.url] = result.content

            return result
        except Exception:
            return result

    def _format_results(self, results: List[WebResult], query: str) -> str:
        """Format results for agent consumption."""
        if not results:
            return "No relevant content found."

        formatted = [f"# Search Results for: {query}\n"]

        for i, r in enumerate(results, 1):
            formatted.append(f"\n## Result {i}: {r.title}")
            formatted.append(f"URL: {r.url}")

            if r.content:
                # Include extracted content
                formatted.append(f"\n{r.content[:4000]}")
            else:
                # Fallback to snippet
                formatted.append(f"\nSnippet: {r.snippet}")

        return "\n".join(formatted)

# --- Alternative: Brave Search API (more reliable, requires API key) ---

class BraveSearchTool(WebSearchTool):
    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    async def _search_duckduckgo(self, query: str) -> List[WebResult]:
        """Override with Brave Search API."""
        try:
            response = await self.client.get(
                self.base_url,
                headers={
                    'Accept': 'application/json',
                    'X-Subscription-Token': self.api_key
                },
                params={'q': query, 'count': self.max_results * 2}
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for i, r in enumerate(data.get('web', {}).get('results', [])):
                results.append(WebResult(
                    url=r['url'],
                    title=r['title'],
                    snippet=r.get('description', ''),
                    score=1.0 - (i * 0.1)
                ))

            return results
        except Exception as e:
            return []

class AsyncRateLimitedWebSearch(WebSearchTool):
    def __init__(self, min_delay: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.min_delay = min_delay
        self.last_request = 0

    async def _fetch_url(self, result: WebResult) -> WebResult:
        elapsed = time.time() - self.last_request
        if elapsed < self.min_delay:
            await asyncio.sleep(self.min_delay - elapsed)

        self.last_request = time.time()
        return await super()._fetch_url(result)

# --- Integration with your tool registry ---

def create_async_web_search_tool(api_key: Optional[str] = None) -> Dict:
    """Create tool definition for agent registry."""
    if api_key:
        searcher = BraveSearchTool(api_key=api_key)
    else:
        searcher = RateLimitedWebSearch()

    async def web_search(query: str, fetch_content: bool = True) -> str:
        return await searcher.search(query, fetch_content)

    return {
        "name": "web_search",
        "description": "Search the web and optionally fetch full article content. Use for current information, documentation, or research.",
        "function": web_search,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "fetch_content": {
                    "type": "boolean",
                    "description": "Whether to fetch and extract full article content (default: true)",
                    "default": True
                }
            },
            "required": ["query"]
        }
    }


import asyncio
import time
from typing import Optional, Dict, List
from dataclasses import dataclass

# (Assuming WebResult, WebSearchTool, BraveSearchTool, and trafilatura are defined above as before)

class RateLimitedWebSearch(WebSearchTool):
    def __init__(self, min_delay: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.min_delay = min_delay
        self.last_request = 0.0

    async def _fetch_url(self, result: 'WebResult') -> 'WebResult':
        elapsed = time.time() - self.last_request
        if elapsed < self.min_delay:
            await asyncio.sleep(self.min_delay - elapsed)

        self.last_request = time.time()
        return await super()._fetch_url(result)


def create_web_search_tool(api_key: Optional[str] = None, min_delay: float = 1.0) -> Dict:
    """Create tool definition for agent registry."""
    if api_key:
        # Note: If using Brave, ensure BraveSearchTool inherits from RateLimitedWebSearch
        # or handles min_delay in its __init__
        searcher = BraveSearchTool(api_key=api_key, min_delay=min_delay)
    else:
        searcher = RateLimitedWebSearch(min_delay=min_delay)

    # FIX: Added max_results to the signature
    async def web_search(query: str, max_results: int = 5, fetch_content: bool = True) -> str:
        return await searcher.search(query)

    return {
        "name": "web_search",
        "description": "Search the web and optionally fetch full article content. Use for current information, documentation, or research.",
        "function": web_search,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5)"
                },
                "fetch_content": {
                    "type": "boolean",
                    "description": "Whether to fetch and extract full article content (default: true)",
                    "default": True
                }
            },
            "required": ["query"]
        }
    }

def search_internet_sync(query: str, max_results: int = 5, fetch_content: bool = True) -> str:
    """Synchronous wrapper for the async web_search function."""
    tool_def = create_web_search_tool()
    web_search = tool_def.get("function")

    if not web_search:
        raise RuntimeError("Failed to create web_search tool.")

    try:
        # FIX: Pass arguments by keyword to perfectly match the async def signature
        return asyncio.run(web_search(query=query, max_results=max_results, fetch_content=fetch_content))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(web_search(query=query, max_results=max_results, fetch_content=fetch_content))
        raise

if __name__ == "__main__":
    result = search_internet_sync("chatGPT")
    print(result)
