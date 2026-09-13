"""Telegram Bot API client with long-polling, callback queries, and rate-resilient dispatch."""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
import httpx
from src.domain.user import TelegramUser
from src.infrastructure.telegram.formatter import markdown_to_telegram_html, split_message_chunks

logger = logging.getLogger(__name__)


DEFAULT_BOT_COMMANDS: List[Dict[str, str]] = [
    {"command": "start", "description": "Mulai & info bot"},
    {"command": "model", "description": "Lihat atau ganti model AI aktif"},
    {"command": "provider", "description": "Lihat atau ganti provider AI aktif (9router/openai/anthropic/...)"},
    {"command": "agent", "description": "Ganti sub-agent persona (coder/qa/researcher)"},
    {"command": "sdlc", "description": "Jalankan 4 tahap SDLC otomatis"},
    {"command": "oc", "description": "Remote kontrol & mirror OpenCode (stop/model/agent/list/attach)"},
    {"command": "schedule", "description": "Jadwalkan prompt AI / cron (e.g. /schedule every 1h Periksa bursa)"},
    {"command": "remind", "description": "Setel pengingat waktu (e.g. /remind 10m Minum air)"},
    {"command": "chart", "description": "Buat grafik visual & ASCII (e.g. /chart bar A,B,C 10,20,30)"},
    {"command": "status", "description": "Status kesehatan & tools sistem"},
    {"command": "settings", "description": "Lihat pengaturan & model aktif"},
    {"command": "tools", "description": "Daftar tools yang tersedia"},
    {"command": "memory", "description": "Lihat memori tersimpan"},
    {"command": "reset", "description": "Bersihkan riwayat percakapan"},
    {"command": "cancel", "description": "Batalkan aksi pending"},
    {"command": "help", "description": "Panduan lengkap perintah bot"},
]



