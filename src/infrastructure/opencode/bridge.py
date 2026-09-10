"""HTTP bridge to locally running OpenCode server (opencode serve / opencode web).

Enables Telegram users to list, attach, inspect, and prompt active OpenCode
sessions directly from Telegram chat — cross-platform (Windows / macOS / Linux).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

DEFAULT_OPENCODE_URL = "http://127.0.0.1:4096"
FALLBACK_PORTS = [4096, 55557]


class OpenCodeError(RuntimeError):
    """Raised when an OpenCode server operation fails."""


class OpenCodeBridge:
    """Communicates with the OpenCode REST HTTP API."""

    def __init__(
        self,
        base_url: str = DEFAULT_OPENCODE_URL,
        timeout: float = 60.0,
        prompt_timeout: float = 180.0,
    ):
        self.base_url = (base_url or DEFAULT_OPENCODE_URL).rstrip("/")
        self.timeout = timeout
        self.prompt_timeout = prompt_timeout

    def _client(self, timeout: Optional[float] = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout or self.timeout)

    async def is_server_available(self, url: Optional[str] = None) -> bool:
        """Check if OpenCode server is responding at target URL."""
        target = (url or self.base_url).rstrip("/")
        try:
            async with self._client(timeout=3.0) as client:
                res = await client.get(f"{target}/session")
                return res.status_code in (200, 404)
        except Exception:
            return False

    async def auto_discover_server(self) -> Optional[str]:
        """Probe configured and standard loopback ports for a live OpenCode server."""
        candidates = [self.base_url]
        for port in FALLBACK_PORTS:
            cand = f"http://127.0.0.1:{port}"
            if cand not in candidates:
                candidates.append(cand)

        for cand in candidates:
            if await self.is_server_available(cand):
                self.base_url = cand
                return cand
        return None

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """Fetch all known sessions from the OpenCode server."""
        url = f"{self.base_url}/session"
        try:
            async with self._client() as client:
                res = await client.get(url)
                if res.status_code != 200:
                    raise OpenCodeError(f"OpenCode returned HTTP {res.status_code}: {res.text[:200]}")
                data = res.json()
                return data if isinstance(data, list) else []
        except httpx.RequestError as e:
            raise OpenCodeError(
                f"Cannot connect to OpenCode server at {self.base_url}. "
                f"Is 'opencode serve' running? Detail: {str(e)}"
            )

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Fetch metadata for a specific session."""
        url = f"{self.base_url}/session/{session_id}"
        try:
            async with self._client() as client:
                res = await client.get(url)
                if res.status_code == 200:
                    return res.json()
                if res.status_code == 404:
                    return None
                raise OpenCodeError(f"HTTP {res.status_code}: {res.text[:200]}")
        except httpx.RequestError as e:
            raise OpenCodeError(f"OpenCode connection error: {str(e)}")

    async def create_session(self, title: Optional[str] = None) -> Dict[str, Any]:
        """Create a new session on the OpenCode server."""
        url = f"{self.base_url}/session"
        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = title
        try:
            async with self._client() as client:
                res = await client.post(url, json=payload)
                if res.status_code not in (200, 201):
                    raise OpenCodeError(f"Failed to create session [HTTP {res.status_code}]: {res.text[:200]}")
                return res.json()
        except httpx.RequestError as e:
            raise OpenCodeError(f"OpenCode connection error: {str(e)}")

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID."""
        url = f"{self.base_url}/session/{session_id}"
        try:
            async with self._client() as client:
                res = await client.delete(url)
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def get_messages(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent messages from a session."""
        url = f"{self.base_url}/session/{session_id}/message"
        try:
            async with self._client() as client:
                res = await client.get(url, params={"limit": limit})
                if res.status_code != 200:
                    raise OpenCodeError(f"HTTP {res.status_code}: {res.text[:200]}")
                data = res.json()
                return data if isinstance(data, list) else []
        except httpx.RequestError as e:
            raise OpenCodeError(f"OpenCode connection error: {str(e)}")

    async def send_message(self, session_id: str, text: str) -> str:
        """Send a prompt to an active OpenCode session and return the text reply."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Prompt text cannot be empty.")

        url = f"{self.base_url}/session/{session_id}/message"
        payload = {
            "parts": [{"type": "text", "text": clean_text}]
        }

        try:
            async with self._client(timeout=self.prompt_timeout) as client:
                res = await client.post(url, json=payload)
                if res.status_code != 200:
                    raise OpenCodeError(
                        f"OpenCode execution error [HTTP {res.status_code}]: {res.text[:300]}"
                    )
                data = res.json()
        except httpx.TimeoutException:
            raise OpenCodeError(
                f"OpenCode session timed out after {self.prompt_timeout}s waiting for completion."
            )
        except httpx.RequestError as e:
            raise OpenCodeError(f"OpenCode connection error: {str(e)}")

        # Extract text from response parts
        parts = data.get("parts", [])
        collected: List[str] = []
        for part in parts:
            if isinstance(part, dict):
                p_type = part.get("type")
                if p_type == "text" and part.get("text"):
                    collected.append(part["text"])

        if collected:
            return "\n\n".join(collected).strip()

        # Fallback: check if info or raw text available
        if isinstance(data.get("info"), dict):
            agent = data["info"].get("agent", "OpenCode")
            finish = data["info"].get("finish", "done")
            return f"[{agent} completed turn with finish={finish}, no text output]"

        return "OpenCode executed the prompt with no text output."
