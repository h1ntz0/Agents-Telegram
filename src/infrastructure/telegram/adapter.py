"""Telegram Bot API client with long-polling, callback queries, and rate-resilient dispatch."""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional
import httpx
from src.domain.user import TelegramUser
from src.infrastructure.telegram.formatter import split_message_chunks

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Async client interfacing with the official Telegram Bot API."""

    def __init__(self, bot_token: str, timeout: float = 30.0):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.timeout = timeout
        self._is_running = False
        self._last_update_id = 0

    async def get_me(self) -> TelegramUser:
        """Fetch bot identity information to verify token validity."""
        url = f"{self.base_url}/getMe"
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url)
            if res.status_code != 200:
                raise ValueError(f"Invalid Telegram Bot Token (HTTP {res.status_code}): {res.text}")
            data = res.json()
            if not data.get("ok"):
                raise ValueError(f"Telegram API Error: {data.get('description', 'Unknown error')}")
            user_data = data["result"]
            return TelegramUser(
                id=user_data["id"],
                username=user_data.get("username", ""),
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
                is_bot=user_data.get("is_bot", True)
            )

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        reply_to_message_id: Optional[int] = None
    ) -> List[int]:
        """Send text message, chunking if necessary. Returns created message IDs."""
        chunks = split_message_chunks(text)
        if not chunks:
            return []

        message_ids = []
        url = f"{self.base_url}/sendMessage"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for idx, chunk in enumerate(chunks):
                payload: Dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True
                }
                # Attach reply markup and reply_to only to the last chunk
                if idx == len(chunks) - 1:
                    if reply_markup:
                        payload["reply_markup"] = reply_markup
                    if reply_to_message_id:
                        payload["reply_to_message_id"] = reply_to_message_id

                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("ok"):
                        message_ids.append(data["result"]["message_id"])
                else:
                    logger.error(f"Failed to send Telegram message to {chat_id}: {res.text}")

        return message_ids

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Edit an existing bot message (e.g. for progress updates or confirmation responses)."""
        url = f"{self.base_url}/editMessageText"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "disable_web_page_preview": True
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, json=payload)
            return res.status_code == 200 and res.json().get("ok", False)

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        """Broadcast chat action indicator like 'typing'."""
        url = f"{self.base_url}/sendChatAction"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json={"chat_id": chat_id, "action": action})
                return res.status_code == 200
        except Exception:
            return False

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> bool:
        """Acknowledge inline keyboard button clicks."""
        url = f"{self.base_url}/answerCallbackQuery"
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception:
            return False

    async def start_polling(
        self,
        on_message: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
        on_callback_query: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None,
        poll_interval: float = 1.0
    ) -> None:
        """Execute non-blocking long-polling loop with automatic backoff."""
        self._is_running = True
        logger.info("Starting Telegram long polling loop")

        backoff = 1.0
        async with httpx.AsyncClient(timeout=35.0) as client:
            while self._is_running:
                try:
                    url = f"{self.base_url}/getUpdates"
                    params = {
                        "offset": self._last_update_id + 1,
                        "timeout": 25,
                        "allowed_updates": ["message", "callback_query"]
                    }
                    res = await client.get(url, params=params)

                    if res.status_code == 200:
                        backoff = 1.0
                        data = res.json()
                        if data.get("ok"):
                            for update in data.get("result", []):
                                update_id = update["update_id"]
                                self._last_update_id = max(self._last_update_id, update_id)

                                if "message" in update:
                                    asyncio.create_task(on_message(update["message"]))
                                elif "callback_query" in update and on_callback_query:
                                    asyncio.create_task(on_callback_query(update["callback_query"]))
                    else:
                        logger.warning(f"Telegram polling non-200 response: {res.status_code}")
                        await asyncio.sleep(backoff)
                        backoff = min(30.0, backoff * 1.5)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Polling loop error: {str(e)}")
                    await asyncio.sleep(backoff)
                    backoff = min(30.0, backoff * 1.5)

                await asyncio.sleep(poll_interval)

    def stop_polling(self) -> None:
        """Signal the polling loop to shut down cleanly."""
        self._is_running = False
        logger.info("Telegram long polling stopped")
