# Setup & Operations Guide (v2.1.0)

This guide covers prerequisites, interactive configuration, background daemon lifecycle management, Docker deployments, and security hardening for the Telegram Agent Platform.

---

## 📋 Prerequisites

* **Operating System**: Linux (Ubuntu 22.04+, Debian 12+, Arch), macOS 13+, or Windows 10/11 (Native PowerShell / CMD / WSL2).
* **Python Runtime**: Python 3.12 or higher. `agent doctor` fails on older interpreters.
* **Database**: SQLite 3 (bundled with Python standard library).
* **Package Manager**: `pip` and `venv` module.
* **Optional**: Docker 24+ and Docker Compose v2 for containerized hosting.

---

## ⚡ 1. Interactive Setup Wizard

The repository includes an automated setup wizard that creates a virtual environment, auto-installs dependencies, and configures `.env`:

```bash
# Linux / macOS
./scripts/setup
```

```powershell
# Windows PowerShell - run in your user directory (Documents / Home)
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
.\scripts\setup.ps1
```

```bat
REM Windows Command Prompt (cmd.exe)
scripts\setup.bat
```

> **Windows note:** Always clone and run from `%USERPROFILE%` (e.g. `C:\Users\YourName\Documents`). Do NOT run inside `C:\Windows\system32` which is write-protected and causes `Permission denied`.

The same wizard is available through the CLI (`agent setup`). With `-y/--non-interactive` plus `--bot-token`, `--provider`, `--model`, `--api-key`, and `--allowed-users` it runs headless for Docker, CI, or a provisioning script. Re-running it merges into the existing `.env` instead of overwriting keys you added yourself; `--force` replaces the file.

### What the Wizard Does:
1. Locates Python 3.12+ (supports `py -3.12`, `python`, `python3`; filters out broken Windows Store stubs; offers auto-install via `winget` if missing).
2. Creates and populates the isolated `.venv` environment and bootstraps `pip` if missing.
3. Installs dependencies with automatic fallback to direct package installs if setuptools editable mode fails.
4. Prompts for your **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather)) and validates connectivity in real time.
5. Lets you select your **AI Provider** (9router, DeepSeek, Anthropic, Google Gemini, OpenAI, OpenRouter, Ollama, OpenCode Zen, OpenCode Go, custom).
6. Interactively presents recommended models or accepts custom model identifiers.
7. Writes configuration to `.env` and attempts to set owner-only permissions (`chmod 0600`). **On Windows this is a no-op** — file/directory ACLs govern access there, so restrict the file through the filesystem's security settings instead.
8. Registers the slash-command menu with Telegram (`setMyCommands`).
9. Pauses on error or completion so double-clicking the script never silently closes the terminal.

---

## ⚙️ 2. Configuration Reference (`.env`)

There is no copy of the variable table in this guide. The single source of truth is:

* **`docs/reference/env.md`** — every environment variable, its default, and what it changes.
* **`.env.example`** — the checked-in template the wizard writes and the file `agent doctor` compares your `.env` against.

Anything in your `.env` that is not in that list is inert, and `agent doctor` reports it. Precedence, highest first: process environment → `.env` → `config/config.yaml` → `config/defaults/default.yaml`.

---

## 🚀 3. Lifecycle & Daemon Management

### Foreground Execution
For debugging and viewing real-time log output:
```bash
./scripts/start
```
or directly:
```bash
./.venv/bin/python -m src start
```
Press `Ctrl+C` to stop.

### Background Daemon
`--detach` spawns a detached process and appends both stdout and stderr to `data/agent.log`:

```bash
# Start in the background
./scripts/start --detach

# Follow the log written by the detached process
tail -f data/agent.log

# Stop the background daemon
./scripts/stop
```

The running instance records its PID in `data/agent.pid`. Starting a second instance for the same bot token is refused; pass `--force` to take over from the existing one.

### Status & Diagnostics
```bash
# Human-readable status plus the resolved provider/model
python -m src status

# Healthcheck mode: exit 1 when the agent is not running
python -m src status --check

# Full diagnostics
./scripts/doctor
```

