"""HTTP Web Page Fetch tool with HTML-to-text extraction and SSRF protection."""

import html
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
import httpx
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult
from src.infrastructure.security.prompt_guard import wrap_untrusted_content
from src.infrastructure.security.ssrf_guard import is_safe_url


class HTMLTextExtractor(HTMLParser):
    """Clean HTML-to-markdown text converter ignoring non-content tags."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "header", "footer", "nav", "style", "head"}

    def __init__(self):
        super().__init__()
        self.text_parts: List[str] = []
        self.skip_stack: List[str] = []
        self.in_list_item = False
        self.current_href: Optional[str] = None
        self.link_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]):
        tag_lower = tag.lower()
        if tag_lower in self.SKIP_TAGS:
            self.skip_stack.append(tag_lower)
            return

        if self.skip_stack:
            return

        attr_dict = dict(attrs)
        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.text_parts.append("\n\n" + "#" * int(tag_lower[1]) + " ")
        elif tag_lower in ("p", "div", "article", "section", "blockquote"):
            self.text_parts.append("\n\n")
        elif tag_lower == "br":
            self.text_parts.append("\n")
        elif tag_lower == "li":
            self.text_parts.append("\n• ")
            self.in_list_item = True
        elif tag_lower == "a":
            self.current_href = attr_dict.get("href")
            self.link_text = []

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if self.skip_stack:
            if tag_lower in self.skip_stack:
                self.skip_stack.remove(tag_lower)
            return

        if tag_lower == "li":
            self.in_list_item = False
        elif tag_lower == "a":
            if self.current_href and self.link_text:
                full_link_text = "".join(self.link_text).strip()
                if full_link_text and self.current_href.startswith(("http://", "https://")):
                    self.text_parts.append(f" [{self.current_href}]")
            self.current_href = None
            self.link_text = []

    def handle_data(self, data: str):
        if self.skip_stack:
            return

        cleaned = data.strip()
        if not cleaned:
            return

        if self.current_href is not None:
            self.link_text.append(cleaned)

        self.text_parts.append(data)

    def get_text(self) -> str:
        raw_text = "".join(self.text_parts)
        # Normalize multiple spaces and blank lines
        raw_text = html.unescape(raw_text)
        raw_text = re.sub(r"\r\n|\r", "\n", raw_text)
        raw_text = re.sub(r"\n{3,}", "\n\n", raw_text)
        lines = [line.strip() for line in raw_text.splitlines()]
        return "\n".join(line for line in lines if line)


class HttpFetchTool(BaseTool):
    """Safely fetch web page articles with HTML extraction and SSRF validation."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="http_fetch",
            description="Fetch the text and article content from a web page URL safely with SSRF protection.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full HTTP/HTTPS URL of the web page to fetch."
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum number of characters of extracted text to return (default: 4000)."
                    }
                },
                "required": ["url"]
            },
            permission=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        url = arguments.get("url", "").strip()
        if not url:
            return ToolResult(content="URL parameter cannot be empty.", is_error=True)

        max_chars = int(arguments.get("max_chars", 4000))
        if max_chars <= 0:
            max_chars = 4000
        max_chars = min(max_chars, 16000)

        # 1. SSRF Safety Verification
        is_safe, reason = is_safe_url(url)
        if not is_safe:
            return ToolResult(
                content=f"SSRF Security Violation: {reason}",
                is_error=True
            )

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                res = await client.get(url, headers=headers)
                if res.status_code >= 400:
                    return ToolResult(
                        content=f"HTTP Request failed with status code {res.status_code}.",
                        is_error=True
                    )

                content_type = res.headers.get("content-type", "").lower()
                # If plain text / json / markdown
                if "application/json" in content_type or "text/plain" in content_type or "text/markdown" in content_type:
                    extracted_text = res.text[:max_chars]
                else:
                    # HTML extraction
                    parser = HTMLTextExtractor()
                    parser.feed(res.text)
                    extracted_text = parser.get_text()[:max_chars]

                if not extracted_text.strip():
                    return ToolResult(content=f"Web page at {url} returned empty readable text content.")

                safe_wrapped = wrap_untrusted_content(extracted_text, source=f"HTTP Fetch: {url}")
                return ToolResult(
                    content=safe_wrapped,
                    metadata={"url": url, "status_code": res.status_code, "length": len(extracted_text)}
                )
        except httpx.TimeoutException:
            return ToolResult(content=f"Connection timed out while fetching {url}.", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Failed to fetch web page: {str(e)}", is_error=True)
