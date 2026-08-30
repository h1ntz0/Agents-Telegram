"""Command-line interface (CLI) for Telegram Agent."""

import argparse
import asyncio
import json
import os
import signal
import sys
import tarfile
from datetime import datetime, timezone
from src.application.config_manager import ConfigManager
from src.application.doctor import SystemDoctor
from src.application.orchestrator import AgentOrchestrator
from src.application.setup_wizard import SetupWizard
from src.domain.user import AuthPolicy
from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.database.sqlite_db import SqliteDatabase
from src.infrastructure.security.logger import configure_logging
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.filesystem_tool import DirectoryListTool, FileReadTool, FileWriteTool
from src.infrastructure.tools.github_tool import GitHubTool
from src.infrastructure.tools.registry import ToolRegistry
from src.infrastructure.tools.shell_tool import ShellTool
from src.infrastructure.tools.web_search import WebSearchTool

PID_FILE = "data/agent.pid"


async def run_agent_daemon(env_path: str = ".env") -> None:
    """Initialize and run the agent runtime loop with graceful signal handling."""
    if not os.path.exists(env_path):
        print(f"Configuration file '{env_path}' not found. Please run './setup' first.")
        sys.exit(1)

    cfg_mgr = ConfigManager(env_path=env_path)
    config = cfg_mgr.load_config()

    logger = configure_logging(config.app.log_level)
    logger.info("Initializing Telegram Agent Runtime...")

    # Write PID file
    os.makedirs("data", exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Initialize Database
    db = SqliteDatabase(database_path=config.storage.database_path)
    await db.connect()

    # Initialize Tool Registry
    tools = ToolRegistry(require_confirmation_for_destructive=config.tools.require_confirmation_for_destructive)

    if config.tools.web_search.enabled:
        tools.register(WebSearchTool())

    if config.tools.github.enabled:
        tools.register(GitHubTool(
            token=config.tools.github.token,
            default_repo=config.tools.github.default_repo,
            allow_write=config.tools.github.allow_write
        ))

    if config.tools.filesystem.enabled:
        tools.register(FileReadTool(root_dir=config.tools.filesystem.root_dir))
        tools.register(FileWriteTool(root_dir=config.tools.filesystem.root_dir, read_only=config.tools.filesystem.read_only))
        tools.register(DirectoryListTool(root_dir=config.tools.filesystem.root_dir))

    if config.tools.shell.enabled:
        tools.register(ShellTool(enabled=True, allow_destructive=config.tools.shell.allow_destructive))

    # Initialize AI Provider
    ai_provider = create_ai_provider(
        provider_name=config.ai.provider,
        api_key=config.ai.api_key,
        model=config.ai.model,
        base_url=config.ai.base_url
    )

    # Initialize Telegram Adapter & Auth
    telegram = TelegramAdapter(bot_token=config.telegram.bot_token)
    auth_policy = AuthPolicy(
        allowlist_enabled=len(config.telegram.allowed_users) > 0,
        allowed_user_ids=set(config.telegram.allowed_users),
        admin_user_ids=set(config.telegram.admin_users),
        enable_private_chat=config.telegram.enable_private_chat,
        enable_group_chat=config.telegram.enable_group_chat,
    )
    auth_manager = TelegramAuthManager(policy=auth_policy)
    rate_limiter = UserRateLimiter(max_requests_per_minute=config.security.rate_limit_per_minute)

    # Initialize Orchestrator
    orchestrator = AgentOrchestrator(
        config=config,
        telegram_adapter=telegram,
        ai_provider=ai_provider,
        db=db,
        tool_registry=tools,
        auth_manager=auth_manager,
        rate_limiter=rate_limiter,
    )

    # Verify bot identity before launching polling loop
    try:
        bot_user = await telegram.get_me()
        print(f"\n✓ Agent Online: @{bot_user.username} (ID: {bot_user.id})")
        print(f"✓ AI Provider: {config.ai.provider.upper()} ({config.ai.model})")
        print("Ready for messages. Press Ctrl+C to stop.\n")
    except Exception as e:
        logger.error(f"Failed to connect to Telegram: {str(e)}")
        print(f"\n✗ Telegram connection failed: {str(e)}")
        await db.close()
        sys.exit(1)

    # Signal handling for graceful shutdown
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        telegram.stop_polling()
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    polling_task = asyncio.create_task(
        telegram.start_polling(
            on_message=orchestrator.handle_message,
            on_callback_query=orchestrator.handle_callback_query
        )
    )

    await stop_event.wait()
    telegram.stop_polling()
    await polling_task
    await db.close()

    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass

    print("\nAgent gracefully stopped.")


def cmd_setup(args: argparse.Namespace) -> None:
    """Run interactive setup wizard."""
    wizard = SetupWizard(env_path=args.env)
    asyncio.run(wizard.run(advanced=args.advanced))


def cmd_start(args: argparse.Namespace) -> None:
    """Start agent runtime."""
    try:
        asyncio.run(run_agent_daemon(env_path=args.env))
    except KeyboardInterrupt:
        print("\nAgent stopped.")


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop running background agent process."""
    if not os.path.exists(PID_FILE):
        print("No running agent process found (PID file missing).")
        return

    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent termination signal to agent process (PID {pid}).")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception as e:
        print(f"Error stopping agent process: {str(e)}")


def cmd_status(args: argparse.Namespace) -> None:
    """Check running process status."""
    is_running = False
    pid = None
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            is_running = True
        except Exception:
            is_running = False

    print("\n╭──────── Agent Status ────────╮")
    print(f"  Process:     {'RUNNING' if is_running else 'STOPPED'}" + (f" (PID: {pid})" if is_running else ""))
    if os.path.exists(args.env):
        cfg = ConfigManager(env_path=args.env).load_config()
        print(f"  AI Provider: {cfg.ai.provider} ({cfg.ai.model})")
        print(f"  Storage:     {cfg.storage.database_path}")
    else:
        print(f"  Config:      Missing ({args.env})")
    print("╰──────────────────────────────╯\n")


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run system diagnostics."""
    print("\nRunning Agent Doctor Diagnostics...\n")
    doctor = SystemDoctor(env_path=args.env)
    passed, results = asyncio.run(doctor.run_diagnostics())

    for r in results:
        mark = "✓" if r["status"] == "PASS" else "✗"
        print(f"{mark} {r['name']}: {r['detail']}")

    print()
    if passed:
        print("✓ All system health checks passed.")
    else:
        print("✗ One or more diagnostics failed. Please resolve the reported issues.")
        sys.exit(1)


def cmd_config(args: argparse.Namespace) -> None:
    """View or reset configuration."""
    cfg_mgr = ConfigManager(env_path=args.env)
    if args.action == "show":
        if not os.path.exists(args.env):
            print(f"Config file '{args.env}' not found.")
            return
        config = cfg_mgr.load_config()
        view = cfg_mgr.get_masked_view(config)
        print("\n" + json.dumps(view, indent=2) + "\n")
    elif args.action == "reset":
        if os.path.exists(args.env):
            confirm = input("Are you sure you want to delete local .env configuration? (y/N): ").strip().lower()
            if confirm in ("y", "yes"):
                os.remove(args.env)
                print("Configuration reset. Run './setup' to reconfigure.")
            else:
                print("Reset cancelled.")
        else:
            print("No .env file found.")


def cmd_backup(args: argparse.Namespace) -> None:
    """Create timestamped tarball backup of database and configuration."""
    os.makedirs("data/backups", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = f"data/backups/agent_backup_{ts}.tar.gz"

    with tarfile.open(backup_file, "w:gz") as tar:
        if os.path.exists(".env"):
            tar.add(".env", arcname=".env.backup")
        if os.path.exists("data/agent.db"):
            tar.add("data/agent.db", arcname="data/agent.db")

    print(f"✓ Backup created: {backup_file}")


def cmd_test(args: argparse.Namespace) -> None:
    """Run automated pytest suite."""
    import subprocess
    cmd = [sys.executable, "-m", "pytest", "-v"]
    if args.coverage:
        cmd.extend(["--cov=src", "--cov-report=term-missing"])
    code = subprocess.call(cmd)
    sys.exit(code)


def main() -> None:
    """CLI Argument Parser entrypoint."""
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Telegram Agent - Self-hosted zero-friction AI Agent Framework"
    )
    parser.add_argument("--version", action="version", version="telegram-agent 1.0.0")
    parser.add_argument("--env", default=".env", help="Path to environment file (default: .env)")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # setup
    p_setup = subparsers.add_parser("setup", help="Run interactive setup wizard")
    p_setup.add_argument("--advanced", action="store_true", help="Include advanced options")

    # start
    subparsers.add_parser("start", help="Start agent runtime daemon")

    # stop
    subparsers.add_parser("stop", help="Stop background agent process")

    # status
    subparsers.add_parser("status", help="Display agent health and runtime status")

    # doctor
    subparsers.add_parser("doctor", help="Run comprehensive health and connectivity diagnostics")

    # config
    p_config = subparsers.add_parser("config", help="Manage configuration")
    p_config.add_argument("action", choices=["show", "reset"], default="show", nargs="?")

    # backup
    subparsers.add_parser("backup", help="Create backup archive of database and settings")

    # test
    p_test = subparsers.add_parser("test", help="Execute test suites")
    p_test.add_argument("--coverage", action="store_true", help="Run tests with coverage report")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "setup": cmd_setup,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "doctor": cmd_doctor,
        "config": cmd_config,
        "backup": cmd_backup,
        "test": cmd_test,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
