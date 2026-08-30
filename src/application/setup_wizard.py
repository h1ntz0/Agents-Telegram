"""Interactive Setup Wizard with live API verification, progressive disclosure, and safe secret handling."""

import getpass
import os
import platform
import shutil
import sys
from typing import Any, Dict, Optional
from src.application.config_manager import ConfigManager, RootConfig
from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.telegram.adapter import TelegramAdapter


class SetupWizard:
    """Guided terminal wizard to configure and initialize the Telegram Agent."""

    def __init__(self, env_path: str = ".env"):
        self.env_path = env_path
        self.config_manager = ConfigManager(env_path=env_path)

    def _prompt(self, question: str, default: str = "") -> str:
        """Prompt user with optional default fallback."""
        default_str = f" [{default}]" if default else ""
        try:
            val = input(f"? {question}{default_str}: ").strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            print("\nSetup aborted.")
            sys.exit(1)

    def _prompt_secret(self, question: str, default: str = "") -> str:
        """Prompt for sensitive credentials securely."""
        default_str = " [Press Enter to keep existing]" if default else ""
        try:
            val = getpass.getpass(f"? {question}{default_str}: ").strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            print("\nSetup aborted.")
            sys.exit(1)

    def _prompt_choice(self, question: str, choices: list[str], default_idx: int = 0) -> str:
        """Prompt user to choose from a list of options."""
        print(f"\n? {question}")
        for i, choice in enumerate(choices, 1):
            marker = ">" if (i - 1) == default_idx else " "
            print(f"  {marker} {i}. {choice}")
        while True:
            val = self._prompt(f"Select option (1-{len(choices)})", str(default_idx + 1))
            if val.isdigit() and 1 <= int(val) <= len(choices):
                return choices[int(val) - 1]
            print("Invalid selection. Please enter a valid option number.")

    def _prompt_bool(self, question: str, default: bool = True) -> bool:
        """Prompt user for a yes/no boolean response."""
        default_str = "Y/n" if default else "y/N"
        val = self._prompt(f"{question} ({default_str})", "y" if default else "n").lower()
        return val in ("y", "yes", "true", "1")

    async def run(self, advanced: bool = False, non_interactive: bool = False) -> bool:
        """Execute the setup wizard sequence."""
        print("\n" + "╭" + "─" * 46 + "╮")
        print("│        Telegram Agent Setup Wizard           │")
        print("╰" + "─" * 46 + "╯\n")

        # Step 0: Environment Detection
        print("Step [1/6] Environment Check")
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info < (3, 12):
            print(f"✗ Incompatible Python version: {py_ver}. Python 3.12+ is required.")
            return False

        os_name = f"{platform.system()} ({platform.release()})"
        git_status = "installed" if shutil.which("git") else "missing"
        docker_status = "installed" if shutil.which("docker") else "missing"

        print(f"✓ Python: {py_ver}")
        print(f"✓ Operating System: {os_name}")
        print(f"✓ Git: {git_status}")
        print(f"✓ Docker: {docker_status}")
        print("Environment is ready.\n")

        # Step 1: Existing configuration check
        existing_cfg: Optional[RootConfig] = None
        if os.path.exists(self.env_path):
            print(f"Existing configuration detected in '{self.env_path}'.")
            try:
                existing_cfg = self.config_manager.load_config()
                if not non_interactive:
                    action = self._prompt_choice(
                        "What would you like to do?",
                        ["Edit / Update configuration", "Keep existing & validate", "Reset configuration"],
                        0
                    )
                    if action == "Keep existing & validate":
                        return await self._validate_and_finish(existing_cfg)
                    elif action == "Reset configuration":
                        os.remove(self.env_path)
                        existing_cfg = None
                        print("Existing configuration cleared.\n")
            except Exception:
                existing_cfg = None

        env_dict: Dict[str, Any] = {}

        # Step 2: Telegram Configuration & Live Validation
        print("Step [2/6] Telegram Configuration")
        while True:
            default_token = existing_cfg.telegram.bot_token if existing_cfg else ""
            token = self._prompt_secret("Telegram Bot Token (from @BotFather)", default_token)
            if not token:
                print("Error: Telegram Bot Token cannot be empty.")
                continue

            print("→ Verifying Telegram Bot token...")
            try:
                adapter = TelegramAdapter(bot_token=token)
                bot_user = await adapter.get_me()
                print(f"✓ Telegram connection verified: @{bot_user.username} (ID: {bot_user.id})")
                env_dict["TELEGRAM_BOT_TOKEN"] = token
                break
            except Exception as e:
                print(f"✗ Telegram verification failed: {str(e)}")
                if not self._prompt_bool("Would you like to re-enter the token?", default=True):
                    env_dict["TELEGRAM_BOT_TOKEN"] = token
                    break

        default_allowed = ",".join(map(str, existing_cfg.telegram.allowed_users)) if existing_cfg else ""
        allowed_users = self._prompt("Allowed Telegram User IDs (comma-separated, leave blank for open access)", default_allowed)
        env_dict["TELEGRAM_ALLOWED_USERS"] = allowed_users

        # Step 3: AI Provider Configuration & Live Validation
        print("\nStep [3/6] AI Provider Configuration")
        providers = ["openai", "anthropic", "google", "openrouter", "ollama", "custom"]
        cur_prov = existing_cfg.ai.provider if existing_cfg and existing_cfg.ai.provider in providers else "openai"
        provider = self._prompt_choice("Select AI Provider", providers, default_idx=providers.index(cur_prov))
        env_dict["AI_PROVIDER"] = provider

        default_model_map = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20241022",
            "google": "gemini-2.0-flash",
            "openrouter": "anthropic/claude-3.5-sonnet",
            "ollama": "llama3.2",
            "custom": "custom-model"
        }

        base_url = ""
        if provider == "custom":
            base_url = self._prompt("Custom OpenAI-compatible Base URL (e.g. http://localhost:8000/v1)", existing_cfg.ai.base_url if existing_cfg else "")
            env_dict["AI_BASE_URL"] = base_url

        while True:
            if provider != "ollama":
                default_key = existing_cfg.ai.api_key if existing_cfg else ""
                api_key = self._prompt_secret(f"{provider.upper()} API Key", default_key)
                env_dict["AI_API_KEY"] = api_key
            else:
                api_key = ""
                env_dict["AI_API_KEY"] = ""

            default_model = existing_cfg.ai.model if existing_cfg else default_model_map.get(provider, "gpt-4o")
            model = self._prompt("Model Name", default_model)
            env_dict["AI_MODEL"] = model

            print(f"→ Verifying credentials with {provider.upper()}...")
            try:
                prov_inst = create_ai_provider(provider_name=provider, api_key=api_key, model=model, base_url=base_url)
                valid = await prov_inst.validate_credentials()
                if valid:
                    print(f"✓ {provider.upper()} connection verified successfully.")
                    break
                else:
                    print(f"✗ Verification warning: Could not validate credentials with {provider.upper()}.")
                    if not self._prompt_bool("Would you like to re-enter your API key?", default=True):
                        break
            except Exception as e:
                print(f"✗ Verification error: {str(e)}")
                if not self._prompt_bool("Would you like to re-enter your API key?", default=True):
                    break

        # Step 4: Agent Persona
        print("\nStep [4/6] Agent Persona")
        env_dict["AGENT_NAME"] = self._prompt("Agent Name", existing_cfg.agent.name if existing_cfg else "Personal Assistant")
        env_dict["AGENT_PERSONALITY"] = self._prompt("Agent Tone / Personality", existing_cfg.agent.personality if existing_cfg else "Professional")
        env_dict["AGENT_SYSTEM_PROMPT"] = self._prompt(
            "System Prompt",
            existing_cfg.agent.system_prompt if existing_cfg else "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed."
        )

        # Step 5: Advanced Preferences & Integrations
        if not advanced and not non_interactive:
            advanced = self._prompt_bool("Configure advanced settings (Tools, GitHub, Memory, Security)?", default=False)

        if advanced:
            print("\nStep [5/6] Advanced Integrations & Security")
            env_dict["ENABLE_WEB_SEARCH"] = self._prompt_bool("Enable Web Search?", default=True)

            enable_gh = self._prompt_bool("Enable GitHub Integration?", default=False)
            env_dict["ENABLE_GITHUB"] = enable_gh
            if enable_gh:
                env_dict["GITHUB_TOKEN"] = self._prompt_secret("GitHub Personal Access Token", "")
                env_dict["GITHUB_DEFAULT_REPO"] = self._prompt("Default Repository (owner/repo)", "")
                env_dict["GITHUB_ALLOW_WRITE"] = self._prompt_bool("Allow GitHub write operations (e.g. create issues)?", default=False)

            env_dict["ENABLE_FILESYSTEM"] = self._prompt_bool("Enable Sandboxed Filesystem Access?", default=True)
            env_dict["FILESYSTEM_READ_ONLY"] = self._prompt_bool("Filesystem Read-Only mode?", default=True)
            env_dict["ALLOW_SHELL"] = self._prompt_bool("Enable Shell Execution (HIGH RISK)?", default=False)
            env_dict["REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE"] = self._prompt_bool("Require User Confirmation for High-Risk Actions?", default=True)

            env_dict["MEMORY_ENABLED"] = self._prompt_bool("Enable Persistent SQLite Memory?", default=True)
            env_dict["RATE_LIMIT_REQUESTS_PER_MINUTE"] = int(self._prompt("Rate Limit (requests per minute per user)", "15"))
            env_dict["DAILY_BUDGET_USD"] = float(self._prompt("Daily AI Budget in USD", "5.0"))
        else:
            # Sane defaults
            env_dict["ENABLE_WEB_SEARCH"] = True
            env_dict["ENABLE_GITHUB"] = False
            env_dict["ENABLE_FILESYSTEM"] = True
            env_dict["FILESYSTEM_READ_ONLY"] = True
            env_dict["ALLOW_SHELL"] = False
            env_dict["REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE"] = True
            env_dict["MEMORY_ENABLED"] = True
            env_dict["RATE_LIMIT_REQUESTS_PER_MINUTE"] = 15
            env_dict["DAILY_BUDGET_USD"] = 5.0

        # Step 6: Review & Persistence
        print("\nStep [6/6] Configuration Review")
        print("╭" + "─" * 46 + "╮")
        print(f"  Telegram:   Connected (Allowlist: {env_dict['TELEGRAM_ALLOWED_USERS'] or 'Open'})")
        print(f"  AI:         {env_dict['AI_PROVIDER'].upper()} ({env_dict['AI_MODEL']})")
        print(f"  Agent:      {env_dict['AGENT_NAME']}")
        print(f"  Memory:     {'Enabled' if env_dict['MEMORY_ENABLED'] else 'Disabled'}")
        print(f"  Web Search: {'Enabled' if env_dict['ENABLE_WEB_SEARCH'] else 'Disabled'}")
        print(f"  GitHub:     {'Enabled' if env_dict['ENABLE_GITHUB'] else 'Disabled'}")
        print(f"  Shell:      {'Enabled' if env_dict['ALLOW_SHELL'] else 'Disabled'}")
        print("╰" + "─" * 46 + "╯\n")

        if not non_interactive and not self._prompt_bool("Save this configuration to .env?", default=True):
            print("Setup cancelled. No changes were saved.")
            return False

        # Save to .env
        self.config_manager.save_env_file(env_dict)
        print(f"✓ Configuration saved to {self.env_path} (Permissions: 0600)")

        # Verify .gitignore
        self._ensure_gitignore()

        print("\n" + "╭" + "─" * 46 + "╮")
        print("│       Setup Completed Successfully           │")
        print("╰" + "─" * 46 + "╯\n")
        print("To start your agent, run:\n")
        print("    ./start\n")
        print("or with Docker:\n")
        print("    docker compose up -d\n")
        print("Then open Telegram and send /start to your bot.\n")

        return True

    def _ensure_gitignore(self) -> None:
        """Ensure .env is listed in .gitignore."""
        if not os.path.exists(".gitignore"):
            with open(".gitignore", "w", encoding="utf-8") as f:
                f.write(".env\ndata/*.db\n.venv/\n")
            return

        with open(".gitignore", "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        if ".env" not in lines:
            with open(".gitignore", "a", encoding="utf-8") as f:
                f.write("\n.env\n")

    async def _validate_and_finish(self, config: RootConfig) -> bool:
        """Run quick validation for existing configuration."""
        from src.application.doctor import SystemDoctor
        doc = SystemDoctor(env_path=self.env_path)
        passed, results = await doc.run_diagnostics()
        for r in results:
            mark = "✓" if r["status"] == "PASS" else "✗"
            print(f"{mark} {r['name']}: {r['detail']}")
        return passed
