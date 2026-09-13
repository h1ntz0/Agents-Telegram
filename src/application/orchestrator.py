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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from src.application.config_manager import RootConfig
from src.infrastructure.opencode.bridge import OpenCodeBridge, OpenCodeError
from src.infrastructure.opencode.mirror import OpenCodeMirror
from src.application.multiagent_sdlc import MultiAgentSDLC
from src.domain.agent import AgentState, Message, PendingConfirmation, Role, Session, ToolCall, ToolResponse
from src.domain.provider import AIProvider, CompletionRequest, PROVIDER_MODELS_CATALOG, normalize_provider_name
from src.application.provider_registry import (
    ProviderCredentialsMissing,
    build_provider,
    list_provider_names,
    provider_is_configured,
    resolve_provider_credentials,
)
from src.infrastructure.ai.model_discovery import fetch_available_models
from src.infrastructure.database.sqlite_db import SqliteDatabase
from src.infrastructure.i18n import (
    available_languages,
    is_supported_language,
    language_name,
    normalize_language,
    t,
)
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
        self._pending_actions: Dict[str, PendingConfirmation] = {}
        self._user_active_persona: Dict[int, str] = {}
        self._user_active_model: Dict[int, str] = {}
        self._user_active_provider: Dict[int, str] = {}
        self._user_language: Dict[int, str] = {}
        self._started_at = datetime.now(timezone.utc)
        self._provider_cache: Dict[str, AIProvider] = {
            normalize_provider_name(config.ai.provider): ai_provider
        }
        self._user_active_oc_session: Dict[int, str] = {}
        self._oc_mirrors: Dict[int, OpenCodeMirror] = {}
        self.opencode_bridge = OpenCodeBridge(
            base_url=getattr(config.ai, "opencode_server_url", "http://127.0.0.1:4096")
        )

    def _get_oc_mirror(self, user_id: int, chat_id: int) -> Optional[OpenCodeMirror]:
        """Return the existing OpenCodeMirror for the attached session or create+store one."""
        sid = self._user_active_oc_session.get(user_id)
        if not sid:
            return None
        existing = self._oc_mirrors.get(user_id)
        if (
            existing is not None
            and getattr(existing, "session_id", sid) == sid
            and getattr(existing, "chat_id", chat_id) == chat_id
        ):
            return existing
        mirror = OpenCodeMirror(
            bridge=self.opencode_bridge,
            telegram=self.telegram,
            session_id=sid,
            chat_id=chat_id,
        )
        self._oc_mirrors[user_id] = mirror
        return mirror

    async def _get_user_provider(self, user_id: int) -> str:
        """Return the user's active provider id (cache -> SQLite -> configured default)."""
        if user_id in self._user_active_provider:
            return self._user_active_provider[user_id]
        memories = await self.db.get_memories(user_id)
        saved = memories.get("_active_provider")
        provider_name = normalize_provider_name(saved or self.config.ai.provider)
        self._user_active_provider[user_id] = provider_name
        return provider_name

    async def _set_user_provider(self, user_id: int, provider_name: str) -> None:
        """Persist the user's active provider so it survives restarts."""
        canonical = normalize_provider_name(provider_name)
        self._user_active_provider[user_id] = canonical
        await self.db.set_memory(user_id, "_active_provider", canonical)

    async def _get_active_ai_provider(self, user_id: int) -> AIProvider:
        """Return a cached AIProvider for the user's active provider (built on first use)."""
        provider_name = await self._get_user_provider(user_id)
        if provider_name not in self._provider_cache:
            self._provider_cache[provider_name] = build_provider(provider_name, self.config)
        return self._provider_cache[provider_name]

    async def _get_user_model(self, user_id: int) -> str:
        """Retrieve the model for the user's ACTIVE provider (per-provider isolation)."""
        provider_name = await self._get_user_provider(user_id)
        cache_key = f"{user_id}:{provider_name}"
        if cache_key in self._user_active_model:
            return self._user_active_model[cache_key]

        memories = await self.db.get_memories(user_id)
        saved_model = memories.get(f"_active_model:{provider_name}")
        if saved_model:
            self._user_active_model[cache_key] = saved_model
            return saved_model

        try:
            cred = resolve_provider_credentials(provider_name, self.config)
            if cred.model:
                return cred.model
        except ProviderCredentialsMissing:
            pass
        catalog = PROVIDER_MODELS_CATALOG.get(provider_name) or []
        return (catalog[0] if catalog else "") or self.config.ai.model

    async def _set_user_model(self, user_id: int, model_name: str) -> None:
        """Persist the model under the user's active provider (per-provider isolation)."""
        provider_name = await self._get_user_provider(user_id)
        clean_name = model_name.strip()
        self._user_active_model[f"{user_id}:{provider_name}"] = clean_name
        await self.db.set_memory(user_id, f"_active_model:{provider_name}", clean_name)

    async def _get_user_language(self, user_id: int) -> str:
        """Return the user's UI language (cache -> SQLite -> deployed default)."""
        if user_id in self._user_language:
            return self._user_language[user_id]
        memories = await self.db.get_memories(user_id)
        code = normalize_language(memories.get("_language") or self.config.app.ui_lang)
        self._user_language[user_id] = code
        return code

    async def _set_user_language(self, user_id: int, language: str) -> str:
        """Persist the user's UI language so it survives restarts."""
        code = normalize_language(language)
        self._user_language[user_id] = code
        await self.db.set_memory(user_id, "_language", code)
        return code

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
            await self.telegram.send_message(chat_id, t("bot.unauthorized"))
            return

        lang = await self._get_user_language(user_id)

        # 2. Rate limiting check
        if not self.rate_limiter.is_allowed(user_id):
            await self.telegram.send_message(chat_id, t("bot.rate_limited", lang))
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
                processed_prompt = caption if caption else t("bot.photo.default_prompt", lang)
            except Exception as e:
                logger.error(f"Failed to process photo: {str(e)}")
                processed_prompt = t("bot.photo.failed", lang, error=str(e), caption=caption or "")

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
                        snippet += t("bot.document.truncated", lang)
                    user_req = caption or t("bot.document.default_prompt", lang)
                    processed_prompt = t(
                        "bot.document.preview", lang,
                        name=file_name, mime=mime_type, size=file_size,
                        content=snippet, request=user_req,
                    )
                else:
                    processed_prompt = t(
                        "bot.document.binary", lang,
                        name=file_name, mime=mime_type, size=file_size,
                        caption=caption or "",
                    )
            except Exception as e:
                logger.error(f"Failed to process document: {str(e)}")
                processed_prompt = t(
                    "bot.document.error", lang,
                    name=file_name, error=str(e), caption=caption or "",
                )

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
                    await self.telegram.send_message(
                        chat_id,
                        t("bot.voice.transcribed", lang, duration=duration, text=transcription),
                    )
                else:
                    await self.telegram.send_message(
                        chat_id,
                        t("bot.voice.no_transcription", lang, duration=duration, size=file_size),
                    )
                    return
            except Exception as e:
                logger.error(f"Failed to process voice note: {str(e)}")
                await self.telegram.send_message(
                    chat_id,
                    t("bot.voice.failed", lang, duration=duration, error=str(e)),
                )
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
        provider_name = await self._get_user_provider(user_id)
        lang = await self._get_user_language(user_id)

        def L(key: str, **kwargs: Any) -> str:
            return t(key, lang, **kwargs)

        if cmd == "/start":
            msg = L(
                "bot.start.body",
                name=self.config.agent.name,
                provider=provider_name.upper(),
                model=active_model,
                persona=active_persona.upper(),
                language=language_name(lang),
            )
            await self.telegram.send_message(chat_id, msg)

        elif cmd == "/help":
            await self.telegram.send_message(chat_id, L("bot.help.body"))

        elif cmd == "/model":
            if args:
                await self._set_user_model(user_id, args)
                markup = {
                    "inline_keyboard": [
                        [{"text": L("bot.model.clear_button"), "callback_data": "reset_session"}]
                    ]
                }
                await self.telegram.send_message(
                    chat_id,
                    L("bot.model.switched", provider=provider_name.upper(), model=args),
                    reply_markup=markup
                )
                return

            # Dynamically discover live models for the ACTIVE provider using its own credentials
            try:
                active_cred = resolve_provider_credentials(provider_name, self.config)
                cred_key, cred_url = active_cred.api_key, active_cred.base_url
            except ProviderCredentialsMissing:
                cred_key, cred_url = "", ""
            catalog_models = await fetch_available_models(
                provider_name=provider_name,
                api_key=cred_key,
                base_url=cred_url,
            )
            if not catalog_models:
                catalog_models = PROVIDER_MODELS_CATALOG.get(provider_name, [])

            # Cap inline keyboard buttons to 15 to avoid overwhelming Telegram UI
            buttons: List[List[Dict[str, str]]] = []
            for m in catalog_models[:15]:
                buttons.append([{"text": f"Select {m}", "callback_data": f"set_model:{m}"}])

            markup = {"inline_keyboard": buttons} if buttons else None
            msg = L("bot.model.header", provider=provider_name.upper(), model=active_model)
            await self.telegram.send_message(chat_id, msg, reply_markup=markup)

        elif cmd == "/provider":
            if not args:
                lines = [L("bot.provider.header"), ""]
                for name in list_provider_names():
                    marker = "\u2705" if name == provider_name else "\u2022"
                    status = L("bot.provider.configured") if provider_is_configured(name, self.config) else L("bot.provider.missing")
                    lines.append(f"{marker} {name} ({status})")
                lines.append("")
                lines.append(L("bot.provider.switch_hint"))
                lines.append(L("bot.provider.credentials_hint"))
                await self.telegram.send_message(chat_id, "\n".join(lines))
                return

            requested = normalize_provider_name(args)
            if requested not in list_provider_names():
                await self.telegram.send_message(
                    chat_id,
                    L("bot.provider.unknown", provider=args, options=", ".join(list_provider_names())),
                )
                return
            try:
                resolve_provider_credentials(requested, self.config)
            except ProviderCredentialsMissing as e:
                await self.telegram.send_message(chat_id, f"\u26a0\ufe0f {e}")
                return

            await self._set_user_provider(user_id, requested)
            self._provider_cache.pop(requested, None)
            active_model = await self._get_user_model(user_id)
            await self.telegram.send_message(
                chat_id,
                L("bot.provider.switched", provider=requested.upper(), model=active_model),
            )

        elif cmd == "/agent":
            if not args:
                cur = self._user_active_persona.get(user_id, "orchestrator")
                avail = ", ".join(SUBAGENT_PERSONAS.keys())
                await self.telegram.send_message(
                    chat_id,
                    L("bot.agent.current", persona=cur, options=avail),
                )
                return
            target = args.lower()
            if target in SUBAGENT_PERSONAS:
                self._user_active_persona[user_id] = target
                await self.telegram.send_message(chat_id, L("bot.agent.switched", persona=target.upper()))
            else:
                await self.telegram.send_message(
                    chat_id,
                    L("bot.agent.unknown", persona=target, options=", ".join(SUBAGENT_PERSONAS.keys())),
                )

        elif cmd == "/schedule":
            if not args:
                await self.telegram.send_message(chat_id, L("bot.schedule.usage"))
                return

            if args.lower() == "list":
                jobs = await self.scheduler.list_jobs(user_id=user_id, active_only=True)
                if not jobs:
                    await self.telegram.send_message(chat_id, L("bot.schedule.none"))
                    return
                lines = [L("bot.schedule.header"), ""]
                for j in jobs:
                    lines.append(L(
                        "bot.schedule.entry",
                        job_id=j.job_id,
                        job_type=j.job_type,
                        prompt=j.prompt,
                        next_run=self.scheduler.format_time(j.next_run_at),
                    ))
                await self.telegram.send_message(chat_id, "\n".join(lines))
                return

            if args.lower().startswith("cancel "):
                job_id = args.split(maxsplit=1)[1].strip()
                cancelled = await self.scheduler.cancel_job(job_id, user_id=user_id)
                if cancelled:
                    await self.telegram.send_message(chat_id, L("bot.schedule.cancelled", job_id=job_id))
                else:
                    await self.telegram.send_message(chat_id, L("bot.schedule.cancel_missing", job_id=job_id))
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
                await self.telegram.send_message(chat_id, L("bot.schedule.need_prompt"))
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
                    L(
                        "bot.schedule.created",
                        job_id=job.job_id,
                        schedule_type=job.schedule_type.upper(),
                        schedule_value=job.schedule_value,
                        next_run=self.scheduler.format_time(job.next_run_at),
                        prompt=job.prompt,
                    ),
                )
            except Exception as e:
                await self.telegram.send_message(chat_id, L("bot.schedule.error", error=str(e)))

        elif cmd == "/remind":
            if not args:
                await self.telegram.send_message(chat_id, L("bot.remind.usage"))
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
                await self.telegram.send_message(chat_id, L("bot.remind.need_text"))
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
                    L(
                        "bot.remind.set",
                        job_id=job.job_id,
                        next_run=self.scheduler.format_time(job.next_run_at),
                        prompt=job.prompt,
                    ),
                )
            except Exception as e:
                await self.telegram.send_message(chat_id, L("bot.remind.error", error=str(e)))

        elif cmd == "/chart":
            if not args:
                await self.telegram.send_message(chat_id, L("bot.chart.usage"))
                return

            chart_tool = ChartTool()

            # Handle pipe format: "/chart bar Title | Label1: 10, Label2: 20"
            if "|" in args:
                header_part, data_part = args.split("|", 1)
                h_tokens = header_part.strip().split(maxsplit=1)
                if h_tokens and h_tokens[0].lower() in ("bar", "line", "pie", "doughnut", "radar", "polararea"):
                    chart_type = h_tokens[0].lower()
                    title = h_tokens[1].strip() if len(h_tokens) > 1 else L("bot.chart.title", chart_type=chart_type.capitalize())
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
                await self.telegram.send_message(chat_id, L("bot.chart.format"))
                return

            chart_type = tokens[0].lower()
            labels_str = tokens[1]
            values_str = tokens[2]

            res = await chart_tool.execute({
                "chart_type": chart_type,
                "labels": labels_str,
                "values": values_str,
                "title": L("bot.chart.title", chart_type=chart_type.capitalize()),
            }, user_id=user_id)

            await self.telegram.send_message(chat_id, res.content)


        elif cmd == "/sdlc":
            if not args:
                await self.telegram.send_message(chat_id, L("bot.sdlc.usage"))
                return
            await self._run_sdlc_flow(chat_id, user_id, args)

        elif cmd == "/status":
            await self.telegram.send_message(chat_id, L(
                "bot.status.body",
                provider=provider_name.upper(),
                model=active_model,
                persona=active_persona.upper(),
                language=language_name(lang),
                memory=L("wizard.review.enabled") if self.config.storage.memory_enabled else L("wizard.review.disabled"),
                tools=len(self.tools.list_definitions()),
            ))

        elif cmd == "/settings":
            await self.telegram.send_message(chat_id, L(
                "bot.settings.body",
                name=self.config.agent.name,
                personality=self.config.agent.personality,
                provider=provider_name.upper(),
                model=active_model,
                temperature=self.config.ai.temperature,
            ))

        elif cmd == "/tools":
            tool_defs = self.tools.list_definitions()
            if not tool_defs:
                await self.telegram.send_message(chat_id, L("bot.tools.none"))
                return
            lines = [L("bot.tools.header")]
            for td in tool_defs:
                lines.append(f"- {td.name} [{td.permission.value}]: {td.description}")
            await self.telegram.send_message(chat_id, "\n".join(lines))

        elif cmd == "/memory":
            if not self.config.storage.memory_enabled:
                await self.telegram.send_message(chat_id, L("bot.memory.disabled"))
                return
            memories = await self.db.get_memories(user_id)
            visible = {k: v for k, v in memories.items() if not k.startswith("_")}
            if not visible:
                await self.telegram.send_message(chat_id, L("bot.memory.none"))
                return
            lines = [L("bot.memory.header")]
            for k, v in visible.items():
                lines.append(f"• {k}: {v}")
            await self.telegram.send_message(chat_id, "\n".join(lines))

        elif cmd == "/lang":
            if not args:
                await self.telegram.send_message(chat_id, L(
                    "bot.lang.current",
                    language=language_name(lang),
                    options=", ".join(available_languages()),
                ))
                return
            if not is_supported_language(args):
                await self.telegram.send_message(chat_id, L(
                    "bot.lang.unknown",
                    value=args,
                    options=", ".join(available_languages()),
                ))
                return
            new_lang = await self._set_user_language(user_id, args)
            await self.telegram.send_message(
                chat_id,
                t("bot.lang.switched", new_lang, language=language_name(new_lang)),
            )

        elif cmd == "/reset":
            session_id = f"user_{user_id}_chat_{chat_id}"
            await self.db.clear_session(session_id)
            self._drop_pending_actions(user_id)
            await self.telegram.send_message(chat_id, L("bot.reset.done"))

        elif cmd == "/cancel":
            removed = self._drop_pending_actions(user_id)
            if removed:
                await self.telegram.send_message(chat_id, L("bot.cancel.done"))
            else:
                await self.telegram.send_message(chat_id, L("bot.cancel.none"))

        elif cmd == "/admin":
            await self._handle_admin_command(chat_id, user_id, args, lang)

        elif cmd == "/oc":
            await self._handle_oc_command(chat_id, user_id, args)

        else:
            await self.telegram.send_message(chat_id, L("bot.unknown_command", command=cmd))

    def _drop_pending_actions(self, user_id: int) -> int:
        """Discard every confirmation owned by a user and return how many were removed."""
        owned = [aid for aid, pending in self._pending_actions.items() if pending.user_id == user_id]
        for action_id in owned:
            del self._pending_actions[action_id]
        return len(owned)

    async def _handle_admin_command(self, chat_id: int, user_id: int, args: str, lang: str) -> None:
        """Show operator diagnostics. Restricted to the ADMIN_TELEGRAM_USERS list."""
        admins = self.config.telegram.admin_users
        if not admins:
            await self.telegram.send_message(chat_id, t("bot.admin.unconfigured", lang))
            return
        if not self.auth.is_admin(user_id):
            await self.telegram.send_message(chat_id, t("bot.admin.denied", lang))
            return
        uptime = datetime.now(timezone.utc) - self._started_at
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        scheduled = len(await self.scheduler.list_jobs(active_only=True))
        await self.telegram.send_message(chat_id, t(
            "bot.admin.stats", lang,
            uptime=f"{hours}h {minutes}m {seconds}s",
            users=len(self._user_language),
            providers=len(self._provider_cache),
            scheduled=scheduled,
            pending=len(self._pending_actions),
            tools=len(self.tools.list_definitions()),
            timezone=getattr(self.scheduler.tz, "key", str(self.scheduler.tz)),
            database=self.config.storage.database_path,
        ))

    async def _handle_oc_command(self, chat_id: int, user_id: int, args: str) -> None:
        """Manage OpenCode terminal session attach, list, new, and direct messaging."""
        tokens = args.split(maxsplit=1)
        subcmd = tokens[0].lower() if tokens else ""
        subargs = tokens[1].strip() if len(tokens) > 1 else ""

        lang = await self._get_user_language(user_id)

        def L(key: str, **kwargs: Any) -> str:
            return t(key, lang, **kwargs)

        current_attached = self._user_active_oc_session.get(user_id)

        if not subcmd or subcmd == "status":
            url = await self.opencode_bridge.auto_discover_server()
            status_line = L("oc.connected", url=url) if url else L("oc.offline")
            attached_line = f"`{current_attached}`" if current_attached else L("oc.none_attached")
            await self.telegram.send_message(chat_id, L(
                "oc.help", status=status_line, session=attached_line,
            ))
            return

        elif subcmd == "list":
            await self.telegram.send_chat_action(chat_id, "typing")
            try:
                await self.opencode_bridge.auto_discover_server()
                sessions = await self.opencode_bridge.list_sessions()
                if not sessions:
                    await self.telegram.send_message(chat_id, L("oc.none_found"))
                    return
                lines = [L("oc.list_header"), ""]
                for s in sessions[:15]:
                    sid = s.get("id", "")
                    title = s.get("title") or s.get("slug") or "(untitled)"
                    model_info = s.get("model") or {}
                    m_name = model_info.get("id") or model_info.get("modelID") or "default"
                    marker = " 👈 (attached)" if sid == current_attached else ""
                    lines.append(f"• `{sid}`\n  {title} [{m_name}]{marker}")
                lines.append("")
                lines.append(L("oc.list_attach_hint"))
                await self.telegram.send_message(chat_id, "\n".join(lines))
            except Exception as e:
                await self.telegram.send_message(chat_id, L("oc.list_failed", error=str(e)))
            return

        elif subcmd == "attach":
            if not subargs:
                await self.telegram.send_message(chat_id, L("oc.attach_usage"))
                return
            target_sid = subargs.strip()
            try:
                session_data = await self.opencode_bridge.get_session(target_sid)
                if not session_data:
                    await self.telegram.send_message(chat_id, L("oc.attach_missing", session=target_sid))
                    return
                self._user_active_oc_session[user_id] = target_sid
                self._get_oc_mirror(user_id, chat_id)
                title = session_data.get("title") or target_sid
                await self.telegram.send_message(
                    chat_id,
                    L("oc.attach_done", session=target_sid, title=title),
                )
            except Exception as e:
                await self.telegram.send_message(chat_id, L("oc.attach_failed", error=str(e)))
            return

        elif subcmd == "detach":
            if user_id in self._oc_mirrors:
                mirror = self._oc_mirrors.pop(user_id)
                try:
                    await mirror.stop()
                except Exception as e:
                    logger.warning(f"Error stopping mirror on detach: {e}")
            if user_id in self._user_active_oc_session:
                old_sid = self._user_active_oc_session.pop(user_id)
                await self.telegram.send_message(chat_id, L("oc.detached", session=old_sid))
            else:
                await self.telegram.send_message(chat_id, L("oc.detach_none"))
            return

        elif subcmd == "new":
            title = subargs if subargs else "telegram-session"
            try:
                new_s = await self.opencode_bridge.create_session(title=title)
                new_sid = new_s.get("id")
                if new_sid:
                    self._user_active_oc_session[user_id] = new_sid
                    self._get_oc_mirror(user_id, chat_id)
                    await self.telegram.send_message(chat_id, L("oc.new_done", session=new_sid, title=title))
                else:
                    await self.telegram.send_message(chat_id, L("oc.new_no_id"))
            except Exception as e:
                await self.telegram.send_message(chat_id, L("oc.new_failed", error=str(e)))
            return

        elif subcmd == "send":
            if not subargs:
                await self.telegram.send_message(chat_id, L("oc.send_usage"))
                return
            target_sid = current_attached
            if not target_sid:
                # Auto-pick the most recent session
                sessions = await self.opencode_bridge.list_sessions()
                if sessions:
                    target_sid = sessions[0].get("id")
            if not target_sid:
                await self.telegram.send_message(chat_id, L("oc.send_none"))
                return

            await self.telegram.send_chat_action(chat_id, "typing")
            try:
                reply = await self.opencode_bridge.send_message(target_sid, subargs)
                clean_reply = humanize_response(reply)
                await self.telegram.send_message(chat_id, f"{L('oc.send_header', session=target_sid)}\n\n{clean_reply}")
            except Exception as e:
                await self.telegram.send_message(chat_id, L("oc.error", error=str(e)))
            return

        elif subcmd == "stop":
            mirror = self._get_oc_mirror(user_id, chat_id)
            if mirror is not None:
                await mirror.stop()
            elif current_attached:
                try:
                    await self.opencode_bridge.interrupt(current_attached)
                except Exception:
                    pass
            await self.telegram.send_message(chat_id, L("oc.stopped"))
            return

        elif subcmd == "model":
            if not current_attached:
                await self.telegram.send_message(chat_id, L("oc.send_none"))
                return
            if not subargs:
                await self.telegram.send_message(chat_id, L("oc.model_usage"))
                return
            m_parts = subargs.split(maxsplit=1)
            model_id = m_parts[0].strip()
            provider_id = m_parts[1].strip() if len(m_parts) > 1 else "9router"
            try:
                ok = await self.opencode_bridge.set_model(current_attached, model_id, provider_id)
                if ok:
                    await self.telegram.send_message(
                        chat_id,
                        L("oc.model_done", session=current_attached, model=model_id, provider=provider_id),
                    )
                else:
                    await self.telegram.send_message(chat_id, L("oc.model_failed"))
            except Exception as e:
                await self.telegram.send_message(chat_id, L("oc.model_error", error=str(e)))
            return

        elif subcmd == "agent":
            if not current_attached:
                await self.telegram.send_message(chat_id, L("oc.send_none"))
                return
            if not subargs:
                await self.telegram.send_message(chat_id, L("oc.agent_usage"))
                return
            agent_name = subargs.strip()
            try:
                ok = await self.opencode_bridge.set_agent(current_attached, agent_name)
                if ok:
                    await self.telegram.send_message(
                        chat_id,
                        L("oc.agent_done", session=current_attached, agent=agent_name),
                    )
                else:
                    await self.telegram.send_message(chat_id, L("oc.agent_failed"))
            except Exception as e:
                await self.telegram.send_message(chat_id, L("oc.agent_error", error=str(e)))
            return

        elif subcmd in ("agents", "models", "commands", "skills"):
            await self.telegram.send_chat_action(chat_id, "typing")
            try:
                if subcmd == "agents":
                    items = await self.opencode_bridge.list_agents()
                    title = "OpenCode Agents"
                elif subcmd == "models":
                    items = await self.opencode_bridge.list_models()
                    title = "OpenCode Models"
                elif subcmd == "commands":
                    items = await self.opencode_bridge.list_commands()
                    title = "OpenCode Commands"
                else:
                    items = await self.opencode_bridge.list_skills()
                    title = "OpenCode Skills"

                if not items:
                    await self.telegram.send_message(chat_id, L("oc.none_items", kind=subcmd))
                    return

                lines = [f"**{title}:**", ""]
                for item in items[:20]:
                    if isinstance(item, dict):
                        item_id = item.get("id") or item.get("name") or item.get("title") or str(item)
                        desc = item.get("description")
                        if desc:
                            lines.append(f"• `{item_id}` — {desc[:80]}")
                        else:
                            lines.append(f"• `{item_id}`")
                    else:
                        lines.append(f"• `{item}`")
                await self.telegram.send_message(chat_id, "\n".join(lines))
            except Exception as e:
                await self.telegram.send_message(chat_id, L("oc.list_failed_items", kind=subcmd, error=str(e)))
            return

        elif subcmd == "diff":
            if not current_attached:
                await self.telegram.send_message(chat_id, L("oc.diff_none"))
                return
            diff_fn = getattr(self.opencode_bridge, "get_diff", None) or getattr(self.opencode_bridge, "diff", None)
            if callable(diff_fn):
                try:
                    diff_res = await diff_fn(current_attached)
                    text_diff = str(diff_res) if diff_res else L("oc.diff_empty")
                    await self.telegram.send_message(
                        chat_id,
                        f"{L('oc.diff_header', session=current_attached)}\n\n`{text_diff}`",
                    )
                except Exception as e:
                    await self.telegram.send_message(chat_id, L("oc.diff_failed", error=str(e)))
            else:
                await self.telegram.send_message(chat_id, L("oc.diff_unsupported"))
            return

        else:
            await self.telegram.send_message(chat_id, L("oc.unknown", subcommand=subcmd))

    async def _run_sdlc_flow(self, chat_id: int, user_id: int, feature_description: str) -> None:
        """Run Multi-Agent SDLC sequence with live progress edits."""
        lang = await self._get_user_language(user_id)
        status_msg_ids = await self.telegram.send_message(chat_id, t("bot.sdlc.starting", lang))
        status_msg_id = status_msg_ids[0] if status_msg_ids else None

        async def update_progress(text: str, percentage: int):
            if status_msg_id:
                await self.telegram.edit_message_text(chat_id, status_msg_id, text)

        try:
            active_ai = await self._get_active_ai_provider(user_id)
            sdlc = MultiAgentSDLC(ai_provider=active_ai, tool_registry=self.tools)
            result = await sdlc.execute_feature_lifecycle(
                feature_description=feature_description,
                user_id=user_id,
                progress_callback=update_progress
            )
            await self.telegram.send_message(chat_id, t(
                "bot.sdlc.report", lang,
                feature=feature_description,
                plan=result.plan_output,
                code=result.code_output,
                qa=result.qa_output,
            ))
        except Exception as e:
            logger.error(f"SDLC Error: {str(e)}")
            await self.telegram.send_message(chat_id, t("bot.sdlc.error", lang, error=str(e)))

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

        lang = await self._get_user_language(user_id)

        if data_str.startswith("set_model:"):
            new_model = data_str.split(":", 1)[1]
            await self._set_user_model(user_id, new_model)
            await self.telegram.answer_callback_query(query_id, t("bot.callback.model_set", lang, model=new_model))
            await self.telegram.edit_message_text(
                chat_id, message_id, t("bot.callback.model_switched", lang, model=new_model)
            )

        elif data_str == "reset_session":
            session_id = f"user_{user_id}_chat_{chat_id}"
            await self.db.clear_session(session_id)
            await self.telegram.answer_callback_query(query_id, t("bot.callback.history_cleared", lang))
            await self.telegram.edit_message_text(chat_id, message_id, t("bot.callback.history_cleared_body", lang))

        elif data_str.startswith("confirm:"):
            action_id = data_str.split(":", 1)[1]
            pending = self._pending_actions.get(action_id)

            if not pending:
                await self.telegram.answer_callback_query(query_id, t("bot.confirm.expired", lang))
                return

            await self.telegram.answer_callback_query(query_id, t("bot.confirm.confirmed", lang))
            await self.telegram.edit_message_text(
                chat_id, message_id, t("bot.confirm.executing", lang, description=pending.description)
            )
            del self._pending_actions[action_id]

            # Execute the confirmed tool
            res = await self.tools.execute(pending.tool_name, pending.arguments, user_id=user_id)
            clean_res = humanize_response(res.content)
            await self.telegram.send_message(chat_id, t("bot.confirm.result", lang, content=clean_res))

        elif data_str.startswith("cancel:"):
            action_id = data_str.split(":", 1)[1]
            if action_id in self._pending_actions:
                del self._pending_actions[action_id]
            await self.telegram.answer_callback_query(query_id, t("bot.confirm.cancelled", lang))
            await self.telegram.edit_message_text(chat_id, message_id, t("bot.confirm.cancelled_body", lang))

        elif data_str.startswith("ocstop:"):
            try:
                sid = data_str.split(":", 1)[1].strip()
                found_mirror = None
                for m in self._oc_mirrors.values():
                    if getattr(m, "session_id", None) == sid:
                        found_mirror = m
                        break
                if found_mirror is not None:
                    await found_mirror.stop()
                elif hasattr(self.opencode_bridge, "interrupt"):
                    try:
                        await self.opencode_bridge.interrupt(sid)
                    except Exception:
                        pass
                await self.telegram.answer_callback_query(query_id, t("oc.stopped", lang))
                if message_id:
                    await self.telegram.edit_message_text(chat_id, message_id, t("oc.stopped", lang))
            except Exception as e:
                logger.error(f"Error handling ocstop callback: {e}")

        elif data_str.startswith("ocperm:"):
            try:
                parts = data_str.split(":")
                sid = None
                reqid = None
                reply = None
                if len(parts) == 3:
                    _, token, reply = parts
                    for m in self._oc_mirrors.values():
                        resolver = getattr(m, "resolve_permission_token", None)
                        resolved = resolver(token) if resolver else None
                        if resolved:
                            sid = getattr(m, "session_id", None)
                            reqid = resolved
                            break
                elif len(parts) == 4:
                    _, sid, reqid, reply = parts
                if reply in {"once", "always", "reject"} and sid and reqid:
                    await self.opencode_bridge.reply_permission(sid, reqid, reply)
                    await self.telegram.answer_callback_query(query_id, f"Permission: {reply}")
                    reply_labels = {
                        "once": t("oc.permission_once", lang),
                        "always": t("oc.permission_always", lang),
                        "reject": t("oc.permission_reject", lang),
                    }
                    if message_id:
                        await self.telegram.edit_message_text(
                            chat_id, message_id, reply_labels.get(reply, reply)
                        )
                else:
                    await self.telegram.answer_callback_query(query_id, t("oc.permission_invalid", lang))
            except Exception as e:
                logger.error(f"Error handling ocperm callback: {e}")

    async def _process_user_prompt(
        self,
        chat_id: int,
        user_id: int,
        prompt_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Execute ReAct loop or forward to an attached OpenCode terminal session."""
        lang = await self._get_user_language(user_id)
        mirror = self._get_oc_mirror(user_id, chat_id)
        if mirror is not None:
            if mirror.is_running:
                await self.telegram.send_message(chat_id, t("oc.busy", lang))
                return
            asyncio.create_task(mirror.run_prompt(prompt_text))
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
        sys_prompt = (
            f"{persona_prompt}\n"
            f"Active Model: {cur_model}\n"
            f"Tone: Direct, authentic, no robotic preambles."
        )
        if self.config.storage.memory_enabled:
            memories = await self.db.get_memories(user_id)
            clean_mems = [f"- {k}: {v}" for k, v in memories.items() if not k.startswith("_")]
            if clean_mems:
                sys_prompt += "\n\nKnown context about user:\n" + "\n".join(clean_mems)

        tool_defs = self.tools.list_definitions()
        max_turns = 5
        active_ai = await self._get_active_ai_provider(user_id)

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
                ai_response = await active_ai.generate_response(req)
            except Exception as e:
                logger.error(f"AI Provider error: {str(e)}")
                await self.telegram.send_message(chat_id, t("bot.ai_error", lang, error=str(e)))
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
                    if self.tools.needs_confirmation(tc.name):
                        action_id = str(uuid.uuid4())[:8]
                        action_desc = f"{tc.name}({json.dumps(tc.arguments)})"
                        pending = PendingConfirmation(
                            action_id=action_id,
                            tool_name=tc.name,
                            arguments=tc.arguments,
                            risk_level="HIGH",
                            description=action_desc,
                            user_id=user_id,
                        )
                        self._pending_actions[action_id] = pending

                        markup = {
                            "inline_keyboard": [
                                [
                                    {"text": t("bot.confirm.confirm_button", lang), "callback_data": f"confirm:{action_id}"},
                                    {"text": t("bot.confirm.cancel_button", lang), "callback_data": f"cancel:{action_id}"}
                                ]
                            ]
                        }
                        prompt_msg = t(
                            "bot.confirm.prompt", lang,
                            tool=tc.name,
                            arguments=json.dumps(tc.arguments, indent=2),
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
                ai_res = await (await self._get_active_ai_provider(job.user_id)).generate_response(req)
                content = humanize_response(ai_res.content or "No response generated.")
                msg_text = t("bot.job.ai_update", await self._get_user_language(job.user_id), content=content)
                await self.telegram.send_message(job.chat_id, msg_text)
            else:
                # Plain reminder
                msg_text = t("bot.job.reminder", await self._get_user_language(job.user_id), prompt=job.prompt)
                await self.telegram.send_message(job.chat_id, msg_text)

            # Record completion / recalculate next occurrence
            await self.scheduler.record_job_completion(job)
        except Exception as e:
            logger.error(f"Error executing scheduled job {job.job_id}: {str(e)}")
