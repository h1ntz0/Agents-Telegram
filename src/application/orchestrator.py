"""Central Agent Orchestrator handling message routing, ReAct loop, multimodal media, scheduling, and Multi-Agent SDLC."""

import asyncio
import base64
import csv
import io
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional
import httpx
from src.application.config_manager import RootConfig
from src.infrastructure.opencode.bridge import OpenCodeBridge, OpenCodeError
from src.application.multiagent_sdlc import MultiAgentSDLC
from src.domain.agent import AgentState, Message, PendingConfirmation, Role, Session, ToolCall, ToolResponse
from src.domain.provider import AIProvider, CompletionRequest, PROVIDER_MODELS_CATALOG
from src.infrastructure.ai.model_discovery import fetch_available_models
from src.infrastructure.database.sqlite_db import SqliteDatabase
from src.infrastructure.scheduler.job_scheduler import JobScheduler, ScheduledJob
from src.infrastructure.security.humanizer import humanize_response
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.chart_tool import ChartTool
from src.infrastructure.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SUBAGENT_PERSONAS = {
    "orchestrator": "You are the Lead Coordinator Agent. You oversee task decomposition and synthesize inputs from specialized agents.",
    "researcher": "You are the Research & Discovery Agent. Search the web, summarize technical docs, and provide verifiable facts.",
    "coder": "You are the Senior Software Engineer Agent. Write clean, working, minimal production code.",
    "qa": "You are the QA & Security Agent. Check for boundary conditions, security vulnerabilities, and verify test assertions.",
}


