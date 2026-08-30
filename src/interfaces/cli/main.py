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
            allow_write=config.tools.github.allow_write,
        ))

    if config.tools.filesystem.enabled:
        tools.register(FileReadTool(root_dir=config.tools.filesystem.root_dir))
        tools.register(FileWriteTool(
            root_dir=config.tools.filesystem.root_dir,
            read_only=config.tools.filesystem.read_only
        ))
        tools.register(DirectoryListTool(root_dir=config.tools.filesystem.root_dir))

    if config.tools.shell.enabled:
        tools.register(ShellTool(
            enabled=True,
            timeout=getattr(config.tools.shell, "timeout_seconds", 30.0),
            allow_destructive=config.tools.shell.allow_destructive
        ))

    # Initialize AI Provider
    ai = create_ai_provider(
        provider_name=config.ai.provider,
        api_key=config.ai.api_key,
        model=config.ai.model,
        base_url=config.ai.base_url,
        timeout=getattr(config.ai, "timeout_seconds", 60.0),
    )

    # Initialize Telegram Adapter
    telegram = TelegramAdapter(bot_token=config.telegram.bot_token)

    # Initialize Security components
    auth_policy = AuthPolicy(
        allowed_user_ids=config.telegram.allowed_users,
        allowlist_enabled=len(config.telegram.allowed_users) > 0,
        allow_groups=config.telegram.allow_groups
    )
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    rate_limiter = UserRateLimiter(max_requests_per_minute=config.security.rate_limit_per_minute)

    # Initialize Orchestrator
    orchestrator = AgentOrchestrator(
        config=config,
        telegram_adapter=telegram,
        ai_provider=ai,
        db=db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=rate_limiter,
    )

    # Shutdown event
    stop_event = asyncio.Event()

    def handle_shutdown(sig, frame):
        logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Verify bot identity
    try:
        me = await telegram.get_me()
        print("\n" + "╭" + "─" * 46 + "╮")
        print(f"│ Telegram Agent Online: @{me.username:<20} │")
        print(f"│ AI Provider:           {config.ai.provider.upper():<20} │")
        print(f"│ Active Model:          {config.ai.model:<20} │")
        print(f"│ Storage Database:      {config.storage.database_path:<20} │")
        print("╰" + "─" * 46 + "╯\n")
        print("Listening for incoming Telegram messages... (Press Ctrl+C to stop)")
    except Exception as e:
        logger.error(f"Failed to connect to Telegram: {str(e)}")
        sys.exit(1)

    # Main Polling Loop
    offset = None
    try:
        while not stop_event.is_set():
            updates = await telegram.get_updates(offset=offset, timeout=10)
            for update in updates:
                offset = update.get("update_id", 0) + 1

                if "message" in update:
                    asyncio.create_task(orchestrator.handle_message(update["message"]))
                elif "callback_query" in update:
                    asyncio.create_task(orchestrator.handle_callback_query(update["callback_query"]))

            await asyncio.sleep(0.1)
    finally:
        logger.info("Closing connections...")
        await telegram.close()
        await db.close()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        print("\nAgent stopped gracefully.")


def cmd_setup(args) -> None:
    wizard = SetupWizard(env_path=args.env)
    asyncio.run(wizard.run(advanced=args.advanced))


def cmd_start(args) -> None:
    asyncio.run(run_agent_daemon(env_path=args.env))


def cmd_stop(args) -> None:
    if not os.path.exists(PID_FILE):
        print("No active agent process found (missing PID file).")
        return
    with open(PID_FILE, "r") as f:
        pid_str = f.read().strip()
    try:
        pid = int(pid_str)
        os.kill(pid, signal.SIGTERM)
        print(f"✓ Sent termination signal to agent process PID {pid}.")
    except Exception as e:
        print(f"Failed to stop agent: {str(e)}")


def cmd_status(args) -> None:
    running = False
    pid_str = None
    if os.path.exists(PID_FILE):
        with open(PID_FILE, "r") as f:
            pid_str = f.read().strip()
        try:
            pid = int(pid_str)
            os.kill(pid, 0)
            running = True
        except OSError:
            running = False

    status_icon = "🟢 RUNNING" if running else "⚪ STOPPED"
    print(f"\nAgent Status: {status_icon}")
    if pid_str:
        print(f"Process PID:  {pid_str}")

    if os.path.exists(args.env):
        cfg_mgr = ConfigManager(env_path=args.env)
        try:
            config = cfg_mgr.load_config()
            print(f"AI Provider:  {config.ai.provider.upper()} ({config.ai.model})")
            print(f"Agent Name:   {config.agent.name}")
        except Exception:
            pass
    print()


def cmd_doctor(args) -> None:
    doctor = SystemDoctor(env_path=args.env)
    passed, results = asyncio.run(doctor.run_diagnostics())
    print("\nRunning Agent Doctor Diagnostics...\n")
    for r in results:
        mark = "✓" if r["status"] == "PASS" else "✗"
        print(f"{mark} {r['name']}: {r['detail']}")
    print()
    if passed:
        print("✓ All system health checks passed.")
    else:
        print("✗ Some health checks failed. Please inspect the logs.")


def cmd_config(args) -> None:
    cfg_mgr = ConfigManager(env_path=args.env)
    if args.action == "show":
        masked = cfg_mgr.get_masked_config()
        print(json.dumps(masked, indent=2))
    elif args.action == "reset":
        if os.path.exists(args.env):
            os.remove(args.env)
            print(f"Configuration file '{args.env}' removed.")


def cmd_backup(args) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup_agent_{ts}.tar.gz"
    with tarfile.open(backup_file, "w:gz") as tar:
        if os.path.exists(args.env):
            tar.add(args.env, arcname=".env")
        if os.path.exists("data"):
            tar.add("data", arcname="data")
    print(f"✓ Backup archive created: {backup_file}")


def cmd_test(args) -> None:
    import subprocess
    cmd = ["pytest"]
    if args.coverage:
        cmd.extend(["--cov=src", "--cov-report=term-missing"])
    subprocess.run(cmd)


def cmd_version(args) -> None:
    print("telegram-agent 1.0.0")


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

    # version
    subparsers.add_parser("version", help="Display version info")

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
        "version": cmd_version,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
