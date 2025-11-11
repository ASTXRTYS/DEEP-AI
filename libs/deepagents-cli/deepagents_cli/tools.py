"""Custom tools for the CLI agent."""

import os
from typing import Any, Literal

import requests
from langchain_core.tools import tool
from tavily import TavilyClient

# Initialize Tavily client if API key is available
tavily_client = (
    TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
    if os.environ.get("TAVILY_API_KEY")
    else None
)


@tool(
    parse_docstring=True,
    response_format="content_and_artifact",
)
def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: str | dict | None = None,
    params: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[str, dict[str, Any]]:
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
        Tuple of (content, artifact):
        - content: Concise summary message for the LLM
        - artifact: Full response dictionary with status, headers, and content
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

        result = {
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": content,
            "url": response.url,
        }

        # Generate concise content for LLM
        if result["success"]:
            content_msg = f"✓ HTTP {method.upper()} request to {result['url']} succeeded (status: {result['status_code']})"
        else:
            content_msg = f"✗ HTTP {method.upper()} request to {result['url']} failed (status: {result['status_code']})"

        return content_msg, result

    except requests.exceptions.Timeout:
        error_result = {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request timed out after {timeout} seconds",
            "url": url,
        }
        error_msg = f"✗ HTTP request to {url} timed out after {timeout}s"
        return error_msg, error_result
    except requests.exceptions.RequestException as e:
        error_result = {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request error: {e!s}",
            "url": url,
        }
        error_msg = f"✗ HTTP request to {url} failed: {type(e).__name__}"
        return error_msg, error_result
    except Exception as e:
        error_result = {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Error making request: {e!s}",
            "url": url,
        }
        error_msg = f"✗ HTTP request to {url} failed unexpectedly"
        return error_msg, error_result


@tool(
    parse_docstring=True,
    response_format="content_and_artifact",
)
def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
) -> tuple[str, dict]:
    """Search the web using Tavily for current information and documentation.

    This tool searches the web and returns relevant results. After receiving results,
    you MUST synthesize the information into a natural, helpful response for the user.

    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return (default: 5)
        topic: Search topic type - "general" for most queries, "news" for current events
        include_raw_content: Include full page content (warning: uses more tokens)

    Returns:
        Tuple of (content, artifact):
        - content: Concise summary of search results for the LLM
        - artifact: Full Tavily response dictionary containing:
            - results: List of search results with title, url, content, score
            - query: The original search query

    IMPORTANT: After using this tool:
    1. Read through the 'content' field of each result
    2. Extract relevant information that answers the user's question
    3. Synthesize this into a clear, natural language response
    4. Cite sources by mentioning the page titles or URLs
    5. NEVER show the raw JSON to the user - always provide a formatted response
    """
    if tavily_client is None:
        error_result = {
            "error": "Tavily API key not configured. Please set TAVILY_API_KEY environment variable.",
            "query": query,
        }
        error_msg = "✗ Web search unavailable - Tavily API key not configured"
        return error_msg, error_result

    try:
        search_results = tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic,
        )

        # Generate concise content for LLM
        num_results = len(search_results.get("results", []))
        content_msg = f"✓ Found {num_results} web search results for: {query}"

        return content_msg, search_results
    except Exception as e:
        error_result = {"error": f"Web search error: {e!s}", "query": query}
        error_msg = f"✗ Web search failed for query: {query}"
        return error_msg, error_result


# Configure tools with tags and metadata for LangSmith observability
http_request.tags = ["external_api", "http", "requires_approval"]
http_request.metadata = {"workflow": "hitl", "risk_level": "medium", "api_type": "rest"}

if tavily_client is not None:
    web_search.tags = ["external_api", "web_search", "tavily", "requires_approval"]
    web_search.metadata = {"workflow": "hitl", "risk_level": "low", "api_provider": "tavily"}