`agent doctor` checks the Python version, OS tooling, configuration schema, **inert `.env` keys**, timezone validity, `.gitignore` coverage, SQLite access, the Telegram connection, the AI provider, and the OpenCode bridge. It **exits with status 1 when any check FAILs** — an invalid `TIMEZONE` and an unrecognised `.env` key are the two most common findings.

---

## 🐳 4. Docker Deployment

The agent is Telegram long-polling only: it listens on no port and nothing is published. State lives in the `./data` bind mount and persists across restarts.

```bash
# 1. Guided first-run configuration (writes .env on the host)
docker compose run --rm setup

# 2. Start the long-polling agent in the background
docker compose up -d

# Follow the agent log
docker compose logs -f

# Run diagnostics inside the running container
docker compose exec telegram-agent python -m src doctor

# Stop the agent
docker compose down
```

`setup` must run before `up` — it is what creates the `.env` file the `telegram-agent` service mounts read-only. Extra wizard flags need the full command, for example:

```bash
docker compose run --rm setup python -m src setup --advanced
docker compose run --rm setup python -m src setup -y \
    --bot-token "$TELEGRAM_BOT_TOKEN" --provider "$AI_PROVIDER" \
    --model "$AI_MODEL" --api-key "$AI_API_KEY"
```

Both services run as uid 1000 (`app`). On Linux, if your host user has a different uid, hand `./data` to that uid (`sudo chown -R 1000:1000 ./data`) or run the wizard as yourself with `docker compose run --rm --user "$(id -u):$(id -g)" setup`.

---

## 🐧 5. Systemd Service (Production Linux Host)

To ensure the agent starts automatically on system boot and restarts on unexpected crashes:

Create `/etc/systemd/system/telegram-agent.service`:

```ini
[Unit]
Description=Telegram Multi-Agent AI Platform
After=network.target

[Service]
Type=simple
User=benn
WorkingDirectory=/home/benn/Project/Agents-Telegram
ExecStart=/home/benn/Project/Agents-Telegram/.venv/bin/python -m src start
Restart=always
RestartSec=5
StandardOutput=append:/home/benn/Project/Agents-Telegram/data/agent.log
StandardError=append:/home/benn/Project/Agents-Telegram/data/agent.log

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-agent
sudo systemctl status telegram-agent
```

With systemd capturing output you do not need `--detach`; the unit supervises the process itself.

---

## ⌨️ 6. Telegram BotFather Configuration

1. Open [@BotFather](https://t.me/BotFather) on Telegram.
2. If running in groups, send `/setprivacy` -> Select your bot -> Choose `Disable` so the bot can process group commands.
3. Autocomplete menu commands (17 of them) are automatically registered on startup via the Telegram Bot API (`setMyCommands`). No manual `/setcommands` entry is necessary.

---

## 🩺 7. Troubleshooting

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| `HTTP 401 Unauthorized` | Invalid Telegram token | Run `./scripts/setup` or update `TELEGRAM_BOT_TOKEN` in `.env`. |
| `Sorry, you are not authorized` | ID missing from allowed list | Add your Telegram User ID to `TELEGRAM_ALLOWED_USERS` in `.env`. |
| `SSRF Security Violation: ... is prohibited` | `http_fetch` targeted an internal address | The HTTP fetcher forbids private/loopback/link-local/reserved addresses. Use a public URL. |
| `Database Locked` | Concurrent unclosed handles | Ensure only one agent instance runs against `data/agent.db`. Use `./scripts/stop` before starting a new process, or `agent start --force` to take over. |
| `Tool Requires Confirmation` | High-risk tool triggered | Click the inline **Confirm** button in Telegram to approve execution, or `/cancel` to discard it. |
| `agent doctor` exits 1 | A check FAILed | Read the failing row. An invalid `TIMEZONE` (reminders would fire in UTC) and unrecognised `.env` keys are reported explicitly. |
| `agent status --check` exits 1 | Agent not running | Start it with `./scripts/start --detach`, then re-check. |