class TelegramAdapter:
    """Async client interfacing with the official Telegram Bot API."""

    def __init__(self, bot_token: str, timeout: float = 30.0):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{self.bot_token}"
        self.timeout = timeout
        self._is_running = False
        self._last_update_id = 0
        self._client: Optional[httpx.AsyncClient] = None

    async def set_my_commands(self, commands: Optional[List[Dict[str, str]]] = None) -> bool:
        """Register slash commands with Telegram so users get autocomplete and menu popup."""
        url = f"{self.base_url}/setMyCommands"
        payload = {"commands": commands or DEFAULT_BOT_COMMANDS}
        client = await self._get_client()
        try:
            res = await client.post(url, json=payload)
            return res.status_code == 200 and res.json().get("ok", False)
        except Exception as e:
            logger.error(f"Failed to register Telegram bot commands: {str(e)}")
            return False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._is_running = False
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_me(self) -> TelegramUser:
        """Fetch bot identity information to verify token validity."""
        url = f"{self.base_url}/getMe"
        client = await self._get_client()
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

    async def get_file(self, file_id: str) -> Dict[str, Any]:
        """Fetch file metadata from Telegram API via getFile."""
        url = f"{self.base_url}/getFile"
        client = await self._get_client()
        res = await client.get(url, params={"file_id": file_id})
        if res.status_code != 200:
            raise RuntimeError(f"Failed to get file info for {file_id}: HTTP {res.status_code}")
        data = res.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getFile error: {data.get('description', 'Unknown error')}")
        return data["result"]

    async def download_file(self, file_path: str) -> bytes:
        """Download raw file bytes using file path provided by getFile."""
        download_url = f"{self.file_base_url}/{file_path.lstrip('/')}"
        client = await self._get_client()
        res = await client.get(download_url)
        if res.status_code != 200:
            raise RuntimeError(f"Failed to download file from {file_path}: HTTP {res.status_code}")
        return res.content

    async def download_file_by_id(self, file_id: str) -> Tuple[bytes, Dict[str, Any]]:
        """Convenience method: get file info and download bytes in one step."""
        file_info = await self.get_file(file_id)
        file_path = file_info.get("file_path", "")
        if not file_path:
            raise RuntimeError(f"No file_path returned by Telegram for file_id {file_id}")
        content = await self.download_file(file_path)
        return content, file_info

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Optional[int]:
        """Send a photo URL or file_id to a Telegram chat."""
        url = f"{self.base_url}/sendPhoto"
        client = await self._get_client()
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo
        }
        if caption:
            payload["caption"] = caption[:1024]
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        try:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                data = res.json()
                if data.get("ok"):
                    return data["result"]["message_id"]
            logger.error(f"Failed to send photo: {res.text}")
        except Exception as e:
            logger.error(f"Telegram send_photo error: {str(e)}")
        return None

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 10) -> List[Dict[str, Any]]:
        """Poll updates directly from Telegram Bot API."""
        url = f"{self.base_url}/getUpdates"
        params: Dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"]
        }
        if offset is not None:
            params["offset"] = offset

        client = await self._get_client()
        try:
            res = await client.get(url, params=params, timeout=timeout + 5)
            if res.status_code == 200:
                data = res.json()
                if data.get("ok"):
                    return data.get("result", [])
            else:
                logger.warning(f"Telegram getUpdates returned HTTP {res.status_code}: {res.text}")
        except httpx.TimeoutException:
            pass
        except Exception as e:
            logger.error(f"Error fetching Telegram updates: {str(e)}")
        return []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        reply_to_message_id: Optional[int] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> List[int]:
        """Send text message, chunking if necessary. Returns created message IDs."""
        chunks = split_message_chunks(text)
        if not chunks:
            return []

        message_ids = []
        url = f"{self.base_url}/sendMessage"
        client = await self._get_client()

        for idx, chunk in enumerate(chunks):
            formatted_text = markdown_to_telegram_html(chunk) if parse_mode == "HTML" else chunk
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": formatted_text,
                "disable_web_page_preview": True
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            # Attach reply markup and reply_to only to the last chunk
            if idx == len(chunks) - 1:
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                if reply_to_message_id:
                    payload["reply_to_message_id"] = reply_to_message_id

            try:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("ok"):
                        message_ids.append(data["result"]["message_id"])
                else:
                    # Retry without parse_mode if HTML/Markdown parsing failed
                    if parse_mode and res.status_code == 400:
                        payload["text"] = chunk
                        payload.pop("parse_mode", None)
                        res = await client.post(url, json=payload)
                        if res.status_code == 200 and res.json().get("ok"):
                            message_ids.append(res.json()["result"]["message_id"])
                            continue
                    logger.error(f"Failed to send Telegram message to {chat_id}: {res.text}")
            except Exception as e:
                logger.error(f"Telegram send_message network error: {str(e)}")

        return message_ids

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        """Edit an existing bot message (e.g. for progress updates or confirmation responses)."""
        url = f"{self.base_url}/editMessageText"
        formatted_text = markdown_to_telegram_html(text) if parse_mode == "HTML" else text
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": formatted_text,
            "disable_web_page_preview": True
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        client = await self._get_client()
        try:
            res = await client.post(url, json=payload)
            if res.status_code == 200 and res.json().get("ok", False):
                return True
            # Fallback if markdown error
            if parse_mode and res.status_code == 400:
                payload["text"] = text
                payload.pop("parse_mode", None)
                res = await client.post(url, json=payload)
                return res.status_code == 200 and res.json().get("ok", False)
            return False
        except Exception as e:
            logger.error(f"Telegram edit_message_text error: {str(e)}")
            return False

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        """Broadcast chat action indicator like 'typing'."""
        url = f"{self.base_url}/sendChatAction"
        client = await self._get_client()
        try:
            res = await client.post(url, json={"chat_id": chat_id, "action": action})
            return res.status_code == 200
        except Exception:
            return False

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None, show_alert: bool = False) -> bool:
        """Acknowledge inline keyboard button clicks."""
        url = f"{self.base_url}/answerCallbackQuery"
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = show_alert
        client = await self._get_client()
        try:
            res = await client.post(url, json=payload)
            return res.status_code == 200
        except Exception:
            return False

    async def start_polling(
        self,
        on_message: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
        on_callback_query: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None,
        poll_interval: float = 0.5
    ) -> None:
        """Execute non-blocking long-polling loop with automatic backoff."""
        self._is_running = True
        logger.info("Starting Telegram long polling loop")

        backoff = 1.0
        while self._is_running:
            try:
                updates = await self.get_updates(offset=self._last_update_id + 1, timeout=25)
                if updates:
                    backoff = 1.0
                    for update in updates:
                        update_id = update["update_id"]
                        self._last_update_id = max(self._last_update_id, update_id)

                        if "message" in update:
                            asyncio.create_task(on_message(update["message"]))
                        elif "callback_query" in update and on_callback_query:
                            asyncio.create_task(on_callback_query(update["callback_query"]))
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
