"""System diagnostics and health inspection suite ('agent doctor')."""

import os
import platform
import shutil
import sys
from typing import Dict, List, Tuple
from src.application.config_manager import ConfigManager, RootConfig
from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.database.sqlite_db import SqliteDatabase
from src.infrastructure.telegram.adapter import TelegramAdapter


class SystemDoctor:
    """Runs automated health checks across environment, configuration, APIs, and permissions."""

    def __init__(self, env_path: str = ".env"):
        self.env_path = env_path
        self.config_manager = ConfigManager(env_path=env_path)

    async def run_diagnostics(self) -> Tuple[bool, List[Dict[str, str]]]:
        """Execute all diagnostics and return overall pass/fail status and detailed check list."""
        results: List[Dict[str, str]] = []
        all_passed = True

        # 1. Python Runtime
        py_ver = sys.version.split()[0]
        if sys.version_info >= (3, 12):
            results.append({"name": "Python Runtime", "status": "PASS", "detail": f"Python {py_ver}"})
        else:
            all_passed = False
            results.append({
                "name": "Python Runtime",
                "status": "FAIL",
                "detail": f"Python {py_ver} detected. Requires Python 3.12 or newer."
            })

        # 2. Environment & System Tools
        os_info = f"{platform.system()} {platform.release()}"
        git_found = shutil.which("git") is not None
        docker_found = shutil.which("docker") is not None

        env_details = f"{os_info} | Git: {'installed' if git_found else 'missing'} | Docker: {'installed' if docker_found else 'missing'}"
        results.append({"name": "Operating System", "status": "PASS", "detail": env_details})

        # 3. Configuration Check
        if not os.path.exists(self.env_path):
            all_passed = False
            results.append({
                "name": "Configuration File",
                "status": "FAIL",
                "detail": f"{self.env_path} not found. Run './setup' to configure."
            })
            return all_passed, results

        try:
            config: RootConfig = self.config_manager.load_config()
            results.append({"name": "Configuration Schema", "status": "PASS", "detail": "Valid syntax and schema."})
        except Exception as e:
            all_passed = False
            results.append({"name": "Configuration Schema", "status": "FAIL", "detail": f"Config parsing error: {str(e)}"})
            return all_passed, results

        # 4. GitIgnore Secret Protection
        if os.path.exists(".gitignore"):
            with open(".gitignore", "r", encoding="utf-8") as f:
                gi_content = f.read()
            if ".env" in gi_content:
                results.append({"name": "Secret Protection (.gitignore)", "status": "PASS", "detail": ".env is gitignored"})
            else:
                all_passed = False
                results.append({"name": "Secret Protection (.gitignore)", "status": "FAIL", "detail": ".env is missing from .gitignore"})
        else:
            all_passed = False
            results.append({"name": "Secret Protection (.gitignore)", "status": "FAIL", "detail": ".gitignore file missing"})

        # 5. Database Storage & Permissions
        try:
            db_dir = os.path.dirname(os.path.abspath(config.storage.database_path))
            os.makedirs(db_dir, exist_ok=True)
            db = SqliteDatabase(database_path=config.storage.database_path)
            await db.connect()
            await db.close()
            results.append({"name": "Database & Storage", "status": "PASS", "detail": f"SQLite accessible at {config.storage.database_path}"})
        except Exception as e:
            all_passed = False
            results.append({"name": "Database & Storage", "status": "FAIL", "detail": f"Storage initialization failed: {str(e)}"})

        # 6. Telegram API Connection Check
        if not config.telegram.bot_token:
            all_passed = False
            results.append({"name": "Telegram Connection", "status": "FAIL", "detail": "TELEGRAM_BOT_TOKEN is empty."})
        else:
            try:
                tg_adapter = TelegramAdapter(bot_token=config.telegram.bot_token)
                bot_user = await tg_adapter.get_me()
                results.append({
                    "name": "Telegram Connection",
                    "status": "PASS",
                    "detail": f"Connected as @{bot_user.username} (ID: {bot_user.id})"
                })
            except Exception as e:
                all_passed = False
                results.append({
                    "name": "Telegram Connection",
                    "status": "FAIL",
                    "detail": f"Connection check failed: {str(e)}"
                })

        # 7. AI Provider Validation Check
        if not config.ai.api_key and config.ai.provider != "ollama":
            all_passed = False
            results.append({"name": "AI Provider", "status": "FAIL", "detail": f"API key for {config.ai.provider} is missing."})
        else:
            try:
                ai_prov = create_ai_provider(
                    provider_name=config.ai.provider,
                    api_key=config.ai.api_key,
                    model=config.ai.model,
                    base_url=config.ai.base_url
                )
                is_valid = await ai_prov.validate_credentials()
                if is_valid:
                    results.append({
                        "name": "AI Provider",
                        "status": "PASS",
                        "detail": f"{config.ai.provider.upper()} ({config.ai.model}) verified."
                    })
                else:
                    all_passed = False
                    results.append({
                        "name": "AI Provider",
                        "status": "FAIL",
                        "detail": f"Could not authenticate with {config.ai.provider}. Please verify API key."
                    })
            except Exception as e:
                all_passed = False
                results.append({"name": "AI Provider", "status": "FAIL", "detail": f"Provider check error: {str(e)}"})

        return all_passed, results
