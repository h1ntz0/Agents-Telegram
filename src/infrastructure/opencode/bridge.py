"""HTTP bridge to locally running OpenCode server (opencode serve / opencode web).

Enables Telegram users to list, attach, inspect, and prompt active OpenCode
sessions directly from Telegram chat — cross-platform (Windows / macOS / Linux).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
import urllib.parse
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
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.base_url = (base_url or DEFAULT_OPENCODE_URL).rstrip("/")
        self.timeout = timeout
        self.prompt_timeout = prompt_timeout
        self.transport = transport

    def _client(self, timeout: Optional[float] = None) -> httpx.AsyncClient:
        kwargs: Dict[str, Any] = {"timeout": timeout or self.timeout}
        if getattr(self, "transport", None) is not None:
            kwargs["transport"] = self.transport
        return httpx.AsyncClient(**kwargs)

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
        candidates = [self.base_url] if self.is_loopback_url(self.base_url) else []
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
        self._assert_loopback()
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
        self._assert_loopback()
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
        self._assert_loopback()
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
        self._assert_loopback()
        url = f"{self.base_url}/session/{session_id}"
        try:
            async with self._client() as client:
                res = await client.delete(url)
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def get_messages(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent messages from a session."""
        self._assert_loopback()
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
        self._assert_loopback()
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


    # -----------------------------------------------------------------------
    # Loopback Security Guard & v2 OpenCode Server API
    # -----------------------------------------------------------------------

    @staticmethod
    def is_loopback_url(url: str) -> bool:
        """Return True only when hostname is exactly 127.0.0.1, localhost, or ::1."""
        if not url or not isinstance(url, str):
            return False
        cleaned = url.strip()
        if not cleaned:
            return False
        try:
            target = cleaned if "://" in cleaned else f"http://{cleaned}"
            parsed = urllib.parse.urlparse(target)
            host = parsed.hostname
            if not host and parsed.netloc:
                netloc = parsed.netloc
                if netloc.startswith("[") and "]" in netloc:
                    host = netloc[1 : netloc.index("]")]
                elif netloc.startswith("::1"):
                    host = "::1"
            if not host:
                return False
            return host.lower() in {"127.0.0.1", "localhost", "::1"}
        except Exception:
            return False

    def _assert_loopback(self) -> None:
        """Raise OpenCodeError if self.base_url is not a loopback address."""
        if not self.is_loopback_url(self.base_url):
            raise OpenCodeError(
                f"OpenCode server URL must be a loopback address (127.0.0.1, localhost, ::1) "
                f"for security, got '{self.base_url}'"
            )

    async def health(self) -> Optional[Dict[str, Any]]:
        """Check OpenCode server health (GET /api/health)."""
        self._assert_loopback()
        url = f"{self.base_url}/api/health"
        try:
            async with self._client(timeout=3.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    return data if isinstance(data, dict) else None
                return None
        except Exception:
            return None

    async def stream_events(self, session_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Stream SSE events from an active session (GET /api/session/{sid}/event)."""
        self._assert_loopback()
        url = f"{self.base_url}/api/session/{session_id}/event"
        client_kwargs: Dict[str, Any] = {"timeout": None}
        if getattr(self, "transport", None) is not None:
            client_kwargs["transport"] = self.transport

        # ponytail: basic SSE accumulator; add event ID tracking when resume needed
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream("GET", url) as res:
                    if res.status_code != 200:
                        err_body = (await res.aread()).decode("utf-8", errors="replace")[:200]
                        raise OpenCodeError(
                            f"OpenCode event stream failed [HTTP {res.status_code}]: {err_body}"
                        )
                    data_lines: List[str] = []
                    async for line in res.aiter_lines():
                        if line.startswith(":"):
                            continue
                        if not line:
                            if data_lines:
                                raw = "\n".join(data_lines)
                                data_lines = []
                                try:
                                    yield json.loads(raw)
                                except json.JSONDecodeError:
                                    pass
                            continue
                        if line.startswith("data:"):
                            chunk = line[5:]
                            if chunk.startswith(" "):
                                chunk = chunk[1:]
                            data_lines.append(chunk)

                    if data_lines:
                        raw = "\n".join(data_lines)
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            pass
        except asyncio.CancelledError:
            raise
        except OpenCodeError:
            raise
        except httpx.RequestError as e:
            raise OpenCodeError(f"OpenCode stream error: {e}") from e

    async def prompt_async(self, session_id: str, text: str) -> Dict[str, Any]:
        """Send asynchronous prompt (POST /api/session/{sid}/prompt)."""
        self._assert_loopback()
        url = f"{self.base_url}/api/session/{session_id}/prompt"
        payload = {"prompt": {"text": text}}
        try:
            async with self._client(timeout=self.prompt_timeout) as client:
                res = await client.post(url, json=payload)
                if res.status_code != 200:
                    raise OpenCodeError(
                        f"OpenCode prompt error [HTTP {res.status_code}]: {res.text[:300]}"
                    )
                data = res.json()
                if isinstance(data, dict):
                    inner = data.get("data")
                    if isinstance(inner, dict):
                        return inner
                    return data
                return {}
        except OpenCodeError:
            raise
        except httpx.RequestError as e:
            raise OpenCodeError(f"OpenCode connection error: {str(e)}")

    async def interrupt(self, session_id: str) -> bool:
        """Interrupt an active session run (POST /api/session/{sid}/interrupt)."""
        self._assert_loopback()
        url = f"{self.base_url}/api/session/{session_id}/interrupt"
        try:
            async with self._client() as client:
                res = await client.post(url)
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def set_model(self, session_id: str, model_id: str, provider_id: str) -> bool:
        """Set model for session (POST /api/session/{sid}/model)."""
        self._assert_loopback()
        url = f"{self.base_url}/api/session/{session_id}/model"
        payload = {"model": {"id": model_id, "providerID": provider_id}}
        try:
            async with self._client() as client:
                res = await client.post(url, json=payload)
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def set_agent(self, session_id: str, agent: str) -> bool:
        """Set agent for session (POST /api/session/{sid}/agent)."""
        self._assert_loopback()
        url = f"{self.base_url}/api/session/{session_id}/agent"
        payload = {"agent": agent}
        try:
            async with self._client() as client:
                res = await client.post(url, json=payload)
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def _get_list(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        self._assert_loopback()
        url = f"{self.base_url}{path}"
        try:
            async with self._client() as client:
                res = await client.get(url, params=params)
                if res.status_code != 200:
                    return []
                data = res.json()
                if isinstance(data, dict):
                    inner = data.get("data")
                    if isinstance(inner, list):
                        return inner
                elif isinstance(data, list):
                    return data
                return []
        except Exception:
            return []

    async def list_agents(self) -> List[Dict[str, Any]]:
        """Fetch available agents (GET /api/agent)."""
        return await self._get_list("/api/agent")

    async def list_models(self) -> List[Dict[str, Any]]:
        """Fetch available models (GET /api/model)."""
        return await self._get_list("/api/model")

    async def list_commands(self) -> List[Dict[str, Any]]:
        """Fetch available commands (GET /api/command)."""
        return await self._get_list("/api/command")

    async def list_skills(self) -> List[Dict[str, Any]]:
        """Fetch available skills (GET /api/skill)."""
        return await self._get_list("/api/skill")

    async def list_permission_requests(
        self, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch pending permission requests (GET /api/session/{sid}/permission or /api/permission/request)."""
        path = (
            f"/api/session/{session_id}/permission"
            if session_id
            else "/api/permission/request"
        )
        return await self._get_list(path)

    async def reply_permission(
        self,
        session_id: str,
        request_id: str,
        reply: str,
        message: Optional[str] = None
    ) -> bool:
        """Reply to permission request (POST /api/session/{sid}/permission/{req_id}/reply)."""
        self._assert_loopback()
        valid_replies = {"once", "always", "reject"}
        if reply not in valid_replies:
            raise ValueError(f"Invalid reply '{reply}'. Must be one of {valid_replies}")
        url = f"{self.base_url}/api/session/{session_id}/permission/{request_id}/reply"
        payload: Dict[str, Any] = {"reply": reply}
        if message is not None:
            payload["message"] = message
        try:
            async with self._client() as client:
                res = await client.post(url, json=payload)
                return res.status_code in (200, 204)
        except Exception:
            return False

    async def get_session_messages_v2(
        self, session_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Fetch recent session messages in v2 format (GET /api/session/{sid}/message)."""
        return await self._get_list(f"/api/session/{session_id}/message", params={"limit": limit})
