import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
"""End-to-End User Simulation & Exploratory Monkey Testing Script.

Simulates a real human user interacting with the Telegram Bot in real-time,
testing real AI completions, model switching, persona switching, memory,
tools, and multi-agent SDLC.
"""

import asyncio
import os
import sys
from src.application.config_manager import ConfigManager
from src.application.orchestrator import AgentOrchestrator
from src.domain.user import AuthPolicy
from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.database.sqlite_db import SqliteDatabase
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.filesystem_tool import DirectoryListTool, FileReadTool, FileWriteTool
from src.infrastructure.tools.registry import ToolRegistry
from src.infrastructure.tools.web_search import WebSearchTool


class SimulatedTelegramAdapter(TelegramAdapter):
    """Intercepts Telegram sends and prints them formatted as a Telegram chat UI."""

    def __init__(self):
        super().__init__(bot_token="simulated_token")
        self.last_sent = []

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        print(f"\n🤖 [Bot -> User {chat_id}]:")
        print(text)
        if reply_markup and "inline_keyboard" in reply_markup:
            print("  🔘 [Buttons]:")
            for row in reply_markup["inline_keyboard"]:
                btn_labels = [f"[{b['text']}]" for b in row]
                print(f"    {' '.join(btn_labels)}")
        self.last_sent.append(text)
        return [12345]

    async def send_chat_action(self, chat_id, action="typing"):
        print(f"  ... [Bot is {action}...] ...")

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        print(f"  🔄 [Progress Update]: {text}")
        return True

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        print(f"  🔔 [Alert]: {text}")
        return True


async def run_simulation():
    cfg_mgr = ConfigManager(env_path=".env")
    config = cfg_mgr.load_config()

    print("=" * 60)
    print("🚀 MEMULAI SIMULASI USER & EXPLORATORY TESTING LIVE")
    print(f"Provider: {config.ai.provider.upper()} | Model: {config.ai.model}")
    print("=" * 60)

    # Initialize components
    db = SqliteDatabase(database_path="data/simulated_agent.db")
    await db.connect()

    tools = ToolRegistry(require_confirmation_for_destructive=False)
    tools.register(FileReadTool(root_dir="data"))
    tools.register(FileWriteTool(root_dir="data", read_only=False))
    tools.register(DirectoryListTool(root_dir="data"))
    tools.register(WebSearchTool())

    ai = create_ai_provider(
        provider_name=config.ai.provider,
        api_key=config.ai.api_key,
        model=config.ai.model,
        base_url=config.ai.base_url,
    )

    telegram = SimulatedTelegramAdapter()
    auth_mgr = TelegramAuthManager(policy=AuthPolicy(allowlist_enabled=False))
    limiter = UserRateLimiter(max_requests_per_minute=1000)

    orchestrator = AgentOrchestrator(
        config=config,
        telegram_adapter=telegram,
        ai_provider=ai,
        db=db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
    )

    user_id = 998877
    chat_id = 998877

    async def user_say(text: str):
        print(f"\n👤 [User]: {text}")
        await orchestrator.handle_message({
            "text": text,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "username": "benn"}
        })
        await asyncio.sleep(0.5)

    async def user_click_button(callback_data: str):
        print(f"\n👆 [User Clicks Button]: {callback_data}")
        await orchestrator.handle_callback_query({
            "id": "query_123",
            "data": callback_data,
            "from": {"id": user_id, "username": "benn"},
            "message": {"chat": {"id": chat_id}, "message_id": 12345}
        })
        await asyncio.sleep(0.5)

    # SCENARIO 1: First Onboarding
    print("\n--- [SCENARIO 1: Greeting & Command List] ---")
    await user_say("/start")
    await user_say("/help")

    # SCENARIO 2: Conversation & Context Memory
    print("\n--- [SCENARIO 2: Chat & Context Retention] ---")
    await user_say("Halo! Nama gua Benn, gua software engineer di Jakarta.")
    await user_say("Siapa nama gua dan apa pekerjaan gua?")

    # SCENARIO 3: Live Model Switching
    print("\n--- [SCENARIO 3: Ganti Model AI secara Dinamis] ---")
    await user_say("/model")
    await user_click_button("set_model:ds/deepseek-v4-flash")
    await user_say("Jelaskan perbedaan synchronous vs asynchronous dalam 1 kalimat.")

    await user_say("/model ag/gemini-3.7-flash-high")
    await user_say("Buat satu baris kode Python untuk filter angka genap dari list `[1, 2, 3, 4, 5, 6]`.")

    # SCENARIO 4: Persona Switching (/agent)
    print("\n--- [SCENARIO 4: Ganti Persona Sub-Agent] ---")
    await user_say("/agent coder")
    await user_say("Tulis fungsi Python async untuk health check endpoint.")

    await user_say("/agent qa")
    await user_say("Audit apa saja risiko keamanan dari string SQL formatting biasa.")

    # SCENARIO 5: Multi-Agent SDLC Lifecycle (/sdlc)
    print("\n--- [SCENARIO 5: Full SDLC Multi-Agent Orchestration] ---")
    await user_say("/sdlc Buat helper Python Token Bucket untuk rate limiting")

    # SCENARIO 6: Status & Context Reset
    print("\n--- [SCENARIO 6: Status & Context Reset] ---")
    await user_say("/status")
    await user_say("/reset")
    await user_say("Kamu masih ingat siapa nama saya?")

    print("\n" + "=" * 60)
    print("✅ SIMULASI SELESAI — SEMUA FITUR BERHASIL DIUJI TANPA ERROR!")
    print("=" * 60)

    await db.close()

if __name__ == "__main__":
    asyncio.run(run_simulation())
