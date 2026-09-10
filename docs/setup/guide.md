# Setup & Operations Guide (v2.0)

This guide covers prerequisites, interactive configuration, background daemon lifecycle management, Docker deployments, and security hardening for the Telegram Agent Platform.

---

## 📋 Prerequisites

* **Operating System**: Linux (Ubuntu 22.04+, Debian 12+, Arch), macOS 13+, or Windows 10/11 (Native PowerShell / CMD / WSL2).
* **Python Runtime**: Python 3.12 or higher.
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
### What the Wizard Does:
1. Locates Python 3.12+ (supports `py -3.12`, `python`, `python3`; filters out broken Windows Store stubs; offers auto-install via `winget` if missing).
2. Creates and populates the isolated `.venv` environment and bootstraps `pip` if missing.
3. Installs dependencies with automatic fallback to direct package installs if setuptools editable mode fails.
4. Prompts for your **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather)) and validates connectivity in real time.
5. Lets you select your **AI Provider** (9router, DeepSeek, Anthropic, Google Gemini, OpenAI, OpenRouter, Ollama).
6. Interactively presents recommended models or accepts custom model identifiers.
7. Writes configuration to `.env` and locks file permissions (`chmod 600`) so other OS users cannot read your API tokens.
8. Pauses on error or completion so double-clicking the script never silently closes the terminal.
---

## ⚙️ 2. Configuration Reference (`.env`)

Below is the complete reference for all supported `.env` variables:

```ini
# Application Environment
APP_ENV=production
LOG_LEVEL=INFO
TIMEZONE=Asia/Jakarta

# Telegram Settings
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_ALLOWED_USERS=123456789,987654321    # Comma-separated user IDs; empty = open
ADMIN_TELEGRAM_USERS=123456789               # Admin user IDs for system maintenance
ENABLE_PRIVATE_CHAT=true
ENABLE_GROUP_CHAT=false

# AI Provider Settings
AI_PROVIDER=9router                          # 9router | deepseek | anthropic | google | openai | openrouter | ollama
AI_API_KEY=your_provider_api_key
AI_MODEL=ag/gemini-3.7-flash-high            # Default active model
AI_BASE_URL=http://localhost:20128/v1        # Optional custom gateway endpoint
AI_TEMPERATURE=0.2
AI_MAX_TOKENS=4096

# Agent Persona
AGENT_NAME=Assistant
AGENT_PERSONALITY=Professional
AGENT_SYSTEM_PROMPT=You are a direct, highly competent AI assistant.

# Integrations & Tools
ENABLE_WEB_SEARCH=true
ENABLE_GITHUB=false
GITHUB_TOKEN=
GITHUB_DEFAULT_REPO=
GITHUB_ALLOW_WRITE=false

ENABLE_FILESYSTEM=true
FILESYSTEM_ROOT_DIR=./data
FILESYSTEM_READ_ONLY=true

# Sandbox & Dangerous Tools
ALLOW_SHELL=false
REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE=true

# Storage & Persistence
MEMORY_ENABLED=true
DATABASE_PATH=data/agent.db
MEMORY_RETENTION_DAYS=0                      # 0 = indefinite retention

# Security & Rate Limiting
RATE_LIMIT_REQUESTS_PER_MINUTE=20
```

---

## 🚀 3. Lifecycle & Daemon Management

### Foreground Execution
For debugging and viewing real-time log output:
```bash
./.venv/bin/python -m src
```

### Background Daemon (`./scripts/start` & `./scripts/stop`)
To run the agent as a background process with PID tracking:

```bash
# Start background daemon
./scripts/start

# Check process status and log output
tail -f data/agent.log

# Stop background daemon
./scripts/stop
```

### System Diagnostics (`./scripts/doctor`)
Run the diagnostics script at any time to verify system health:

```bash
./scripts/doctor
```

---

## 🐳 4. Docker Deployment

### Run with Docker Compose
```bash
# Complete setup wizard first to generate .env
./scripts/setup

# Start containers in detached mode
docker compose up -d

# View real-time container logs
docker compose logs -f

# Stop container
docker compose down
```

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
ExecStart=/home/benn/Project/Agents-Telegram/.venv/bin/python -m src
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

---

## ⌨️ 6. Telegram BotFather Configuration

1. Open [@BotFather](https://t.me/BotFather) on Telegram.
2. If running in groups, send `/setprivacy` -> Select your bot -> Choose `Disable` so the bot can process group commands.
3. Autocomplete menu commands are automatically registered on startup via the Telegram Bot API (`setMyCommands`). No manual `/setcommands` entry is necessary.

---

## 🩺 7. Troubleshooting

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| `HTTP 401 Unauthorized` | Invalid Telegram token | Run `./scripts/setup` or update `TELEGRAM_BOT_TOKEN` in `.env`. |
| `Sorry, you are not authorized` | ID missing from allowed list | Add your Telegram User ID to `TELEGRAM_ALLOWED_USERS` in `.env`. |
| `SSRF Blocked: Destination IP is private` | Target URL is internal | The HTTP fetcher strictly forbids RFC 1918 addresses (`10.*`, `192.168.*`, `127.0.0.1`). |
| `Database Locked` | Concurrent unclosed handles | Ensure only one agent instance runs against `data/agent.db`. Use `./scripts/stop` before starting a new process. |
| `Tool Requires Confirmation` | High-risk tool triggered | Click the inline **Confirm** button in Telegram to approve execution. |
