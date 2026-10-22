import logging
from ddgs import DDGS

logger = logging.getLogger("InternetTools")

def search_internet(query: str, max_results: int = 5) -> str:
    """
    Perform a simple internet search using DuckDuckGo.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return.

    Returns:
        A string containing the search results (titles and snippets).
    """
    logger.info(f"Searching internet for: {query}")
    try:
        with DDGS() as ddgs:
            # Use list() to force execution and catch exceptions
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No results found for the query."

            formatted_results = []
            for i, result in enumerate(results, 1):
                formatted_results.append(f"{i}. {result['title']}\n   Snippet: {result['body']}\n   URL: {result['href']}\n")

            return "\n".join(formatted_results)
    except Exception as e:
        # DuckDuckGo search can raise exceptions for 'no results' in some versions/cases
        if "No results found" in str(e):
            return "No results found for the query."
        logger.error(f"Internet search error: {str(e)}")
        return f"Error performing internet search: {str(e)}"

# Tool definition for the LLM
internet_tool_definition = {
    "type": "function",
    "function": {
        "name": "search_internet",
        "description": "Perform a simple internet search to get information about current events, weather, or specific topics.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to use for the internet search."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Defaults to 5."
                }
            },
            "required": ["query"]
        }
    }
}

# Mapping for tool execution
INTERNET_TOOL_MAP = {
    "search_internet": search_internet
}
