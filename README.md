<div align="center">

# 🤖 Telegram Agent Platform
### *Self-hosted, multimodal multi-agent AI platform for Telegram*

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Release: v2.1.0](https://img.shields.io/badge/release-v2.1.0-blueviolet.svg)](CHANGELOG.md)
[![Architecture: Clean](https://img.shields.io/badge/architecture-Clean%20%2F%20Hexagonal-orange.svg)](docs/architecture/overview.md)
[![Security: OWASP Hardened](https://img.shields.io/badge/security-OWASP%20Hardened-red.svg)](docs/security/model.md)

Run a personal AI agent inside Telegram. Tool calling, scheduled tasks, image and document
understanding, live model switching, and a remote control for a local OpenCode session —
all on your own machine, with all data in a local SQLite file.

</div>

---

## Quick start

**Prerequisites:** Python 3.12 or newer, and a bot token from
[@BotFather](https://t.me/BotFather) (send `/newbot`, copy the token).
Docker is optional but makes this a two-command install.

Open a terminal in your home folder — never inside `C:\Windows\system32` — and clone:

```bash
git clone https://github.com/h1ntz0/Agents-Telegram.git
cd Agents-Telegram
```

<details open>
<summary><b>🐧 Linux / macOS</b></summary>

```bash
./scripts/setup     # creates .venv, installs dependencies, runs the wizard
./scripts/start     # start the agent; Ctrl+C stops it
```
</details>

<details open>
<summary><b>🪟 Windows (PowerShell)</b></summary>

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
.\scripts\setup.ps1
.\scripts\start.ps1
```

Using Command Prompt instead? Run `scripts\setup.bat` and `scripts\start.bat`.
If Python 3.12+ is missing, the installer offers to install it through `winget`; close
the window, open a new one, and run setup again.
</details>

<details open>
<summary><b>🐳 Docker</b></summary>

```bash
docker compose run --rm setup    # guided wizard; writes .env
docker compose up -d             # start the agent in the background
docker compose logs -f           # follow the output
```
</details>

Then open Telegram, find your bot, and send `/start`.

> **Secure it first.** Leave `TELEGRAM_ALLOWED_USERS` empty and anyone who guesses your
> bot's username can drive it. The wizard asks for your numeric user ID — get it from
> [@userinfobot](https://t.me/userinfobot).

### Unattended install

For CI, provisioning scripts, or a server you configure from a playbook:

```bash
agent setup -y \
  --bot-token "$TELEGRAM_BOT_TOKEN" \
  --provider openai --model gpt-4o-mini --api-key "$OPENAI_API_KEY" \
  --allowed-users "$MY_TELEGRAM_ID" \
  --timezone Asia/Jakarta
```

No prompts. A token that Telegram rejects fails the install with a non-zero exit code
instead of leaving a half-configured deployment behind.

---

## What you get

| | |
| :--- | :--- |
| 💬 **Chat with tool calling** | The model calls real tools — search, fetch, run code, query GitHub, read and write files — in a loop of up to 5 turns. |
| ⏰ **Proactive tasks** | `/schedule` recurring jobs and `/remind` one-off reminders, both interpreted in your own timezone. The agent messages you first. |
| 👁️ **Images, documents, voice** | Send a photo, a CSV, or a voice note and it just works. Photos go to the model as images; documents are read as text; voice is transcribed when an OpenAI-compatible key is configured. |
| 🔄 **Live model switching** | `/model` and `/provider` switch mid-conversation across 10 providers, with each provider keeping its own active model. |
| 👥 **Multi-agent SDLC** | `/sdlc <task>` runs planner → developer → QA → reviewer and streams progress into the chat. |
| ⌨️ **Remote OpenCode control** | `/oc` mirrors a local `opencode serve` session: live tool-call streaming, model and agent switching, and inline approval buttons for risky operations. |
| 🌐 **English and Indonesian** | `/lang en` or `/lang id`, persisted per user. |
| 🛡️ **Safe by default** | Shell execution off, filesystem writes sandboxed, destructive tools gated behind a button confirmation, SSRF guard on fetching, per-user rate limiting. |

---

## Telegram commands

`/help` lists everything in the chat. Full reference:
[docs/reference/commands.md](docs/reference/commands.md).

| Command | What it does |
| :--- | :--- |
| `/start` | Status: provider, model, persona, language |
| `/model [name]` | Model picker, or switch directly |
| `/provider [name]` | Provider list, or switch provider |
| `/agent <persona>` | `orchestrator`, `researcher`, `coder`, or `qa` |
| `/sdlc <task>` | Run the 4-stage development lifecycle |
| `/oc <sub>` | Control a local OpenCode session |
| `/schedule <time\|cron> <prompt>` | Recurring AI task (`list`, `cancel <id>`) |
| `/remind <time> <text>` | One-off reminder |
| `/chart <type> <labels> <values>` | Bar, line, pie, doughnut, radar charts |
| `/status` | Runtime status |
| `/settings` | Current configuration |
| `/tools` | Registered tools and their permissions |
| `/memory` | Stored memory |
| `/lang [en\|id]` | Change the language |
| `/reset` | Clear the conversation |
| `/cancel` | Discard a pending confirmation |
| `/admin` | Operator diagnostics (needs `ADMIN_TELEGRAM_USERS`) |
| `/help` | Everything above |

---

## Supported providers

Switch at runtime with `/provider`; each provider's credentials live in `.env`.

| Provider | Sample models | Credentials |
| :--- | :--- | :--- |
| **9router** (local gateway) | `ag/gemini-3.8-flash-high`, `ds/deepseek-v4-flash`, `ocg/kimi-k3` | `NINE_ROUTER_API_KEY`, `NINE_ROUTER_BASE_URL` |
| **DeepSeek** | `deepseek-chat`, `deepseek-reasoner` | `DEEPSEEK_API_KEY` |
| **Anthropic** | `claude-3-7-sonnet-20250219`, `claude-3-5-haiku-20241022` | `ANTHROPIC_API_KEY` |
| **Google** | `gemini-2.0-flash`, `gemini-1.5-pro` | `GOOGLE_API_KEY` |
| **OpenAI** | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3-mini` | `OPENAI_API_KEY` |
| **OpenRouter** | `anthropic/claude-3.5-sonnet`, `deepseek/deepseek-r1` | `OPENROUTER_API_KEY` |
| **Ollama** (local, free) | `llama3.2`, `qwen2.5-coder`, `mistral` | `OLLAMA_BASE_URL` — no key |
| **OpenCode Zen** | `muse-spark-1.2-contributor-free`, `oc/big-pickle` | `OPENCODE_ZEN_API_KEY` |
| **OpenCode Go** | `go-code-fast`, `go-sonnet` | `OPENCODE_GO_API_KEY` |
| **Custom** | anything OpenAI-compatible | `CUSTOM_API_KEY`, `CUSTOM_BASE_URL` |

The model list is fetched live from the provider when you run the wizard or `/model`, so
you pick from what your account can actually use. Every provider and environment variable
is documented in [docs/reference/env.md](docs/reference/env.md).

---

## Tools

All 13 tools, with the environment variable that gates each one. Risk tiers are enforced:
`HIGH` tools require an inline button confirmation unless you turn
`REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE` off.

| Tool | Permission | Risk | Default |
| :--- | :--- | :--- | :--- |
| `web_search` | READ | LOW | on |
| `http_fetch` | READ | LOW | on — SSRF-guarded |
| `generate_chart` | READ | LOW | on |
| `get_weather` | READ | LOW | on |
| `github` | READ | LOW | on — write gated by `GITHUB_ALLOW_WRITE` |
| `file_read`, `dir_list` | READ | LOW | on |
| `python_sandbox` | EXECUTE | MEDIUM | on |
| `file_write`, `file_edit` | WRITE | MEDIUM | on — blocked by `FILESYSTEM_READ_ONLY` |
| `opencode_session` | EXECUTE | MEDIUM | on |
| `file_delete` | DESTRUCTIVE | HIGH | on — **asks for confirmation** |
| `shell_execute` | EXECUTE | HIGH | **off** |

Details, parameters and extension instructions:
[docs/integrations/tools.md](docs/integrations/tools.md).

---

## Operating the agent

```bash
agent start --detach     # run in the background, logging to data/agent.log
agent status             # is it up, and with which configuration?
agent stop               # graceful shutdown
agent doctor             # full health check; exits non-zero on any failure
agent backup             # archive .env and data/ into a tarball
```

`agent doctor` is the first thing to run when something is wrong. It checks the Python
version, operating system, configuration schema, any `.env` keys the agent ignores,
your timezone, `.gitignore` coverage, SQLite access, the Telegram connection, the AI
provider, and the OpenCode bridge:

```text
OK  Python Runtime: Python 3.12.10
OK  Operating System: Windows 11 | Git: installed | Docker: installed
OK  Configuration Schema: Valid syntax and schema.
OK  Configuration Keys: Every key in .env is recognised.
OK  Timezone: Schedules use Asia/Jakarta.
OK  Secret Protection (.gitignore): .env is gitignored
OK  Database & Storage: SQLite accessible at data/agent.db
OK  Telegram Connection: Connected as @your_bot (ID: 123456789)
OK  AI Provider: OPENAI (gpt-4o-mini) verified.
--  OpenCode Terminal Bridge: Offline (start with `opencode serve --port 4096` ...)
```

Two agents cannot poll the same bot token at once — the second start is refused with a
clear message rather than producing silent Telegram 409 conflicts. Use `--force` to take
over from an instance that will not stop.

---

## Configuration

Everything lives in `.env`, with `config/defaults/default.yaml` underneath it as the
shipped defaults layer. Full reference: [docs/reference/env.md](docs/reference/env.md).

Re-running `agent setup` is safe: it updates the keys it manages and preserves your
comments and any keys it does not know about.

---

## Troubleshooting

| Symptom | Fix |
| :--- | :--- |
| `python` not found, or version too old | Install Python 3.12+ (`winget install -e --id Python.Python.3.12`, `brew install python@3.12`, or `apt install python3 python3-venv python3-pip`) and re-run setup. |
| PowerShell refuses to run the script | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force` |
| Setup says the token is invalid | Check for a stray space or a truncated paste. Get a fresh token from @BotFather with `/token`. |
| Nothing happens when you message the bot | Run `agent doctor`. Check `TELEGRAM_ALLOWED_USERS` contains your numeric ID, and that only one agent is running (`agent status`). |
| `409 Conflict` in the logs | Two instances are polling the same bot token. `agent stop` then `agent start`. |
| Reminders fire at the wrong hour | Set `TIMEZONE` to your IANA zone (`Asia/Jakarta`, `Europe/Berlin`, …). `agent doctor` flags an invalid value. |
| `.env` setting has no effect | `agent doctor` lists keys the agent never reads, which is usually a typo — `MEMORY_PROVIDER` instead of `STORAGE_PROVIDER`, for example. |
| A tool never gets called | `ALLOW_SHELL` defaults to `false`, and `FILESYSTEM_READ_ONLY` blocks writes. Check `/tools` in Telegram to see what is registered. |
| Docker: agent exits immediately | Run `docker compose run --rm setup` first — the container needs the `.env` it writes. |

---

## Documentation

| Document | Answers |
| :--- | :--- |
| [docs/README.md](docs/README.md) | Index of everything below |
| [docs/reference/commands.md](docs/reference/commands.md) | Every Telegram command and CLI subcommand |
| [docs/reference/env.md](docs/reference/env.md) | Every environment variable |
| [docs/setup/guide.md](docs/setup/guide.md) | Install, systemd, Docker, operations |
| [docs/architecture/overview.md](docs/architecture/overview.md) | Layers, runtime flow, data model |
| [docs/integrations/tools.md](docs/integrations/tools.md) | Tool reference and how to add one |
| [docs/security/model.md](docs/security/model.md) | Threat model and the guards that implement it |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and conventions |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |

---

## Development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

The codebase is clean-architecture: `src/interfaces` → `src/application` → `src/domain`,
with `src/infrastructure` implementing the ports. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Security

* **Local data sovereignty** — chat history, memories and schedules live in `data/agent.db`
  on your machine. Nothing is sent anywhere except your chosen AI provider and Telegram.
* **Secret isolation** — `.env` is gitignored and written with `0600` on POSIX (on Windows
  the file inherits your profile ACLs).
* **SSRF guard** — `http_fetch` rejects private, loopback, link-local and cloud-metadata
  addresses.
* **Path jail** — filesystem tools cannot escape `FILESYSTEM_ROOT_DIR`.
* **Confirmation gate** — destructive tools surface inline Approve / Cancel buttons.
* **Rate limiting** — a per-user sliding window prevents runaway API spend.

Report a vulnerability per [SECURITY.md](SECURITY.md).

---

## License

Distributed under the [MIT License](LICENSE).
