"""Command-line interface (CLI) for Telegram Agent."""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from typing import List, Optional

from src import __version__
from src.application.config_manager import ConfigManager, ConfigurationError
from src.application.doctor import SystemDoctor
from src.application.orchestrator import AgentOrchestrator
from src.application.setup_wizard import SetupError, SetupOptions, SetupWizard
from src.domain.user import AuthPolicy
from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.database.sqlite_db import SqliteDatabase
from src.infrastructure.i18n import set_language, t
from src.infrastructure.scheduler.job_scheduler import JobScheduler
from src.infrastructure.security.logger import configure_logging
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.chart_tool import ChartTool
from src.infrastructure.opencode.bridge import OpenCodeBridge
from src.infrastructure.tools.filesystem_tool import DirectoryListTool, FileDeleteTool, FileEditTool, FileReadTool, FileWriteTool
from src.infrastructure.tools.opencode_tool import OpenCodeBridgeTool
from src.infrastructure.tools.github_tool import GitHubTool
from src.infrastructure.tools.http_fetch_tool import HttpFetchTool
from src.infrastructure.tools.python_sandbox_tool import PythonSandboxTool
from src.infrastructure.tools.registry import ToolRegistry
from src.infrastructure.tools.shell_tool import ShellTool
from src.infrastructure.tools.weather_tool import WeatherTool
from src.infrastructure.tools.web_search import WebSearchTool

PID_FILE = "data/agent.pid"
STOP_FILE = "data/agent.stop"
LOG_FILE = "data/agent.log"
# A stop request is noticed on the next poll iteration (the long poll waits up to 10s),
# so the grace period must comfortably exceed that before we escalate to a hard kill.
STOP_GRACE_SECONDS = 20.0


# --------------------------------------------------------------------------- #
# Process supervision helpers
# --------------------------------------------------------------------------- #

def read_pid(pid_file: str = PID_FILE) -> Optional[int]:
    """Return the PID recorded on disk, or None when absent or unreadable."""
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def process_alive(pid: int) -> bool:
    """Whether a process with this PID currently exists.

    On Windows this must NOT use ``os.kill(pid, 0)``: that API maps to TerminateProcess,
    so the "probe" would kill the process it is inspecting. It opens the process for
    query instead and checks GetExitCodeProcess.
    """
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but belongs to another user.
        return True
    except OSError:
        return False


