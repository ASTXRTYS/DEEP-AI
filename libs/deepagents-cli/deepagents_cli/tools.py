"""Custom tools for the CLI agent."""

import os
from typing import Any, Literal

import requests
from tavily import TavilyClient

# Initialize Tavily client if API key is available
tavily_client = (
    TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
    if os.environ.get("TAVILY_API_KEY")
    else None
)


def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] = None,
    data: str | dict = None,
    params: dict[str, str] = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Make HTTP requests to REST APIs and JSON endpoints.

    **IMPORTANT**: This tool is for API calls that return JSON data, NOT for:
    - Web scraping or fetching HTML pages (use web_search instead)
    - Researching documentation (use web_search instead)
    - General web browsing (use web_search instead)

    Use this ONLY for programmatic API endpoints like:
    - REST APIs (e.g., https://api.github.com/repos/...)
    - JSON endpoints
    - Webhook calls

    Args:
        url: Target API endpoint URL
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        headers: HTTP headers to include
        data: Request body data (string or dict)
        params: URL query parameters
        timeout: Request timeout in seconds

    Returns:
        Dictionary with response data including status, headers, and content
    """
    try:
        kwargs = {"url": url, "method": method.upper(), "timeout": timeout}

        if headers:
            kwargs["headers"] = headers
        if params:
            kwargs["params"] = params
        if data:
            if isinstance(data, dict):
                kwargs["json"] = data
            else:
                kwargs["data"] = data

        response = requests.request(**kwargs)

        try:
            content = response.json()
        except:
            content = response.text
            # Truncate large HTML responses to prevent context overflow
            # If response is >50KB, it's likely HTML and should use web_search instead
            if len(content) > 50000:
                content = (
                    content[:50000]
                    + f"\n\n... [Response truncated - {len(content):,} chars total. "
                    + "NOTE: For web pages and documentation, use web_search tool instead of http_request]"
                )

        return {
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": content,
            "url": response.url,
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request timed out after {timeout} seconds",
            "url": url,
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request error: {e!s}",
            "url": url,
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Error making request: {e!s}",
            "url": url,
        }


def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Search the web using Tavily for current information and documentation.

    This tool searches the web and returns relevant results. After receiving results,
    you MUST synthesize the information into a natural, helpful response for the user.

    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return (default: 5)
        topic: Search topic type - "general" for most queries, "news" for current events
        include_raw_content: Include full page content (warning: uses more tokens)

    Returns:
        Dictionary containing:
        - results: List of search results, each with:
            - title: Page title
            - url: Page URL
            - content: Relevant excerpt from the page
            - score: Relevance score (0-1)
        - query: The original search query

    IMPORTANT: After using this tool:
    1. Read through the 'content' field of each result
    2. Extract relevant information that answers the user's question
    3. Synthesize this into a clear, natural language response
    4. Cite sources by mentioning the page titles or URLs
    5. NEVER show the raw JSON to the user - always provide a formatted response
    """
    if tavily_client is None:
        return {
            "error": "Tavily API key not configured. Please set TAVILY_API_KEY environment variable.",
            "query": query,
        }

    try:
        search_docs = tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic,
        )
        return search_docs
    except Exception as e:
        return {"error": f"Web search error: {e!s}", "query": query}
