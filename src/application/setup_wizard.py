"""Interactive Setup Wizard with live API verification, progressive disclosure, and flexible model selection."""

import getpass
import os
import platform
import shutil
import sys
from typing import Any, Dict, List, Optional
from src.application.config_manager import ConfigManager, RootConfig
from src.infrastructure.ai.factory import create_ai_provider
from src.domain.provider import PROVIDER_MODELS_CATALOG
from src.infrastructure.ai.model_discovery import (
    base_url_lacks_api_path,
    fetch_available_models_ex,
    normalize_base_url,
)
from src.infrastructure.telegram.adapter import TelegramAdapter

# Model menus are derived from the shared catalog so the wizard can never drift
# out of sync with the providers' real model list.
PROVIDER_MODEL_MENUS: Dict[str, List[str]] = {
    provider: list(models) + ["Ketik nama model manual (Custom)"]
    for provider, models in PROVIDER_MODELS_CATALOG.items()
}


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
            print("\nSetup dibatalkan.")
            sys.exit(1)

    def _prompt_int(self, question: str, default: int = 15) -> int:
        """Prompt user for an integer with graceful validation and retry."""
        while True:
            raw = self._prompt(question, str(default))
            try:
                clean = raw.strip()
                if clean.lower() in ("y", "yes", "ok"):
                    return default
                return int(clean)
            except ValueError:
                print(f"Masukkan angka bilangan bulat yang valid (contoh: {default}).")

    def _prompt_float(self, question: str, default: float = 5.0) -> float:
        """Prompt user for a floating-point number with graceful validation."""
        while True:
            raw = self._prompt(question, str(default))
            try:
                clean = raw.strip()
                if clean.lower() in ("y", "yes", "ok"):
                    return default
                return float(clean)
            except ValueError:
                print(f"Masukkan angka desimal yang valid (contoh: {default}).")

    def _prompt_secret(self, question: str, default: str = "") -> str:
        """Prompt for sensitive credentials securely."""
        default_str = " [Tekan Enter untuk pakai nilai lama]" if default else ""
        try:
            val = getpass.getpass(f"? {question}{default_str}: ").strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            print("\nSetup dibatalkan.")
            sys.exit(1)
    def _prompt_url(self, question: str, default: str = "") -> str:
        """Prompt for a base URL, validating and normalizing it with retry."""
        while True:
            raw = self._prompt(question, default)
            normalized = normalize_base_url(raw)
            if normalized:
                if normalized != raw.strip().rstrip("/"):
                    print(f"  → Menggunakan URL: {normalized}")
                if base_url_lacks_api_path(normalized):
                    print(
                        "  ℹ️  URL ini belum punya path. Gateway OpenAI-compatible biasanya "
                        "butuh suffix /v1\n     (contoh: http://localhost:20128/v1)."
                    )
                return normalized


    def _prompt_choice(self, question: str, choices: list[str], default_idx: int = 0) -> str:
        """Prompt user to choose from a list of options."""
        print(f"\n? {question}")
        for i, choice in enumerate(choices, 1):
            marker = ">" if (i - 1) == default_idx else " "
            print(f"  {marker} {i}. {choice}")
        while True:
            val = self._prompt(f"Pilih nomor opsi (1-{len(choices)})", str(default_idx + 1))
            if val.isdigit() and 1 <= int(val) <= len(choices):
                return choices[int(val) - 1]
            print("Pilihan tidak valid. Silakan ketik angka opsi yang tersedia.")

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
            print(f"✗ Versi Python tidak kompatibel: {py_ver}. Diperlukan Python 3.12+.")
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
            print(f"Konfigurasi lama ditemukan di '{self.env_path}'.")
            try:
                existing_cfg = self.config_manager.load_config()
                if not non_interactive:
                    action = self._prompt_choice(
                        "Apa yang ingin Anda lakukan?",
                        ["Edit / Update konfigurasi", "Pertahankan konfigurasi lama & uji", "Reset konfigurasi dari awal"],
                        0
                    )
                    if action == "Pertahankan konfigurasi lama & uji":
                        return await self._validate_and_finish(existing_cfg)
                    elif action == "Reset konfigurasi dari awal":
                        os.remove(self.env_path)
                        existing_cfg = None
                        print("Konfigurasi lama berhasil dihapus.\n")
            except Exception:
                existing_cfg = None

        env_dict: Dict[str, Any] = {}

        # Step 2: Telegram Configuration & Live Validation
        print("Step [2/6] Telegram Configuration")
        while True:
            default_token = existing_cfg.telegram.bot_token if existing_cfg else ""
            token = self._prompt_secret("Telegram Bot Token (didapat dari @BotFather)", default_token)
            if not token:
                print("Error: Telegram Bot Token tidak boleh kosong.")
                continue

            print("→ Memverifikasi token Telegram Bot...")
            try:
                adapter = TelegramAdapter(bot_token=token)
                bot_user = await adapter.get_me()
                print(f"✓ Koneksi Telegram terverifikasi: @{bot_user.username} (ID: {bot_user.id})")
                env_dict["TELEGRAM_BOT_TOKEN"] = token
                break
            except Exception as e:
                print(f"✗ Verifikasi Telegram gagal: {str(e)}")
                if not self._prompt_bool("Ingin memasukkan ulang token?", default=True):
                    env_dict["TELEGRAM_BOT_TOKEN"] = token
                    break

        default_allowed = ",".join(map(str, existing_cfg.telegram.allowed_users)) if existing_cfg else ""
        allowed_users = self._prompt("Allowed Telegram User IDs (pisahkan dengan koma jika banyak, kosongkan untuk akses terbuka)", default_allowed)
        env_dict["TELEGRAM_ALLOWED_USERS"] = allowed_users

        # Step 3: AI Provider Configuration & Flexible Model Selection
        print("\nStep [3/6] AI Provider Configuration")
        providers = ["9router", "deepseek", "anthropic", "google", "openai", "openrouter", "ollama", "opencode-zen", "opencode-go", "custom"]
        cur_prov = existing_cfg.ai.provider if existing_cfg and existing_cfg.ai.provider in providers else "9router"
        provider = self._prompt_choice("Pilih AI Provider", providers, default_idx=providers.index(cur_prov))
        env_dict["AI_PROVIDER"] = provider

        base_url = ""
        if provider == "9router":
            default_9r_url = existing_cfg.ai.base_url if (existing_cfg and existing_cfg.ai.base_url) else "http://localhost:20128/v1"
            base_url = self._prompt_url("9router Gateway URL", default_9r_url)
            env_dict["AI_BASE_URL"] = base_url
        elif provider == "deepseek":
            default_ds_url = existing_cfg.ai.base_url if (existing_cfg and existing_cfg.ai.base_url) else "https://api.deepseek.com/v1"
            base_url = self._prompt_url("DeepSeek API URL", default_ds_url)
            env_dict["AI_BASE_URL"] = base_url
        elif provider == "opencode-zen":
            default_zen_url = existing_cfg.ai.base_url if (existing_cfg and existing_cfg.ai.base_url) else "https://api.opencode.ai/v1"
            base_url = self._prompt_url("OpenCode Zen API Base URL", default_zen_url)
            env_dict["AI_BASE_URL"] = base_url
        elif provider == "opencode-go":
            default_go_url = existing_cfg.ai.base_url if (existing_cfg and existing_cfg.ai.base_url) else "https://go.opencode.ai/v1"
            base_url = self._prompt_url("OpenCode Go API Base URL", default_go_url)
            env_dict["AI_BASE_URL"] = base_url
        elif provider == "custom":
            base_url = self._prompt_url("Custom OpenAI-compatible Base URL (contoh: http://localhost:8000/v1)", existing_cfg.ai.base_url if existing_cfg else "")
            env_dict["AI_BASE_URL"] = base_url

        while True:
            if provider not in ("ollama", "9router"):
                default_key = existing_cfg.ai.api_key if existing_cfg else ""
                api_key = self._prompt_secret(f"{provider.upper()} API Key", default_key)
                env_dict["AI_API_KEY"] = api_key
            elif provider == "9router":
                default_key = existing_cfg.ai.api_key if existing_cfg else ""
                api_key = self._prompt("9router API Key (opsional / password untuk gateway)", default_key)
                env_dict["AI_API_KEY"] = api_key
            else:
                api_key = ""
                env_dict["AI_API_KEY"] = ""

            # Dynamic Live Model Discovery from Provider API
            print(f"\n→ Mengambil daftar model yang tersedia dari {provider.upper()}...")
            discovered, live_ok = await fetch_available_models_ex(provider, api_key=api_key, base_url=base_url)
            clean_discovered = [m for m in discovered if m != "Ketik nama model manual (Custom)"]
            if not clean_discovered:
                clean_discovered = [m for m in PROVIDER_MODEL_MENUS.get(provider, []) if m != "Ketik nama model manual (Custom)"]

            if not live_ok:
                print(f"⚠️  Gagal mengambil daftar model LIVE dari {provider.upper()}.")
                print(
                    "    Menampilkan daftar CADANGAN yang bisa usang — periksa URL gateway dan API key."
                )
                print(f"    Gateway dipakai: {base_url or '(default provider)'}")

            model_options = clean_discovered + ["Ketik nama model manual (Custom)"]
            default_model = existing_cfg.ai.model if (existing_cfg and existing_cfg.ai.model in model_options) else model_options[0]

            source = "LIVE" if live_ok else "cadangan/offline"
            print(f"\n? Pilih Model AI untuk {provider.upper()} ({len(clean_discovered)} model — {source}):")
            for i, opt in enumerate(model_options, 1):
                marker = ">" if opt == default_model else " "
                print(f"  {marker} {i}. {opt}")

            raw_model_input = self._prompt(
                f"Pilih nomor (1-{len(model_options)}) atau langsung ketik nama model",
                "1"
            )

            # Check if user typed a number
            if raw_model_input.isdigit() and 1 <= int(raw_model_input) <= len(model_options):
                chosen_opt = model_options[int(raw_model_input) - 1]
                if chosen_opt == "Ketik nama model manual (Custom)":
                    model = self._prompt("Ketik nama model", default_model)
                else:
                    model = chosen_opt
            else:
                # User directly typed a model name like 'ag/gemini-3.7-flash-high'
                model = raw_model_input.strip()

            env_dict["AI_MODEL"] = model

            print(f"→ Menguji kredensial ke {provider.upper()} ({model})...")
            try:
                prov_inst = create_ai_provider(provider_name=provider, api_key=api_key, model=model, base_url=base_url)
                valid = await prov_inst.validate_credentials()
                if valid:
                    print(f"✓ Koneksi ke {provider.upper()} ({model}) berhasil diverifikasi.")
                    break
                else:
                    print(f"✗ Peringatan: Gagal memvalidasi kredensial ke {provider.upper()}.")
                    detail = getattr(prov_inst, "last_error", None)
                    if detail:
                        print(f"  Detail: {detail}")
                    if not self._prompt_bool("Tetap gunakan model ini dan lanjutkan?", default=True):
                        continue
                    break
            except Exception as e:
                print(f"✗ Catatan verifikasi: {str(e)}")
                if not self._prompt_bool("Tetap gunakan model ini dan lanjutkan?", default=True):
                    continue
                break

        # Step 4: Agent Persona
        print("\nStep [4/6] Agent Persona")
        env_dict["AGENT_NAME"] = self._prompt("Nama Agent", existing_cfg.agent.name if existing_cfg else "Personal Assistant")
        env_dict["AGENT_PERSONALITY"] = self._prompt("Gaya Bahasa / Karakter Agent", existing_cfg.agent.personality if existing_cfg else "Direct & Helpful")
        env_dict["AGENT_SYSTEM_PROMPT"] = self._prompt(
            "System Prompt",
            existing_cfg.agent.system_prompt if existing_cfg else "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed."
        )

        # Step 5: Advanced Preferences & Integrations
        if not advanced and not non_interactive:
            advanced = self._prompt_bool("Konfigurasi pengaturan lanjutan (Multi-Agent, Tools, GitHub, Memory)?", default=False)

        if advanced:
            print("\nStep [5/6] Advanced Integrations & Security")
            env_dict["ENABLE_WEB_SEARCH"] = self._prompt_bool("Aktifkan fitur Web Search?", default=True)

            enable_gh = self._prompt_bool("Aktifkan integrasi GitHub?", default=True)
            env_dict["ENABLE_GITHUB"] = enable_gh
            if enable_gh:
                env_dict["GITHUB_TOKEN"] = self._prompt_secret("GitHub Personal Access Token", "")
                env_dict["GITHUB_DEFAULT_REPO"] = self._prompt("Default Repository (owner/repo)", "")
                env_dict["GITHUB_ALLOW_WRITE"] = self._prompt_bool("Izinkan operasi tulis GitHub (buat issues)?", default=False)

            env_dict["ENABLE_FILESYSTEM"] = self._prompt_bool("Aktifkan akses Filesystem Sandbox?", default=True)
            env_dict["FILESYSTEM_READ_ONLY"] = self._prompt_bool("Mode Filesystem Read-Only?", default=True)
            env_dict["ALLOW_SHELL"] = self._prompt_bool("Aktifkan eksekusi Shell Terminal (HIGH RISK)?", default=False)
            env_dict["REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE"] = self._prompt_bool("Wajibkan konfirmasi user untuk aksi berisiko tinggi?", default=True)

            env_dict["MEMORY_ENABLED"] = self._prompt_bool("Aktifkan memori persisten SQLite?", default=True)
            env_dict["RATE_LIMIT_REQUESTS_PER_MINUTE"] = self._prompt_int("Rate Limit (maksimal request per menit per user)", default=15)
            env_dict["DAILY_BUDGET_USD"] = self._prompt_float("Batas budget harian AI dalam USD (angka, misal: 5.0)", default=5.0)
        else:
            # Sane defaults
            env_dict["ENABLE_WEB_SEARCH"] = True
            env_dict["ENABLE_GITHUB"] = True
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
        print(f"  Rate Limit: {env_dict['RATE_LIMIT_REQUESTS_PER_MINUTE']} req/min")
        print(f"  Daily Budget: ${env_dict['DAILY_BUDGET_USD']}")
        print("╰" + "─" * 46 + "╯\n")

        if not non_interactive and not self._prompt_bool("Simpan konfigurasi ini ke .env?", default=True):
            print("Setup dibatalkan. Tidak ada file yang diubah.")
            return False

        # Save to .env
        self.config_manager.save_env_file(env_dict)
        print(f"✓ Konfigurasi tersimpan di {self.env_path} (Permissions: 0600)")

        # Register Telegram bot commands for autocomplete & menu button
        try:
            adapter = TelegramAdapter(bot_token=env_dict.get("TELEGRAM_BOT_TOKEN", ""))
            await adapter.set_my_commands()
            print("✓ Shortcut menu & autocomplete perintah Telegram berhasil didaftarkan.")
        except Exception:
            pass

        # Verify .gitignore
        self._ensure_gitignore()

        print("\n" + "╭" + "─" * 46 + "╮")
        print("│       Setup Berhasil Selesai                 │")
        print("╰" + "─" * 46 + "╯\n")
        print("Jalankan agent dengan perintah:\n")
        if platform.system() == "Windows":
            print("  PowerShell:      .\\scripts\\start.ps1")
            print("  Command Prompt:  scripts\\start.bat\n")
        else:
            print("  Linux / macOS:   ./scripts/start")
            print("  Windows:         .\\scripts\\start.ps1\n")
        print("atau dengan Docker:\n")
        print("    docker compose up -d\n")
        print("Buka Telegram lalu kirim /start, /model, atau /sdlc ke bot Anda.\n")

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
