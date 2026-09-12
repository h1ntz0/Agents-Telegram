"""OpenCode live session mirror for Telegram.

Streams OpenCode agent execution events using a compact Status Card design.
Status and tool updates are continuously mirrored into a single card message,
while assistant responses are sent as full separate messages upon completion.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class RenderedUpdate:
    """Rendered representation of a single OpenCode event."""

    kind: str  # "status" | "tool" | "text" | "error" | "done"
    text: str


def _safe_get(data: Any, *keys: str) -> Any:
    curr = data
    for k in keys:
        if not isinstance(curr, dict):
            return None
        curr = curr.get(k)
    return curr


def _extract_tool(data: Dict[str, Any]) -> str:
    for val in [
        data.get("tool"),
        data.get("toolName"),
        data.get("name"),
        _safe_get(data, "state", "tool"),
    ]:
        if val:
            return str(val)
    return "tool"


def _extract_title(data: Dict[str, Any]) -> Optional[str]:
    for val in [
        _safe_get(data, "state", "title"),
        data.get("title"),
        _safe_get(data, "state", "input", "command"),
        _safe_get(data, "input", "command"),
        _safe_get(data, "state", "input", "filePath"),
        _safe_get(data, "input", "filePath"),
    ]:
        if val:
            return str(val)
    return None


def _extract_output(data: Dict[str, Any]) -> Optional[str]:
    for val in [
        _safe_get(data, "state", "output"),
        data.get("output"),
    ]:
        if val is not None:
            return str(val)
    return None


def _extract_error(data: Dict[str, Any]) -> str:
    for val in [
        _safe_get(data, "state", "error"),
        data.get("error"),
        data.get("message"),
    ]:
        if val is not None and val != "":
            if isinstance(val, dict):
                return str(val.get("message") or val)
            return str(val)
    return "error"


def _extract_command(data: Dict[str, Any]) -> str:
    for val in [
        _safe_get(data, "state", "input", "command"),
        _safe_get(data, "input", "command"),
        _safe_get(data, "state", "command"),
        data.get("command"),
        _safe_get(data, "state", "title"),
        data.get("title"),
    ]:
        if val:
            return str(val)
    return ""


def render_event(event: Dict[str, Any]) -> Optional[RenderedUpdate]:
    """Map one OpenCode SSE frame to a RenderedUpdate, or None to ignore."""
    try:
        if not isinstance(event, dict):
            return None

        event_type = event.get("type")
        data = event.get("data")
        if not event_type or not isinstance(event_type, str) or not isinstance(data, dict):
            return None

        if event_type == "session.next.prompt.admitted":
            return RenderedUpdate(kind="status", text="⏳ Prompt diterima…")

        if event_type == "session.next.step.started":
            return RenderedUpdate(kind="status", text="🧠 Berpikir…")

        if event_type == "session.next.text.ended":
            text = data.get("text")
            if text is not None:
                return RenderedUpdate(kind="text", text=str(text))
            return None

        if event_type == "session.next.text.started":
            return None

        if event_type == "session.next.tool.called":
            tool = _extract_tool(data)
            title = _extract_title(data)
            text = f"🔧 {tool}: {title}" if title else f"🔧 {tool}"
            return RenderedUpdate(kind="tool", text=text)

        if event_type == "session.next.tool.progress":
            title = _extract_title(data)
            progress = _safe_get(data, "state", "progress") or data.get("progress")
            if not (title or progress):
                return None
            tool = _extract_tool(data)
            return RenderedUpdate(kind="tool", text=f"⏳ {tool}…")

        if event_type == "session.next.tool.success":
            tool = _extract_tool(data)
            return RenderedUpdate(kind="tool", text=f"✅ {tool}")

        if event_type == "session.next.tool.failed":
            tool = _extract_tool(data)
            error = _extract_error(data)
            return RenderedUpdate(kind="error", text=f"❌ {tool}: {error}")

        if event_type == "session.next.shell.started":
            cmd = _extract_command(data)
            return RenderedUpdate(kind="tool", text=f"💻 shell: {cmd}")

        if event_type == "session.next.shell.ended":
            return None

        if event_type == "session.next.step.failed":
            error = _extract_error(data)
            return RenderedUpdate(kind="error", text=f"❌ {error}")

        if event_type == "session.next.step.ended":
            finish = data.get("finish")
            if not finish:
                return None
            return RenderedUpdate(kind="done", text=str(finish))

        if event_type in ("session.next.prompted", "session.next.synthetic"):
            return None

        return None
    except Exception:
        return None


class OpenCodeMirror:
    """Mirrors a live OpenCode session using an ephemeral Status Card."""

    def __init__(
        self,
        bridge: Any,
        telegram: Any,
        session_id: str,
        chat_id: int,
        *,
        edit_interval: float = 1.5,
        max_chars: int = 3500,
        max_idle_seconds: float = 900.0,
        permission_poll_interval: float = 3.0,
        max_card_lines: int = 6,
    ) -> None:
        self.bridge = bridge
        self.telegram = telegram
        self.session_id = session_id
        self.chat_id = chat_id
        self.edit_interval = edit_interval
        self.max_chars = max_chars
        self.max_idle_seconds = max_idle_seconds
        self.permission_poll_interval = permission_poll_interval
        self.max_card_lines = max_card_lines

        self._running: bool = False
        self._status_lines: List[str] = []
        self._assistant_texts: List[str] = []
        self._surfaced_permission_ids: Set[str] = set()
        self._permission_tokens: Dict[str, str] = {}
        self._perm_seq: int = 0
        self._header: str = "⏳ OpenCode"

    @property
    def is_running(self) -> bool:
        """True while run_prompt is actively consuming events."""
        return self._running

    def _render_status_card(self) -> str:
        """Compose compact status card text from recent status/tool lines."""
        recent = (
            self._status_lines[-self.max_card_lines :]
            if self._status_lines
            else ["⏳ Memproses…"]
        )
        return f"{self._header}\n" + "\n".join(recent)

    def _render(self) -> str:
        """Compatibility alias for _render_status_card."""
        return self._render_status_card()

    def _stop_keyboard(self) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": "⏹️ Stop", "callback_data": f"ocstop:{self.session_id}"}]
            ]
        }

    async def _check_permissions(self) -> None:
        """Poll and relay active permission requests to Telegram."""
        try:
            if not hasattr(self.bridge, "list_permission_requests"):
                return
            requests = await self.bridge.list_permission_requests(self.session_id)
            if not isinstance(requests, list):
                return

            for req in requests:
                if not isinstance(req, dict):
                    continue
                req_id = (
                    req.get("id")
                    or req.get("requestID")
                    or req.get("requestId")
                )
                if not req_id:
                    continue
                req_id_str = str(req_id)
                self._surfaced_permission_ids.add(req_id_str)
                self._perm_seq += 1
                token = f"{self.session_id[-6:]}{self._perm_seq}"
                self._permission_tokens[token] = req_id_str

                title = (
                    req.get("permission")
                    or req.get("type")
                    or req.get("title")
                    or req.get("name")
                    or "Perizinan"
                )
                desc = (
                    req.get("pattern")
                    or req.get("description")
                    or req.get("message")
                    or req.get("command")
                    or req.get("path")
                    or ""
                )
                msg_text = f"🔐 Permintaan Izin: {title}\n{desc}".strip()
                keyboard = {
                    "inline_keyboard": [
                        [
                            {
                                "text": "✅ Once",
                                "callback_data": f"ocperm:{token}:once",
                            },
                            {
                                "text": "🟢 Always",
                                "callback_data": f"ocperm:{token}:always",
                            },
                            {
                                "text": "❌ Reject",
                                "callback_data": f"ocperm:{token}:reject",
                            },
                        ]
                    ]
                }
                await self.telegram.send_message(
                    self.chat_id,
                    msg_text,
                    reply_markup=keyboard,
                )
        except Exception as e:
            logger.debug(f"Failed to poll permission requests: {e}")

    def resolve_permission_token(self, token: str) -> Optional[str]:
        """Resolve a short callback token back to its OpenCode request id."""
        return self._permission_tokens.get(token)

    async def run_prompt(self, text: str) -> None:
        """Submit prompt, maintain status card, and deliver full assistant text."""
        self._running = True
        self._status_lines = []
        self._assistant_texts = []
        self._surfaced_permission_ids = set()

        card_id: Optional[int] = None
        perm_task: Optional[asyncio.Task[None]] = None
        terminal_update: Optional[RenderedUpdate] = None

        try:
            try:
                await self.telegram.send_chat_action(self.chat_id, "typing")
            except Exception as e:
                logger.debug(f"Failed to send typing chat action: {e}")

            # Inspect agent name if cheaply available from bridge
            agent_name = ""
            try:
                if hasattr(self.bridge, "get_session"):
                    session_info = await self.bridge.get_session(self.session_id)
                    if isinstance(session_info, dict) and session_info.get("agent"):
                        agent_name = str(session_info["agent"])
            except Exception:
                pass
            self._header = (
                f"⏳ OpenCode [{agent_name}]" if agent_name else "⏳ OpenCode"
            )

            await self.bridge.prompt_async(self.session_id, text)

            # Send Status Card message with Stop button
            initial_card = self._render_status_card()
            send_res = await self.telegram.send_message(
                self.chat_id,
                initial_card,
                reply_markup=self._stop_keyboard(),
            )
            if isinstance(send_res, list) and send_res:
                card_id = send_res[0]
            elif isinstance(send_res, int):
                card_id = send_res

            # Initial permission check and background poller
            await self._check_permissions()

            async def _poll_permissions_loop() -> None:
                while self._running:
                    await asyncio.sleep(self.permission_poll_interval)
                    if self._running:
                        await self._check_permissions()

            perm_task = asyncio.create_task(_poll_permissions_loop())

            # Event streaming loop
            last_edit_time = time.monotonic() - self.edit_interval
            last_card_text = initial_card

            stream = self.bridge.stream_events(self.session_id)
            iterator = aiter(stream)

            while self._running:
                try:
                    event = await asyncio.wait_for(
                        anext(iterator),
                        timeout=self.max_idle_seconds,
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    logger.warning(
                        f"OpenCode stream idle timeout after {self.max_idle_seconds}s "
                        f"for session {self.session_id}"
                    )
                    break

                upd = render_event(event)
                if upd is None:
                    continue

                if upd.kind == "text":
                    self._assistant_texts.append(upd.text)
                    continue

                if upd.kind in ("status", "tool", "error"):
                    self._status_lines.append(upd.text)

                if upd.kind in ("done", "error"):
                    terminal_update = upd
                    break

                now = time.monotonic()
                if (now - last_edit_time) >= self.edit_interval:
                    new_card = self._render_status_card()
                    if card_id is not None and new_card != last_card_text:
                        await self.telegram.edit_message_text(
                            self.chat_id,
                            card_id,
                            new_card,
                            reply_markup=self._stop_keyboard(),
                        )
                        last_card_text = new_card
                        last_edit_time = now

            # Stop background permission poller
            if perm_task and not perm_task.done():
                perm_task.cancel()
                try:
                    await perm_task
                except asyncio.CancelledError:
                    pass

            # 2. Assistant text sent as NEW message(s), FULL text without truncation
            full_assistant_text = "".join(self._assistant_texts)
            is_error = terminal_update and terminal_update.kind == "error"

            if full_assistant_text and not is_error:
                await self.telegram.send_message(self.chat_id, full_assistant_text)

            # 3. Final compact edit on status card, remove inline keyboard
            if card_id is not None:
                if is_error:
                    err_msg = terminal_update.text if terminal_update else "unknown"
                    if err_msg.startswith("❌ "):
                        err_msg = err_msg[2:].strip()
                    final_card = f"❌ OpenCode error: {err_msg}"
                elif terminal_update and terminal_update.kind == "done":
                    final_card = f"✅ OpenCode selesai ({terminal_update.text})"
                else:
                    final_card = "✅ OpenCode selesai (done)"

                await self.telegram.edit_message_text(
                    self.chat_id,
                    card_id,
                    final_card,
                    reply_markup={"inline_keyboard": []},
                )

        except Exception as e:
            logger.error(f"Error in OpenCodeMirror run_prompt: {e}", exc_info=True)
            err_msg = f"❌ OpenCode error: {e}"
            try:
                if card_id is not None:
                    await self.telegram.edit_message_text(
                        self.chat_id,
                        card_id,
                        err_msg,
                        reply_markup={"inline_keyboard": []},
                    )
                else:
                    await self.telegram.send_message(self.chat_id, err_msg)
            except Exception as send_err:
                logger.error(f"Failed to send error notification to Telegram: {send_err}")
        finally:
            if perm_task and not perm_task.done():
                perm_task.cancel()
            self._running = False

    async def stop(self) -> None:
        """Interrupt active session turn and stop consuming events."""
        self._running = False
        try:
            if hasattr(self.bridge, "interrupt"):
                await self.bridge.interrupt(self.session_id)
        except Exception as e:
            logger.warning(f"Error interrupting OpenCode session {self.session_id}: {e}")
        return None