class AgentOrchestrator:
    """Orchestrates agent execution flow between Telegram, AI provider, tools, SQLite persistence, and proactive scheduler."""

    def __init__(
        self,
        config: RootConfig,
        telegram_adapter: TelegramAdapter,
        ai_provider: AIProvider,
        db: SqliteDatabase,
        tool_registry: ToolRegistry,
        auth_manager: TelegramAuthManager,
        rate_limiter: UserRateLimiter,
        scheduler: Optional[JobScheduler] = None,
    ):
        self.config = config
        self.telegram = telegram_adapter
        self.ai = ai_provider
        self.db = db
        self.tools = tool_registry
        self.auth = auth_manager
        self.rate_limiter = rate_limiter
        self.scheduler = scheduler or JobScheduler(db=db)
        self.sdlc = MultiAgentSDLC(ai_provider=ai_provider, tool_registry=tool_registry)
        self._pending_actions: Dict[str, PendingConfirmation] = {}
        self._user_active_persona: Dict[int, str] = {}
        self._user_active_model: Dict[int, str] = {}
        self._user_active_oc_session: Dict[int, str] = {}
        self.opencode_bridge = OpenCodeBridge(
            base_url=getattr(config.ai, "opencode_server_url", "http://127.0.0.1:4096")
        )

    async def _get_user_model(self, user_id: int) -> str:
        """Retrieve user's chosen model from runtime cache or SQLite persistence."""
        if user_id in self._user_active_model:
            return self._user_active_model[user_id]

        memories = await self.db.get_memories(user_id)
        saved_model = memories.get("_active_model")
        if saved_model:
            self._user_active_model[user_id] = saved_model
            return saved_model

        return self.config.ai.model

    async def _set_user_model(self, user_id: int, model_name: str) -> None:
        """Update user's chosen model in runtime cache and SQLite persistence."""
        clean_name = model_name.strip()
        self._user_active_model[user_id] = clean_name
        await self.db.set_memory(user_id, "_active_model", clean_name)

    async def _transcribe_audio(self, audio_bytes: bytes, filename: str = "voice.ogg") -> Optional[str]:
        """Attempt speech-to-text transcription via OpenAI-compatible whisper endpoint."""
        api_key = self.config.ai.api_key
        if not api_key:
            return None

        base_url = (self.config.ai.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": (filename, audio_bytes, "audio/ogg")}
        data = {"model": "whisper-1"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, headers=headers, data=data, files=files)
                if res.status_code == 200:
                    result_json = res.json()
                    return result_json.get("text", "").strip()
        except Exception as e:
            logger.warning(f"Audio transcription failed: {str(e)}")
        return None

    async def handle_message(self, message_data: Dict[str, Any]) -> None:
        """Process incoming Telegram message supporting text and multimodal attachments."""
        chat = message_data.get("chat", {})
        chat_id = chat.get("id")
        user = message_data.get("from", {})
        user_id = user.get("id")
        is_group = chat.get("type", "private") in ("group", "supergroup")

        if not chat_id or not user_id:
            return

        # 1. Authorization check
        if not self.auth.check_authorization(user_id, is_group=is_group):
            await self.telegram.send_message(chat_id, "Sorry, you are not authorized to use this bot.")
            return

        # 2. Rate limiting check
        if not self.rate_limiter.is_allowed(user_id):
            await self.telegram.send_message(chat_id, "Rate limit exceeded. Please wait a moment before sending more messages.")
            return

        # 3. Extract text / captions and process attachments
        raw_text = message_data.get("text", "").strip()
        caption = message_data.get("caption", "").strip()
        processed_prompt: Optional[str] = None
        message_metadata: Dict[str, Any] = {}

        # Case A: Photo attachment
        if "photo" in message_data and isinstance(message_data["photo"], list) and len(message_data["photo"]) > 0:
            photo_obj = message_data["photo"][-1]
            file_id = photo_obj.get("file_id")
            width = photo_obj.get("width", 0)
            height = photo_obj.get("height", 0)
            file_size = photo_obj.get("file_size", 0)

            try:
                photo_bytes, file_info = await self.telegram.download_file_by_id(file_id)
                b64_photo = base64.b64encode(photo_bytes).decode("utf-8")
                message_metadata["image_base64"] = b64_photo
                message_metadata["mime_type"] = "image/jpeg"
                processed_prompt = caption if caption else "Tolong analisis dan jelaskan gambar terlampir ini secara detail."
            except Exception as e:
                logger.error(f"Failed to process photo: {str(e)}")
                processed_prompt = f"Gagal mengunduh foto ({str(e)}). {caption or ''}"

        # Case B: Document attachment (txt, csv, json, code, markdown, etc.)
        elif "document" in message_data:
            doc = message_data["document"]
            file_id = doc.get("file_id")
            file_name = doc.get("file_name", "document")
            mime_type = doc.get("mime_type", "application/octet-stream")
            file_size = doc.get("file_size", 0)

            try:
                doc_bytes, file_info = await self.telegram.download_file_by_id(file_id)
                # Attempt decoding text content
                text_content = ""
                try:
                    text_content = doc_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        text_content = doc_bytes.decode("latin-1")
                    except Exception:
                        text_content = ""

                if text_content:
                    snippet = text_content[:4000]
                    if len(text_content) > 4000:
                        snippet += "\n... [truncated]"
                    user_req = caption or "Please analyze and summarize this attached document."
                    processed_prompt = (
                        f"[Document Attached: {file_name} ({mime_type}, {file_size} bytes)]\n"
                        f"--- Content Preview ---\n{snippet}\n--- End Preview ---\n\n"
                        f"{user_req}"
                    )
                else:
                    processed_prompt = (
                        f"[Binary Document Attached: {file_name} ({mime_type}, {file_size} bytes)]\n"
                        f"{caption or 'Binary file received.'}"
                    )
            except Exception as e:
                logger.error(f"Failed to process document: {str(e)}")
                processed_prompt = f"[Document Attached: {file_name} (Download Error: {str(e)})]\n{caption or ''}"

        # Case C: Voice / Audio note
        elif "voice" in message_data or "audio" in message_data:
            voice_obj = message_data.get("voice") or message_data.get("audio")
            file_id = voice_obj.get("file_id")
            duration = voice_obj.get("duration", 0)
            file_size = voice_obj.get("file_size", 0)

            try:
                audio_bytes, file_info = await self.telegram.download_file_by_id(file_id)
                transcription = await self._transcribe_audio(audio_bytes, filename=f"voice_{file_id}.ogg")
                if transcription:
                    processed_prompt = f"[Voice Message Transcribed]: {transcription}"
                    await self.telegram.send_message(chat_id, f"🎙️ _Transcribed voice note ({duration}s):_\n\"{transcription}\"")
                else:
                    await self.telegram.send_message(
                        chat_id,
                        f"🎙️ Received voice note ({duration}s, {file_size} bytes).\nVoice transcription requires an OpenAI API key or whisper endpoint configured."
                    )
                    return
            except Exception as e:
                logger.error(f"Failed to process voice note: {str(e)}")
                await self.telegram.send_message(chat_id, f"🎙️ Received voice note ({duration}s), but failed to process audio: {str(e)}")
                return

        # Case D: Standard text message
        elif raw_text:
            processed_prompt = raw_text

        if not processed_prompt:
            return

        # 4. Handle bot slash commands
        if processed_prompt.startswith("/"):
            await self._handle_command(chat_id, user_id, processed_prompt)
            return

        # 5. Normal chat / prompt execution
        await self._process_user_prompt(chat_id, user_id, processed_prompt, metadata=message_metadata)

    async def _handle_command(self, chat_id: int, user_id: int, command_text: str) -> None:
        """Route standard Telegram slash commands, dynamic model switching, scheduler, and SDLC."""
        parts = command_text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        active_model = await self._get_user_model(user_id)
        active_persona = self._user_active_persona.get(user_id, "orchestrator")
        provider_name = self.config.ai.provider.lower()

        if cmd == "/start":
            msg = (
                f"Hello! I am {self.config.agent.name}.\n\n"
                f"Status: Online\n"
                f"Active Provider: {provider_name.upper()}\n"
                f"Active Model: {active_model}\n"
                f"Active Persona: {active_persona.upper()}\n\n"
                "Commands:\n"
                "/model - View or change active AI model\n"
                "/agent - Switch sub-agent persona\n"
                "/schedule <time/cron> <prompt> - Schedule proactive AI job\n"
                "/remind <time> <text> - Set a reminder\n"
                "/chart <type> <labels> <values> - Generate chart\n"
                "/sdlc <task> - Run full 4-stage SDLC\n"
                "/reset - Clear chat history context\n"
                "/help - View all commands"
            )
            await self.telegram.send_message(chat_id, msg)

        elif cmd == "/help":
            help_text = (
                "Available Commands:\n"
                "/model [name] - View or switch active AI model\n"
                "/agent [orchestrator|researcher|coder|qa] - Switch sub-agent persona\n"
                "/schedule <time/cron> <prompt> - Schedule proactive AI job\n"
                "  • Examples: `/schedule every 1h Periksa berita terkini`\n"
                "  • Subcommands: `/schedule list`, `/schedule cancel <id>`\n"
                "/remind <time> <text> - Set a one-off reminder\n"
                "  • Examples: `/remind 15m Minum air`, `/remind 14:30 Rapat`\n"
                "/chart <type> <labels> <values> - Generate QuickChart & ASCII chart\n"
                "  • Example: `/chart bar Jan,Feb,Mar 10,25,18`\n"
                "/sdlc <task> - Execute multi-agent development lifecycle\n"
                "/status - Runtime health and configuration overview\n"
                "/settings - View current model and preferences\n"
                "/tools - List active tools\n"
                "/memory - View recorded memory\n"
                "/reset - Clear conversation context\n"
                "/cancel - Abort pending action"
            )
            await self.telegram.send_message(chat_id, help_text)

        elif cmd == "/model":
            if args:
                await self._set_user_model(user_id, args)
                markup = {
                    "inline_keyboard": [
                        [{"text": "🧹 Clear History (/reset)", "callback_data": "reset_session"}]
                    ]
                }
                await self.telegram.send_message(
                    chat_id,
                    f"✓ Active model for {provider_name.upper()} switched to: {args}\n\nTip: Gunakan /reset jika ingin mengosongkan riwayat percakapan dari model sebelumnya.",
                    reply_markup=markup
                )
                return

            # Dynamically discover live models for the active provider
            catalog_models = await fetch_available_models(
                provider_name=provider_name,
                api_key=self.config.ai.api_key,
                base_url=self.config.ai.base_url
            )
            if not catalog_models:
                catalog_models = PROVIDER_MODELS_CATALOG.get(provider_name, [])

            # Cap inline keyboard buttons to 15 to avoid overwhelming Telegram UI
            buttons: List[List[Dict[str, str]]] = []
            for m in catalog_models[:15]:
                buttons.append([{"text": f"Select {m}", "callback_data": f"set_model:{m}"}])

            markup = {"inline_keyboard": buttons} if buttons else None
            msg = (
                f"Active Provider: {provider_name.upper()}\n"
                f"Current Model: {active_model}\n\n"
                "Click a model button below or type:\n"
                "  /model <model_name>\n"
                "Contoh: /model ds/deepseek-v4-flash"
            )
            await self.telegram.send_message(chat_id, msg, reply_markup=markup)

        elif cmd == "/agent":
            if not args:
                cur = self._user_active_persona.get(user_id, "orchestrator")
                avail = ", ".join(SUBAGENT_PERSONAS.keys())
                await self.telegram.send_message(chat_id, f"Current Agent Persona: {cur}\nAvailable: {avail}\nUsage: /agent <name>")
                return
            target = args.lower()
            if target in SUBAGENT_PERSONAS:
                self._user_active_persona[user_id] = target
                await self.telegram.send_message(chat_id, f"✓ Switched to {target.upper()} agent persona.")
            else:
                await self.telegram.send_message(chat_id, f"Unknown agent persona '{target}'. Options: {', '.join(SUBAGENT_PERSONAS.keys())}")

        elif cmd == "/schedule":
            if not args:
                usage = (
                    "Usage: `/schedule <time/cron> <prompt>`\n\n"
                    "Examples:\n"
                    "• `/schedule every 1h Periksa berita saham`\n"
                    "• `/schedule 10m Analisis log server`\n"
                    "• `/schedule */30 * * * * Update harga koin`\n"
                    "• `/schedule list` — Lihat semua jadwal aktif\n"
                    "• `/schedule cancel <job_id>` — Batalkan jadwal"
                )
                await self.telegram.send_message(chat_id, usage)
                return

            if args.lower() == "list":
                jobs = await self.scheduler.list_jobs(user_id=user_id, active_only=True)
                if not jobs:
                    await self.telegram.send_message(chat_id, "No active scheduled jobs.")
                    return
                lines = ["📅 **Active Scheduled Jobs:**"]
                for j in jobs:
                    lines.append(f"• `{j.job_id}` [{j.job_type}]: {j.prompt} (Next: {j.next_run_at.strftime('%Y-%m-%d %H:%M:%S UTC')})")
                await self.telegram.send_message(chat_id, "\n".join(lines))
                return

            if args.lower().startswith("cancel "):
                job_id = args.split(maxsplit=1)[1].strip()
                cancelled = await self.scheduler.cancel_job(job_id, user_id=user_id)
                if cancelled:
                    await self.telegram.send_message(chat_id, f"✓ Scheduled job `{job_id}` has been cancelled.")
                else:
                    await self.telegram.send_message(chat_id, f"Job `{job_id}` not found or already completed/cancelled.")
                return

            # Parse schedule time expression and prompt
            # Support tokens like 'in 10m prompt...', 'every 1h prompt...', '10m prompt...', '*/5 * * * * prompt...'
            cron_match = re.match(r"^((?:(?:\*/\d+|\d+(?:-\d+)?|\*)\s+){4}(?:\*/\d+|\d+(?:-\d+)?|\*))\s+(.+)$", args)
            interval_match = re.match(r"^(in\s+\d+\s*\w+|every\s+\d+\s*\w+|\d+\s*[a-zA-Z]+|\d{1,2}:\d{2})\s+(.+)$", args, re.IGNORECASE)

            if cron_match:
                sched_expr = cron_match.group(1).strip()
                prompt_text = cron_match.group(2).strip()
            elif interval_match:
                sched_expr = interval_match.group(1).strip()
                prompt_text = interval_match.group(2).strip()
            else:
                tokens = args.split(maxsplit=1)
                sched_expr = tokens[0]
                prompt_text = tokens[1] if len(tokens) > 1 else ""

            if not prompt_text:
                await self.telegram.send_message(chat_id, "Please provide the prompt/task to execute.")
                return

            try:
                job = await self.scheduler.schedule_cron(
                    user_id=user_id,
                    chat_id=chat_id,
                    schedule_expr=sched_expr,
                    prompt=prompt_text,
                    is_ai_prompt=True,
                )
                await self.telegram.send_message(
                    chat_id,
                    f"✓ Proactive scheduled AI job created (`{job.job_id}`).\n"
                    f"• Type: {job.schedule_type.upper()} ({job.schedule_value})\n"
                    f"• Next Trigger: {job.next_run_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"• Prompt: \"{job.prompt}\""
                )
            except Exception as e:
                await self.telegram.send_message(chat_id, f"Scheduling error: {str(e)}")

        elif cmd == "/remind":
            if not args:
                usage = (
                    "Usage: `/remind <time> <reminder_text>`\n\n"
                    "Examples:\n"
                    "• `/remind 10m Minum air putih`\n"
                    "• `/remind in 2h Rapat koordinasi tim`\n"
                    "• `/remind 18:00 Kirim laporan harian`"
                )
                await self.telegram.send_message(chat_id, usage)
                return

            # Parse time and reminder text
            remind_match = re.match(r"^(in\s+\d+\s*\w+|\d+\s*\w+|\d{1,2}:\d{2})\s+(.+)$", args, re.IGNORECASE)
            if remind_match:
                time_expr = remind_match.group(1).strip()
                remind_text = remind_match.group(2).strip()
            else:
                tokens = args.split(maxsplit=1)
                time_expr = tokens[0]
                remind_text = tokens[1] if len(tokens) > 1 else ""

            if not remind_text:
                await self.telegram.send_message(chat_id, "Please provide the reminder message.")
                return

            try:
                job = await self.scheduler.schedule_reminder(
                    user_id=user_id,
                    chat_id=chat_id,
                    time_expr=time_expr,
                    text=remind_text,
                )
                await self.telegram.send_message(
                    chat_id,
                    f"⏰ Reminder set (`{job.job_id}`).\n"
                    f"• Time: {job.next_run_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"• Message: \"{job.prompt}\""
                )
            except Exception as e:
                await self.telegram.send_message(chat_id, f"Reminder error: {str(e)}")

        elif cmd == "/chart":
            if not args:
                usage = (
                    "Usage: `/chart <type> <labels> <values>`\n\n"
                    "Examples:\n"
                    "• `/chart bar Jan,Feb,Mar 10,25,18`\n"
                    "• `/chart bar Title | Jan: 10, Feb: 20`\n"
                    "• `/chart pie Python,TypeScript,Go 45,35,20`\n"
                    "• `/chart line Q1,Q2,Q3,Q4 100,150,130,210`"
                )
                await self.telegram.send_message(chat_id, usage)
                return

            chart_tool = ChartTool()

            # Handle pipe format: "/chart bar Title | Label1: 10, Label2: 20"
            if "|" in args:
                header_part, data_part = args.split("|", 1)
                h_tokens = header_part.strip().split(maxsplit=1)
                if h_tokens and h_tokens[0].lower() in ("bar", "line", "pie", "doughnut", "radar", "polararea"):
                    chart_type = h_tokens[0].lower()
                    title = h_tokens[1].strip() if len(h_tokens) > 1 else f"{chart_type.capitalize()} Chart"
                else:
                    chart_type = "bar"
                    title = header_part.strip()

                labels = []
                values = []
                for item in re.split(r"[,;\n]", data_part):
                    item = item.strip()
                    if ":" in item:
                        k, v = item.split(":", 1)
                        try:
                            labels.append(k.strip())
                            values.append(float(v.strip()))
                        except ValueError:
                            pass
                res = await chart_tool.execute({
                    "chart_type": chart_type,
                    "labels": labels,
                    "values": values,
                    "title": title,
                }, user_id=user_id)
                await self.telegram.send_message(chat_id, res.content)
                return

            tokens = args.split(maxsplit=2)
            if len(tokens) < 3:
                await self.telegram.send_message(chat_id, "Format: `/chart <type> <labels> <values>` (e.g. `/chart bar A,B,C 10,20,30`)")
                return

            chart_type = tokens[0].lower()
            labels_str = tokens[1]
            values_str = tokens[2]

            res = await chart_tool.execute({
                "chart_type": chart_type,
                "labels": labels_str,
                "values": values_str,
                "title": f"{chart_type.capitalize()} Chart",
            }, user_id=user_id)

            await self.telegram.send_message(chat_id, res.content)


        elif cmd == "/sdlc":
            if not args:
                await self.telegram.send_message(chat_id, "Usage: /sdlc <describe the feature or task to build>")
                return
            await self._run_sdlc_flow(chat_id, user_id, args)

        elif cmd == "/status":
            status_text = (
                f"Agent Status: RUNNING\n"
                f"Telegram: CONNECTED\n"
                f"Provider: {provider_name.upper()}\n"
                f"Active Model: {active_model}\n"
                f"Active Persona: {active_persona.upper()}\n"
                f"Memory: {'Enabled' if self.config.storage.memory_enabled else 'Disabled'}\n"
                f"Active Tools: {len(self.tools.list_definitions())}"
            )
            await self.telegram.send_message(chat_id, status_text)

        elif cmd == "/settings":
            settings_text = (
                f"Settings Overview:\n"
                f"- Name: {self.config.agent.name}\n"
                f"- Personality: {self.config.agent.personality}\n"
                f"- AI Provider: {provider_name.upper()}\n"
                f"- Active Model: {active_model}\n"
                f"- Temperature: {self.config.ai.temperature}"
            )
            await self.telegram.send_message(chat_id, settings_text)

        elif cmd == "/tools":
            tool_defs = self.tools.list_definitions()
            if not tool_defs:
                await self.telegram.send_message(chat_id, "No tools are currently enabled.")
                return
            lines = ["Registered Tools:"]
            for td in tool_defs:
                lines.append(f"- {td.name} [{td.permission.value}]: {td.description}")
            await self.telegram.send_message(chat_id, "\n".join(lines))

        elif cmd == "/memory":
            memories = await self.db.get_memories(user_id)
            if not memories:
                await self.telegram.send_message(chat_id, "No memories recorded yet.")
                return
            lines = ["Stored Memories:"]
            for k, v in memories.items():
                if not k.startswith("_"):
                    lines.append(f"• {k}: {v}")
            if len(lines) == 1:
                lines.append("(empty)")
            await self.telegram.send_message(chat_id, "\n".join(lines))

        elif cmd == "/reset":
            session_id = f"user_{user_id}_chat_{chat_id}"
            await self.db.clear_session(session_id)
            if user_id in self._pending_actions:
                del self._pending_actions[user_id]
            await self.telegram.send_message(chat_id, "Conversation context reset.")

        elif cmd == "/cancel":
            if user_id in self._pending_actions:
                del self._pending_actions[user_id]
                await self.telegram.send_message(chat_id, "Pending action cancelled.")
            else:
                await self.telegram.send_message(chat_id, "No action currently pending confirmation.")

        elif cmd == "/oc":
            await self._handle_oc_command(chat_id, user_id, args)

        else:
            await self.telegram.send_message(chat_id, f"Unknown command '{cmd}'. Type /help for assistance.")

    async def _handle_oc_command(self, chat_id: int, user_id: int, args: str) -> None:
        """Manage OpenCode terminal session attach, list, new, and direct messaging."""
        tokens = args.split(maxsplit=1)
        subcmd = tokens[0].lower() if tokens else ""
        subargs = tokens[1].strip() if len(tokens) > 1 else ""

        current_attached = self._user_active_oc_session.get(user_id)

        if not subcmd or subcmd == "status":
            url = await self.opencode_bridge.auto_discover_server()
            status_line = f"🟢 Connected ({url})" if url else "⚪ Offline (jalankan `opencode serve` di terminal)"
            attached_line = f"`{current_attached}`" if current_attached else "None (kirim `/oc attach <session_id>`)"
            msg = (
                f"**OpenCode Terminal Bridge**\n\n"
                f"• Server: {status_line}\n"
                f"• Attached Session: {attached_line}\n\n"
                "Perintah:\n"
                "• `/oc list` — Tampilkan semua sesi OpenCode lokal\n"
                "• `/oc attach <id>` — Hubungkan bot ke sesi terminal OpenCode\n"
                "• `/oc detach` — Lepas sesi yang sedang terhubung\n"
                "• `/oc new [title]` — Buat sesi OpenCode baru dari Telegram\n"
                "• `/oc send <prompt>` — Kirim pesan langsung ke sesi terminal"
            )
            await self.telegram.send_message(chat_id, msg)
            return

        elif subcmd == "list":
            await self.telegram.send_chat_action(chat_id, "typing")
            try:
                await self.opencode_bridge.auto_discover_server()
                sessions = await self.opencode_bridge.list_sessions()
                if not sessions:
                    await self.telegram.send_message(chat_id, "Tidak ada sesi OpenCode yang ditemukan.")
                    return
                lines = ["**Sesi OpenCode Lokal:**\n"]
                for s in sessions[:15]:
                    sid = s.get("id", "")
                    title = s.get("title") or s.get("slug") or "(untitled)"
                    model_info = s.get("model") or {}
                    m_name = model_info.get("id") or model_info.get("modelID") or "default"
                    marker = " 👈 (attached)" if sid == current_attached else ""
                    lines.append(f"• `{sid}`\n  {title} [{m_name}]{marker}")
                lines.append("\nKetik `/oc attach <id>` untuk menghubungkan sesi ke chat ini.")
                await self.telegram.send_message(chat_id, "\n".join(lines))
            except Exception as e:
                await self.telegram.send_message(chat_id, f"Gagal mengambil sesi OpenCode: {str(e)}")
            return

        elif subcmd == "attach":
            if not subargs:
                await self.telegram.send_message(chat_id, "Penggunaan: `/oc attach <session_id>`")
                return
            target_sid = subargs.strip()
            try:
                session_data = await self.opencode_bridge.get_session(target_sid)
                if not session_data:
                    await self.telegram.send_message(chat_id, f"Sesi `{target_sid}` tidak ditemukan di server OpenCode.")
                    return
                self._user_active_oc_session[user_id] = target_sid
                title = session_data.get("title") or target_sid
                await self.telegram.send_message(
                    chat_id,
                    f"✓ Sesi OpenCode `{target_sid}` ({title}) berhasil di-attach!\n\n"
                    "Sekarang, setiap pesan yang Anda kirim di chat ini akan langsung dieksekusi oleh sesi terminal OpenCode tersebut.\n"
                    "Ketik `/oc detach` untuk kembali ke mode bot standar."
                )
            except Exception as e:
                await self.telegram.send_message(chat_id, f"Gagal attach sesi: {str(e)}")
            return

        elif subcmd == "detach":
            if user_id in self._user_active_oc_session:
                old_sid = self._user_active_oc_session.pop(user_id)
                await self.telegram.send_message(chat_id, f"✓ Sesi `{old_sid}` telah dilepas. Bot kembali ke mode AI mandiri.")
            else:
                await self.telegram.send_message(chat_id, "Tidak ada sesi OpenCode yang sedang terhubung.")
            return

        elif subcmd == "new":
            title = subargs if subargs else "telegram-session"
            try:
                new_s = await self.opencode_bridge.create_session(title=title)
                new_sid = new_s.get("id")
                if new_sid:
                    self._user_active_oc_session[user_id] = new_sid
                    await self.telegram.send_message(chat_id, f"✓ Sesi OpenCode baru dibuat & di-attach: `{new_sid}` ({title}).")
                else:
                    await self.telegram.send_message(chat_id, "Sesi dibuat tetapi server tidak mengembalikan ID.")
            except Exception as e:
                await self.telegram.send_message(chat_id, f"Gagal membuat sesi: {str(e)}")
            return

        elif subcmd == "send":
            if not subargs:
                await self.telegram.send_message(chat_id, "Penggunaan: `/oc send <prompt>`")
                return
            target_sid = current_attached
            if not target_sid:
                # Auto-pick the most recent session
                sessions = await self.opencode_bridge.list_sessions()
                if sessions:
                    target_sid = sessions[0].get("id")
            if not target_sid:
                await self.telegram.send_message(chat_id, "Tidak ada sesi OpenCode aktif. Jalankan `/oc new` atau `/oc attach <id>`.")
                return

            await self.telegram.send_chat_action(chat_id, "typing")
            try:
                reply = await self.opencode_bridge.send_message(target_sid, subargs)
                clean_reply = humanize_response(reply)
                await self.telegram.send_message(chat_id, f"**OpenCode (`{target_sid}`):**\n\n{clean_reply}")
            except Exception as e:
                await self.telegram.send_message(chat_id, f"OpenCode Error: {str(e)}")
            return

        else:
            await self.telegram.send_message(chat_id, f"Perintah `/oc {subcmd}` tidak dikenal. Ketik `/oc` untuk bantuan.")

    async def _run_sdlc_flow(self, chat_id: int, user_id: int, feature_description: str) -> None:
        """Run Multi-Agent SDLC sequence with live progress edits."""
        status_msg_ids = await self.telegram.send_message(chat_id, "Starting Multi-Agent SDLC execution...")
        status_msg_id = status_msg_ids[0] if status_msg_ids else None

        async def update_progress(text: str, percentage: int):
            if status_msg_id:
                await self.telegram.edit_message_text(chat_id, status_msg_id, text)

        try:
            result = await self.sdlc.execute_feature_lifecycle(
                feature_description=feature_description,
                user_id=user_id,
                progress_callback=update_progress
            )
            report = (
                f"Multi-Agent SDLC Completed: {feature_description}\n\n"
                f"--- 1. SPECIFICATION (Planner) ---\n{result.plan_output}\n\n"
                f"--- 2. IMPLEMENTATION (Developer) ---\n{result.code_output}\n\n"
                f"--- 3. VERIFICATION (QA) ---\n{result.qa_output}"
            )
            await self.telegram.send_message(chat_id, report)
        except Exception as e:
            logger.error(f"SDLC Error: {str(e)}")
            await self.telegram.send_message(chat_id, f"Multi-Agent SDLC Error: {str(e)}")

    async def handle_callback_query(self, callback_data: Dict[str, Any]) -> None:
        """Handle inline button clicks for model selection, tool confirmations, and resets."""
        query_id = callback_data.get("id", "")
        data_str = callback_data.get("data", "")
        user = callback_data.get("from", {})
        user_id = user.get("id")
        msg = callback_data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")

        if not user_id or not chat_id:
            return

        if data_str.startswith("set_model:"):
            new_model = data_str.split(":", 1)[1]
            await self._set_user_model(user_id, new_model)
            await self.telegram.answer_callback_query(query_id, f"Model set to {new_model}")
            await self.telegram.edit_message_text(chat_id, message_id, f"✓ Active model switched to: {new_model}\n(Kirim /reset jika ingin mengosongkan riwayat sesi model sebelumnya)")

        elif data_str == "reset_session":
            session_id = f"user_{user_id}_chat_{chat_id}"
            await self.db.clear_session(session_id)
            await self.telegram.answer_callback_query(query_id, "Riwayat percakapan dibersihkan.")
            await self.telegram.edit_message_text(chat_id, message_id, "✓ Riwayat percakapan berhasil dibersihkan untuk model baru.")

        elif data_str.startswith("confirm:"):
            action_id = data_str.split(":", 1)[1]
            pending = self._pending_actions.get(action_id)

            if not pending:
                await self.telegram.answer_callback_query(query_id, "Action expired or already processed.")
                return

            await self.telegram.answer_callback_query(query_id, "Action confirmed.")
            await self.telegram.edit_message_text(chat_id, message_id, f"Executing confirmed action: {pending.description}...")
            del self._pending_actions[action_id]

            # Execute the confirmed tool
            res = await self.tools.execute(pending.tool_name, pending.arguments, user_id=user_id)
            clean_res = humanize_response(res.content)
            await self.telegram.send_message(chat_id, f"Execution Result:\n{clean_res}")

        elif data_str.startswith("cancel:"):
            action_id = data_str.split(":", 1)[1]
            if action_id in self._pending_actions:
                del self._pending_actions[action_id]
            await self.telegram.answer_callback_query(query_id, "Action cancelled.")
            await self.telegram.edit_message_text(chat_id, message_id, "Operation was cancelled.")

    async def _process_user_prompt(
        self,
        chat_id: int,
        user_id: int,
        prompt_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Execute ReAct loop or forward to an attached OpenCode terminal session."""
        # If a user has an OpenCode session attached, forward straight to the terminal
        oc_sid = self._user_active_oc_session.get(user_id)
        if oc_sid:
            await self.telegram.send_chat_action(chat_id, "typing")
            try:
                reply_text = await self.opencode_bridge.send_message(oc_sid, prompt_text)
                clean_reply = humanize_response(reply_text)
            except OpenCodeError as e:
                clean_reply = (
                    f"Gagal menghubungi sesi OpenCode `{oc_sid}`: {str(e)}\n"
                    "Ketik `/oc list` untuk daftar sesi, atau `/oc detach` untuk lepas."
                )
            except Exception as e:
                clean_reply = f"Terminal error: {str(e)}"
            await self.telegram.send_message(chat_id, clean_reply)
            return

        await self.telegram.send_chat_action(chat_id, "typing")

        session = await self.db.get_or_create_session(user_id, chat_id)
        user_message = Message(role=Role.USER, content=prompt_text, metadata=metadata or {})
        session.add_message(user_message)
        await self.db.save_message(session.session_id, user_id, user_message)

        # Get active subagent persona and exact active model for this user
        cur_persona = self._user_active_persona.get(user_id, "orchestrator")
        cur_model = await self._get_user_model(user_id)
        persona_prompt = SUBAGENT_PERSONAS.get(cur_persona, self.config.agent.system_prompt)

        # Build dynamic system prompt with explicit active model engine context
        memories = await self.db.get_memories(user_id)
        sys_prompt = (
            f"{persona_prompt}\n"
            f"Active Model: {cur_model}\n"
            f"Tone: Direct, authentic, no robotic preambles."
        )
        if memories:
            clean_mems = [f"- {k}: {v}" for k, v in memories.items() if not k.startswith("_")]
            if clean_mems:
                sys_prompt += f"\n\nKnown context about user:\n" + "\n".join(clean_mems)

        tool_defs = self.tools.list_definitions()
        max_turns = 5

        for _ in range(max_turns):
            req = CompletionRequest(
                messages=session.messages,
                system_prompt=sys_prompt,
                tools=tool_defs,
                model=cur_model,
                temperature=self.config.ai.temperature,
                max_tokens=self.config.ai.max_tokens,
            )

            try:
                ai_response = await self.ai.generate_response(req)
            except Exception as e:
                logger.error(f"AI Provider error: {str(e)}")
                await self.telegram.send_message(chat_id, f"AI Provider Error: {str(e)}")
                return

            # Case A: AI generated tool calls
            if ai_response.tool_calls:
                assistant_msg = Message(
                    role=Role.ASSISTANT,
                    content=ai_response.content or "",
                    tool_calls=ai_response.tool_calls
                )
                session.add_message(assistant_msg)
                await self.db.save_message(session.session_id, user_id, assistant_msg)

                tool_responses = []
                for tc in ai_response.tool_calls:
                    # Check if tool is destructive or requires confirmation
                    if self.tools.is_destructive(tc.name):
                        action_id = str(uuid.uuid4())[:8]
                        action_desc = f"{tc.name}({json.dumps(tc.arguments)})"
                        pending = PendingConfirmation(
                            action_id=action_id,
                            tool_name=tc.name,
                            arguments=tc.arguments,
                            risk_level="HIGH",
                            description=action_desc
                        )
                        self._pending_actions[action_id] = pending

                        markup = {
                            "inline_keyboard": [
                                [
                                    {"text": "Confirm", "callback_data": f"confirm:{action_id}"},
                                    {"text": "Cancel", "callback_data": f"cancel:{action_id}"}
                                ]
                            ]
                        }
                        prompt_msg = (
                            f"Agent requested a high-risk operation:\n\n"
                            f"Tool: {tc.name}\n"
                            f"Arguments: {json.dumps(tc.arguments, indent=2)}\n\n"
                            "Do you want to proceed?"
                        )
                        await self.telegram.send_message(chat_id, prompt_msg, reply_markup=markup)
                        return

                    # Execute safe tool immediately
                    await self.telegram.send_chat_action(chat_id, "typing")
                    tool_res = await self.tools.execute(tc.name, tc.arguments, user_id=user_id)
                    tool_responses.append(ToolResponse(
                        tool_call_id=tc.id,
                        name=tc.name,
                        content=tool_res.content,
                        is_error=tool_res.is_error
                    ))

                tool_msg = Message(role=Role.TOOL, content="", tool_responses=tool_responses)
                session.add_message(tool_msg)
                await self.db.save_message(session.session_id, user_id, tool_msg)
                continue

            # Case B: AI generated direct text response
            raw_content = ai_response.content or "No response generated."
            clean_content = humanize_response(raw_content)

            assistant_msg = Message(role=Role.ASSISTANT, content=clean_content)
            session.add_message(assistant_msg)
            await self.db.save_message(session.session_id, user_id, assistant_msg)

            await self.telegram.send_message(chat_id, clean_content)
            break

    async def run_scheduled_job(self, job: ScheduledJob) -> None:
        """Execute a due scheduled job (reminder or AI task) and push proactive notification to Telegram."""
        logger.info(f"Executing scheduled job {job.job_id} ({job.job_type}) for user {job.user_id} in chat {job.chat_id}")
        try:
            if job.is_ai_prompt:
                # Proactive AI completion
                cur_model = await self._get_user_model(job.user_id)
                sys_prompt = f"{self.config.agent.system_prompt}\nActive Model: {cur_model}"
                req = CompletionRequest(
                    messages=[Message(role=Role.USER, content=job.prompt)],
                    system_prompt=sys_prompt,
                    tools=self.tools.list_definitions(),
                    model=cur_model,
                    temperature=self.config.ai.temperature,
                    max_tokens=self.config.ai.max_tokens,
                )
                ai_res = await self.ai.generate_response(req)
                content = humanize_response(ai_res.content or "No response generated.")
                msg_text = f"🔔 **Scheduled AI Task Update:**\n\n{content}"
                await self.telegram.send_message(job.chat_id, msg_text)
            else:
                # Plain reminder
                msg_text = f"⏰ **Reminder:**\n{job.prompt}"
                await self.telegram.send_message(job.chat_id, msg_text)

            # Record completion / recalculate next occurrence
            await self.scheduler.record_job_completion(job)
        except Exception as e:
            logger.error(f"Error executing scheduled job {job.job_id}: {str(e)}")