def force_kill(pid: int) -> None:
    """Terminate a process without waiting for it to shut down cleanly."""
    try:
        if os.name == "nt":
            # Only SIGTERM/SIGKILL reach TerminateProcess on Windows; both are hard kills.
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def request_stop(pid: int) -> None:
    """Ask a running agent to shut down, gracefully where the platform allows it.

    The sentinel file works on every platform (the polling loop checks it each tick);
    SIGTERM additionally triggers the handler on POSIX, matching systemd and Docker.
    """
    os.makedirs(os.path.dirname(os.path.abspath(STOP_FILE)), exist_ok=True)
    try:
        with open(STOP_FILE, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except OSError:
        pass

    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def clear_stop_file() -> None:
    """Remove a leftover stop request so the next start is not aborted immediately."""
    try:
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
    except OSError:
        pass


def clear_stale_pid(pid_file: str = PID_FILE) -> Optional[int]:
    """Delete a PID file whose process is gone. Returns the stale PID, if any."""
    pid = read_pid(pid_file)
    if pid is None:
        if os.path.exists(pid_file):
            os.remove(pid_file)
        return None
    if process_alive(pid):
        return None
    try:
        os.remove(pid_file)
    except OSError:
        pass
    return pid


def wait_for_exit(pid: int, timeout: float = STOP_GRACE_SECONDS) -> bool:
    """Block until a process exits, returning whether it did so within the timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.2)
    return not process_alive(pid)


def stop_running_agent(pid: int, announce: bool = True) -> None:
    """Stop a live agent, escalating to a hard kill if it does not exit in time."""
    request_stop(pid)
    if wait_for_exit(pid):
        clear_stop_file()
        clear_stale_pid()
        return

    if announce:
        print(t("cli.stop_timeout", pid=pid, seconds=int(STOP_GRACE_SECONDS)))
    force_kill(pid)
    wait_for_exit(pid, timeout=5.0)
    clear_stop_file()
    clear_stale_pid()


def check_no_running_instance(force: bool) -> None:
    """Refuse to start a second poller for the same bot token; --force takes over instead."""
    clear_stop_file()

    stale = clear_stale_pid()
    if stale is not None:
        print(t("cli.stale_pid", pid=stale))

    pid = read_pid()
    if pid is None or not process_alive(pid):
        return

    if not force:
        print(t("cli.already_running", pid=pid))
        sys.exit(1)

    stop_running_agent(pid, announce=False)


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #

async def run_agent_daemon(env_path: str = ".env", force: bool = False) -> None:
    """Initialize and run the agent runtime loop with graceful signal handling."""
    if not os.path.exists(env_path):
        print(t("cli.no_config", path=env_path))
        sys.exit(1)

    check_no_running_instance(force)

    try:
        cfg_mgr = ConfigManager(env_path=env_path)
        config = cfg_mgr.load_config()
    except ConfigurationError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    set_language(config.app.ui_lang)
    logger = configure_logging(config.app.log_level)
    logger.info("Initializing Telegram Agent Runtime...")

    # Write PID file
    os.makedirs(os.path.dirname(os.path.abspath(PID_FILE)), exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    # Initialize Database
    db = SqliteDatabase(database_path=config.storage.database_path)
    await db.connect()

    if config.storage.retention_days > 0:
        purged = await db.purge_expired_memories(config.storage.retention_days)
        if purged:
            logger.info(t("cli.purged", count=purged, days=config.storage.retention_days))

    # Initialize Scheduler (timezone-aware so /remind 18:00 means the user's 18:00)
    scheduler = JobScheduler(db=db, timezone=config.app.timezone)

    # Initialize Tool Registry
    tools = ToolRegistry(require_confirmation_for_destructive=config.tools.require_confirmation_for_destructive)

    if getattr(config.tools, "web_search", None) and config.tools.web_search.enabled:
        tools.register(WebSearchTool())

    if getattr(config.tools, "http_fetch", None) and config.tools.http_fetch.enabled:
        tools.register(HttpFetchTool(timeout=config.tools.http_fetch.timeout_seconds))

    if getattr(config.tools, "chart", None) and config.tools.chart.enabled:
        tools.register(ChartTool())

    if getattr(config.tools, "python_sandbox", None) and config.tools.python_sandbox.enabled:
        tools.register(PythonSandboxTool(default_timeout=config.tools.python_sandbox.timeout_seconds))

    if getattr(config.tools, "weather", None) and config.tools.weather.enabled:
        tools.register(WeatherTool(timeout=config.tools.weather.timeout_seconds))

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
        tools.register(FileEditTool(
            root_dir=config.tools.filesystem.root_dir,
            read_only=config.tools.filesystem.read_only
        ))
        tools.register(FileDeleteTool(
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

    # OpenCode session bridge (remote-control a local opencode serve instance)
    tools.register(OpenCodeBridgeTool(bridge=OpenCodeBridge(base_url=config.ai.opencode_server_url)))

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
        admin_user_ids=config.telegram.admin_users,
        allowlist_enabled=len(config.telegram.allowed_users) > 0,
        enable_private_chat=config.telegram.enable_private_chat,
        enable_group_chat=config.telegram.enable_group_chat
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
        scheduler=scheduler,
    )

    # Shutdown event
    stop_event = asyncio.Event()

    def handle_shutdown(sig, frame):
        logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_shutdown)

    # Background scheduler runner task
    async def scheduler_background_loop():
        logger.info("Scheduler background runner started.")
        while not stop_event.is_set():
            try:
                due_jobs = await scheduler.get_due_jobs()
                for due_job in due_jobs:
                    asyncio.create_task(orchestrator.run_scheduled_job(due_job))
            except Exception as e:
                logger.error(f"Scheduler tick error: {str(e)}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        logger.info("Scheduler background runner stopped.")

    scheduler_task = asyncio.create_task(scheduler_background_loop())

    # Verify bot identity and register menu command suggestions
    try:
        me = await telegram.get_me()
        await telegram.set_my_commands()
        width = 46
        print("\n+" + "-" * width + "+")
        print("| " + t("cli.online_banner").ljust(width - 2) + " |")
        print("| " + f"@{me.username}".ljust(width - 2) + " |")
        print("| " + f"{config.ai.provider.upper()} ({config.ai.model})".ljust(width - 2) + " |")
        print("| " + f"{config.storage.database_path}".ljust(width - 2) + " |")
        print("+" + "-" * width + "+\n")
        print(t("cli.listening"))
    except Exception as e:
        logger.error(f"Failed to connect to Telegram: {str(e)}")
        await db.close()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        sys.exit(1)

    # Main Polling Loop
    offset = None
    try:
        while not stop_event.is_set():
            # Windows cannot deliver SIGTERM, so `agent stop` also drops a sentinel file.
            if os.path.exists(STOP_FILE):
                logger.info("Stop request received; shutting down.")
                stop_event.set()
                break

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
        stop_event.set()
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await telegram.close()
        await db.close()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        print(t("cli.stopped"))


def spawn_detached(env_path: str) -> int:
    """Start the agent as a background process and return its PID."""
    os.makedirs(os.path.dirname(os.path.abspath(LOG_FILE)), exist_ok=True)
    log = open(LOG_FILE, "a", encoding="utf-8")
    log.write(f"\n--- started at {datetime.now(timezone.utc).isoformat()} ---\n")
    log.flush()

    argv = [sys.executable, "-m", "src", "start", "--env", env_path]
    kwargs = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL, "cwd": os.getcwd()}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(argv, **kwargs)
    log.close()
    return proc.pid


# --------------------------------------------------------------------------- #
# CLI commands
# --------------------------------------------------------------------------- #

def cmd_setup(args) -> None:
    options = SetupOptions(
        advanced=args.advanced,
        non_interactive=args.non_interactive,
        bot_token=args.bot_token or "",
        provider=args.provider or "",
        model=args.model or "",
        api_key=args.api_key or "",
        base_url=args.base_url or "",
        allowed_users=args.allowed_users or "",
        language=args.lang or "",
        timezone=args.timezone or "",
        force=args.force,
    )
    wizard = SetupWizard(env_path=args.env)
    try:
        ok = asyncio.run(wizard.run(options))
    except SetupError as e:
        print(f"\nSetup failed: {e}")
        sys.exit(1)
    if not ok:
        sys.exit(1)


def cmd_start(args) -> None:
    if args.detach:
        check_no_running_instance(args.force)
        try:
            pid = spawn_detached(args.env)
        except Exception as e:
            print(t("cli.detach_failed", error=str(e)))
            sys.exit(1)
        print(t("cli.detached", pid=pid, log=LOG_FILE))
        return
    asyncio.run(run_agent_daemon(env_path=args.env, force=args.force))


def cmd_stop(args) -> None:
    pid = read_pid()
    if pid is None:
        print(t("cli.no_pid"))
        return

    if not process_alive(pid):
        clear_stale_pid()
        print(t("cli.stale_pid", pid=pid))
        return

    print(t("cli.stop_signal", pid=pid))
    stop_running_agent(pid)
    if process_alive(pid):
        print(t("cli.stop_failed", error=f"PID {pid} is still running"))
        sys.exit(1)


def cmd_status(args) -> None:
    pid = read_pid()
    running = pid is not None and process_alive(pid)
    if pid is not None and not running:
        # A PID file left behind by a crash must not be reported as a live process.
        clear_stale_pid()
        pid = None

    if getattr(args, "check", False):
        if running:
            print(f"OK (pid {pid})")
            return
        print(t("cli.status.check_failed"))
        sys.exit(1)

    print()
    print(t("cli.status.header", status=t("cli.status.running") if running else t("cli.status.stopped")))
    if running and pid:
        print(t("cli.status.pid", pid=pid))

    if os.path.exists(args.env):
        cfg_mgr = ConfigManager(env_path=args.env)
        try:
            config = cfg_mgr.load_config()
            print(t("cli.status.provider", provider=config.ai.provider.upper(), model=config.ai.model))
            print(t("cli.status.agent_name", name=config.agent.name))
        except Exception as e:
            print(f"Configuration error: {e}")
    else:
        print(t("cli.no_config", path=args.env))
    print()


def cmd_doctor(args) -> None:
    doctor = SystemDoctor(env_path=args.env)
    passed, results = asyncio.run(doctor.run_diagnostics())
    print(f"\n{t('cli.doctor.header')}\n")
    for r in results:
        status = r["status"]
        mark = "OK " if status == "PASS" else ("-- " if status == "INFO" else "x  ")
        print(f"{mark} {r['name']}: {r['detail']}")

    print()
    if passed:
        print(t("cli.doctor.passed"))
    else:
        print(t("cli.doctor.failed"))
        sys.exit(1)


def cmd_config(args) -> None:
    cfg_mgr = ConfigManager(env_path=args.env)
    if args.action == "show":
        try:
            print(json.dumps(cfg_mgr.get_masked_config(), indent=2))
        except ConfigurationError as e:
            print(f"Configuration error: {e}")
            sys.exit(1)
    elif args.action == "reset":
        if os.path.exists(args.env):
            os.remove(args.env)
            print(t("cli.config.reset_done", path=args.env))
        else:
            print(t("cli.config.reset_missing", path=args.env))


def cmd_backup(args) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup_agent_{ts}.tar.gz"
    with tarfile.open(backup_file, "w:gz") as tar:
        if os.path.exists(args.env):
            tar.add(args.env, arcname=".env")
        if os.path.exists("data"):
            tar.add("data", arcname="data")
    print(t("cli.backup.created", path=backup_file))


def cmd_test(args) -> None:
    cmd = [sys.executable, "-m", "pytest"]
    if args.coverage:
        cmd.extend(["--cov=src", "--cov-report=term-missing"])
    sys.exit(subprocess.call(cmd))


def cmd_version(args) -> None:
    print(f"telegram-agent {__version__}")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser, accepting --env both before and after the subcommand."""
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Telegram Agent - self-hosted AI agent framework for Telegram",
    )
    parser.add_argument("--version", action="version", version=f"telegram-agent {__version__}")
    parser.add_argument("--env", default=".env", help="Path to the environment file (default: .env)")

    # Given after the subcommand, this must not clobber a value supplied before it.
    def with_common(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sub.add_argument("--env", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        return sub

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    p_setup = with_common(subparsers.add_parser("setup", help="Run the setup wizard (interactive or headless)"))
    p_setup.add_argument("--advanced", action="store_true", help="Ask the advanced integration questions")
    p_setup.add_argument("-y", "--non-interactive", action="store_true", help="Never prompt; requires --bot-token and --provider")
    p_setup.add_argument("--bot-token", help="Telegram bot token from @BotFather")
    p_setup.add_argument("--provider", help="AI provider id (9router, openai, anthropic, ollama, ...)")
    p_setup.add_argument("--model", help="Model name to use for the chosen provider")
    p_setup.add_argument("--api-key", help="API key for the chosen provider")
    p_setup.add_argument("--base-url", help="Base URL override for the chosen provider")
    p_setup.add_argument("--allowed-users", help="Comma separated Telegram user IDs allowed to use the bot")
    p_setup.add_argument("--lang", choices=["en", "id"], help="Language for the agent UI and wizard")
    p_setup.add_argument("--timezone", help="IANA timezone for reminders and schedules (e.g. Asia/Jakarta)")
    p_setup.add_argument("--force", action="store_true", help="Overwrite the existing configuration instead of updating it")

    p_start = with_common(subparsers.add_parser("start", help="Start the agent runtime"))
    p_start.add_argument("--detach", action="store_true", help="Run in the background and log to data/agent.log")
    p_start.add_argument("--force", action="store_true", help="Take over from an already running instance")

    with_common(subparsers.add_parser("stop", help="Stop the background agent process"))

    p_status = with_common(subparsers.add_parser("status", help="Display agent and configuration status"))
    p_status.add_argument("--check", action="store_true", help="Exit non-zero when the agent is not running")

    with_common(subparsers.add_parser("doctor", help="Run health and connectivity diagnostics"))

    p_config = with_common(subparsers.add_parser("config", help="Manage configuration"))
    p_config.add_argument("action", choices=["show", "reset"], default="show", nargs="?")

    with_common(subparsers.add_parser("backup", help="Archive the database and settings"))

    p_test = with_common(subparsers.add_parser("test", help="Execute the test suite"))
    p_test.add_argument("--coverage", action="store_true", help="Also produce a coverage report")

    with_common(subparsers.add_parser("version", help="Display version info"))

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
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
