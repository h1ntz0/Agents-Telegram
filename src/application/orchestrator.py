"""Central Agent Orchestrator handling message routing, ReAct loop, multi-agent SDLC delegation, and Humanizer output."""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional
from src.application.config_manager import RootConfig
from src.application.multiagent_sdlc import MultiAgentSDLC
from src.domain.agent import AgentState, Message, PendingConfirmation, Role, Session, ToolCall, ToolResponse
from src.domain.provider import AIProvider, CompletionRequest
from src.infrastructure.database.sqlite_db import SqliteDatabase
from src.infrastructure.security.humanizer import humanize_response
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SUBAGENT_PERSONAS = {
    "orchestrator": "You are the Lead Coordinator Agent. You oversee task decomposition and synthesize inputs from specialized agents.",
    "researcher": "You are the Research & Discovery Agent. Search the web, summarize technical docs, and provide verifiable facts.",
    "coder": "You are the Senior Software Engineer Agent. Write clean, working, minimal production code.",
    "qa": "You are the QA & Security Agent. Check for boundary conditions, security vulnerabilities, and verify test assertions.",
}


class AgentOrchestrator:
    """Orchestrates agent execution flow between Telegram, AI provider, tools, SQLite persistence, and Multi-Agent SDLC."""

    def __init__(
        self,
        config: RootConfig,
        telegram_adapter: TelegramAdapter,
        ai_provider: AIProvider,
        db: SqliteDatabase,
        tool_registry: ToolRegistry,
        auth_manager: TelegramAuthManager,
        rate_limiter: UserRateLimiter,
    ):
        self.config = config
        self.telegram = telegram_adapter
        self.ai = ai_provider
        self.db = db
        self.tools = tool_registry
        self.auth = auth_manager
        self.rate_limiter = rate_limiter
        self.sdlc = MultiAgentSDLC(ai_provider=ai_provider, tool_registry=tool_registry)
        self._pending_actions: Dict[str, PendingConfirmation] = {}
        self._user_active_persona: Dict[int, str] = {}

    async def handle_message(self, message_data: Dict[str, Any]) -> None:
        """Process incoming Telegram message."""
        text = message_data.get("text", "").strip()
        if not text:
            return

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

        # 3. Handle bot slash commands
        if text.startswith("/"):
            await self._handle_command(chat_id, user_id, text)
            return

        # 4. Normal chat / prompt execution
        await self._process_user_prompt(chat_id, user_id, text)

    async def _handle_command(self, chat_id: int, user_id: int, command_text: str) -> None:
        """Route standard Telegram slash commands and multi-agent workflows."""
        parts = command_text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/start":
            msg = (
                f"Hello! I am {self.config.agent.name}.\n\n"
                f"Status: Online\n"
                f"Provider: {self.config.ai.provider.upper()} ({self.config.ai.model})\n"
                f"Active Agent Persona: {self._user_active_persona.get(user_id, 'orchestrator').upper()}\n\n"
                "Send me any task or question. Type /help to view available commands."
            )
            await self.telegram.send_message(chat_id, msg)

        elif cmd == "/help":
            help_text = (
                "Available Commands:\n"
                "/start - Bot status and greeting\n"
                "/help - Show this guide\n"
                "/status - Runtime health, memory, and provider status\n"
                "/agent [orchestrator|researcher|coder|qa] - Switch sub-agent persona\n"
                "/sdlc <feature_description> - Run full Multi-Agent SDLC pipeline\n"
                "/settings - Active AI model and agent persona\n"
                "/tools - List enabled tools and permission levels\n"
                "/memory - View stored memory entries for this session\n"
                "/reset - Clear active conversation context\n"
                "/cancel - Abort any pending action awaiting confirmation"
            )
            await self.telegram.send_message(chat_id, help_text)

        elif cmd == "/agent":
            if not args:
                cur = self._user_active_persona.get(user_id, "orchestrator")
                avail = ", ".join(SUBAGENT_PERSONAS.keys())
                await self.telegram.send_message(chat_id, f"Current Agent Persona: {cur}\nAvailable: {avail}\nUsage: /agent <name>")
                return
            target = args.lower()
            if target in SUBAGENT_PERSONAS:
                self._user_active_persona[user_id] = target
                await self.telegram.send_message(chat_id, f"Switched to {target.upper()} agent persona.")
            else:
                await self.telegram.send_message(chat_id, f"Unknown agent persona '{target}'. Options: {', '.join(SUBAGENT_PERSONAS.keys())}")

        elif cmd == "/sdlc":
            if not args:
                await self.telegram.send_message(chat_id, "Usage: /sdlc <describe the feature or task to build>")
                return
            await self._run_sdlc_flow(chat_id, user_id, args)

        elif cmd == "/status":
            cur_persona = self._user_active_persona.get(user_id, "orchestrator")
            status_text = (
                f"Agent Status: RUNNING\n"
                f"Telegram: CONNECTED\n"
                f"AI Provider: {self.config.ai.provider}\n"
                f"Model: {self.config.ai.model}\n"
                f"Active Persona: {cur_persona.upper()}\n"
                f"Memory: {'Enabled' if self.config.storage.memory_enabled else 'Disabled'}\n"
                f"Active Tools: {len(self.tools.list_definitions())}"
            )
            await self.telegram.send_message(chat_id, status_text)

        elif cmd == "/settings":
            settings_text = (
                f"Settings Overview:\n"
                f"- Name: {self.config.agent.name}\n"
                f"- Personality: {self.config.agent.personality}\n"
                f"- AI Provider: {self.config.ai.provider}\n"
                f"- Model: {self.config.ai.model}\n"
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
                lines.append(f"• {k}: {v}")
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

        else:
            await self.telegram.send_message(chat_id, f"Unknown command '{cmd}'. Type /help for assistance.")

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
        """Handle inline button clicks for destructive tool confirmations."""
        query_id = callback_data.get("id", "")
        data_str = callback_data.get("data", "")
        user = callback_data.get("from", {})
        user_id = user.get("id")
        msg = callback_data.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")

        if not user_id or not chat_id:
            return

        if data_str.startswith("confirm:"):
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

    async def _process_user_prompt(self, chat_id: int, user_id: int, prompt_text: str) -> None:
        """Execute ReAct loop with tool resolution, multi-turn persistence, and humanized output."""
        await self.telegram.send_chat_action(chat_id, "typing")

        session = await self.db.get_or_create_session(user_id, chat_id)
        user_message = Message(role=Role.USER, content=prompt_text)
        session.add_message(user_message)
        await self.db.save_message(session.session_id, user_id, user_message)

        # Get active subagent persona or default orchestrator
        cur_persona = self._user_active_persona.get(user_id, "orchestrator")
        persona_prompt = SUBAGENT_PERSONAS.get(cur_persona, self.config.agent.system_prompt)

        # Build dynamic system prompt with memory context
        memories = await self.db.get_memories(user_id)
        sys_prompt = f"{persona_prompt}\nTone: Direct, authentic, no robotic preambles."
        if memories:
            mem_summary = "\n".join(f"- {k}: {v}" for k, v in memories.items())
            sys_prompt += f"\n\nKnown context about user:\n{mem_summary}"

        tool_defs = self.tools.list_definitions()
        max_turns = 5

        for _ in range(max_turns):
            req = CompletionRequest(
                messages=session.messages,
                system_prompt=sys_prompt,
                tools=tool_defs,
                model=self.config.ai.model,
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
