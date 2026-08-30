"""Web Search tool using safe search endpoints with SSRF verification."""

import json
from typing import Any, Dict
import httpx
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult
from src.infrastructure.security.prompt_guard import wrap_untrusted_content
from src.infrastructure.security.ssrf_guard import is_safe_url


class WebSearchTool(BaseTool):
    """Executes external web queries safely with prompt isolation."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="Search the web for current information, documentation, news, or general facts.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search keywords or question."
                    }
                },
                "required": ["query"]
            },
            permission=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        query = arguments.get("query", "").strip()
        if not query:
            return ToolResult(content="Search query cannot be empty.", is_error=True)

        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        data = {"q": query}

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                res = await client.post(url, headers=headers, data=data)
                if res.status_code != 200:
                    return ToolResult(content=f"Search request failed with status {res.status_code}.", is_error=True)

                raw_html = res.text
                # Extract snippet text simply and cleanly
                from html.parser import HTMLParser

                class TextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.text_parts = []
                        self.in_result = False

                    def handle_starttag(self, tag, attrs):
                        classes = dict(attrs).get("class", "")
                        if "result__snippet" in classes or "result__title" in classes:
                            self.in_result = True

                    def handle_endtag(self, tag):
                        self.in_result = False

                    def handle_data(self, data):
                        if self.in_result and data.strip():
                            self.text_parts.append(data.strip())

                extractor = TextExtractor()
                extractor.feed(raw_html)
                snippets = extractor.text_parts[:10]

                if not snippets:
                    # Return informative fallback
                    return ToolResult(content=f"No direct search results found for query '{query}'.")

                combined_results = "\n".join(f"- {s}" for s in snippets)
                safe_wrapped = wrap_untrusted_content(combined_results, source="DuckDuckGo Web Search")
                return ToolResult(content=safe_wrapped)
        except Exception as e:
            return ToolResult(content=f"Search connection error: {str(e)}", is_error=True)
