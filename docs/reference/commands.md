# Commands reference

Two command surfaces: what you can send to the bot in Telegram, and what you can run on
the machine hosting it. Both are generated from the same code (`BOT_COMMAND_KEYS` in
`src/infrastructure/telegram/adapter.py` and `build_parser()` in
`src/interfaces/cli/main.py`), so this page is the only place they are written down.

---

## Telegram commands

Send these in a private chat with your bot. The menu is registered with Telegram at
startup, so typing `/` shows autocomplete.

| Command | Arguments | What it does |
| :--- | :--- | :--- |
| `/start` | — | Greeting plus current provider, model, persona and language |
| `/model` | `[name]` | Without arguments: an inline keyboard of live models for the active provider. With a name: switch immediately (`/model ds/deepseek-v4-flash`) |
| `/provider` | `[name]` | Without arguments: every provider with `configured` / `no credentials`. With a name: switch the provider for your user, persisted across restarts |
| `/agent` | `[persona]` | Switch the system persona: `orchestrator`, `researcher`, `coder`, `qa` |
| `/sdlc` | `<task>` | Run the 4-stage lifecycle (planner → developer → QA → reviewer) with live progress edits |
| `/oc` | `[sub]` | Remote-control a local `opencode serve` session. Subcommands: `list`, `attach <id>`, `detach`, `new [title]`, `send <prompt>`, `stop`, `model <id> [providerID]`, `agent <name>`, `agents`, `models`, `commands`, `skills`, `diff` |
| `/schedule` | `<time\|cron> <prompt>` | Create a recurring job. Accepts `every 1h`, `10m`, or a 5-field cron. Subcommands: `list`, `cancel <job_id>` |
| `/remind` | `<time> <text>` | One-off reminder. Accepts `10m`, `in 2h`, `18:00`, or an ISO timestamp |
| `/chart` | `<type> <labels> <values>` | Render a chart. Types: `bar`, `line`, `pie`, `doughnut`, `radar`. Also accepts `bar Title \| Jan: 10, Feb: 20` |
| `/status` | — | Runtime status: provider, model, persona, language, memory, active tool count |
| `/settings` | — | Agent name, personality, provider, model, temperature |
| `/tools` | — | Every registered tool with its permission level |
| `/memory` | — | Stored memories (settings keys starting with `_` are hidden) |
| `/lang` | `[en\|id]` | Show or change your language. Persisted per user |
| `/reset` | — | Clear this chat's conversation history |
| `/cancel` | — | Discard the confirmation that is waiting for your approval |
| `/help` | — | All of the above |
| `/admin` | — | Operator diagnostics (uptime, users, jobs, pending confirmations). Requires your user ID in `ADMIN_TELEGRAM_USERS` |

### Times are local

`/remind 18:00`, `/schedule 0 9 * * *` and naive ISO timestamps are interpreted in
`TIMEZONE`. Confirmation messages show the resolved time with its UTC offset, for example
`2026-03-01 18:00:00 +0700`.

### Delivery is one message at a time

A message longer than 4000 characters is split into several Telegram messages. The agent
answers a prompt with at most 5 model turns (the ReAct tool-calling loop).

---

## CLI subcommands

Run as `agent <subcommand>`, `python -m src <subcommand>`, or through the launcher scripts
in `scripts/`.

| Command | Key flags | What it does |
| :--- | :--- | :--- |
| `setup` | `--advanced`, `-y/--non-interactive`, `--bot-token`, `--provider`, `--model`, `--api-key`, `--base-url`, `--allowed-users`, `--lang en\|id`, `--timezone`, `--force` | Configure the agent. Interactive by default; fully headless with `-y`. Merges into an existing `.env` instead of overwriting it |
| `start` | `--detach`, `--force` | Run the agent. Foreground by default. `--detach` backgrounds it and appends to `data/agent.log`. `--force` takes over from a running instance |
| `stop` | — | Stop the running agent. Exits 0 when stopped or when nothing was running |
| `status` | `--check` | Show status and configuration. `--check` prints nothing and exits 1 when the agent is down, for healthchecks |
| `doctor` | — | Health checks: Python, OS, config schema, inert `.env` keys, timezone, `.gitignore`, SQLite, Telegram, AI provider, OpenCode bridge. **Exits 1 when any check FAILs** |
| `config` | `show` \| `reset` | Print the resolved configuration with secrets masked, or delete the `.env` file |
| `backup` | — | Archive `.env` and `data/` into `backup_agent_<timestamp>.tar.gz` |
| `test` | `--coverage` | Run the pytest suite |
| `version` | — | Print the version |

Global flags:

| Flag | Notes |
| :--- | :--- |
| `--env PATH` | Environment file to use. Accepted **before or after** the subcommand |
| `--version` | Same as `version` |
| `-h`, `--help` | Usage |

### Examples

```bash
# Interactive configuration
agent setup

# Unattended, for Docker, CI, or a provisioning script
agent setup -y --bot-token "$TELEGRAM_BOT_TOKEN" --provider openai \
    --model gpt-4o-mini --api-key "$OPENAI_API_KEY" \
    --allowed-users 12345678 --lang en --timezone Asia/Jakarta

# Run in the background, then inspect
agent start --detach
agent status
tail -f data/agent.log

# Take over from an instance that will not stop
agent start --force

# Use a different configuration file
agent --env .env.staging start
agent status --env .env.staging

# Healthcheck exit code
agent status --check && echo up || echo down
```

---

## Launcher scripts

These wrap the CLI so you do not have to manage a virtual environment by hand. They
create `.venv` and install dependencies on first use, forward every argument to
`python -m src`, and propagate its exit code.

| Linux / macOS | Windows PowerShell | Windows CMD |
| :--- | :--- | :--- |
| `./scripts/setup` | `.\scripts\setup.ps1` | `scripts\setup.bat` |
| `./scripts/start` | `.\scripts\start.ps1` | `scripts\start.bat` |
| `./scripts/stop` | `.\scripts\stop.ps1` | `scripts\stop.bat` |
| `./scripts/doctor` | `.\scripts\doctor.ps1` | `scripts\doctor.bat` |

All three variants accept the same flags, for example
`.\scripts\setup.ps1 --advanced` or `./scripts/start --detach`.
