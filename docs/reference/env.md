# Environment variables

Every variable the agent reads, what it does, and its default. The runnable template is
[`.env.example`](../../.env.example); this page is the explanation behind it.

`agent doctor` compares your `.env` against this list and reports any key the agent does
not read, so a typo cannot fail silently.

**Precedence, highest first:** process environment → `.env` → `config/config.yaml` →
`config/defaults/default.yaml` → built-in defaults.

`agent setup` writes `.env` for you. Re-running it updates the keys it manages and leaves
everything else — comments, hand-edited values, extra providers — exactly as it was.

---

## Application

| Variable | Default | Description |
| :--- | :--- | :--- |
| `APP_ENV` | `production` | Deployment marker. Values other than `production` make the log level default to `DEBUG`. |
| `LOG_LEVEL` | *(derived)* | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. Empty means derive it from `APP_ENV`. |
| `TIMEZONE` | `UTC` | IANA name. `/remind`, `/schedule` wall-clock times and cron fields are interpreted in this zone, and results are displayed in it. An unknown name falls back to UTC and is reported by `agent doctor`. |
| `UI_LANG` | `en` | Default UI language: `en` or `id`. Each user can override it with `/lang`. |

## Telegram

| Variable | Default | Description |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | *(required)* | Token from [@BotFather](https://t.me/BotFather). Verified live during setup. |
| `TELEGRAM_ALLOWED_USERS` | *(empty)* | Comma-separated numeric user IDs allowed to use the bot. **Empty means anyone who finds the bot can use it.** |
| `ADMIN_TELEGRAM_USERS` | *(empty)* | Comma-separated user IDs allowed to run `/admin`. **Empty disables `/admin` entirely.** |
| `ENABLE_PRIVATE_CHAT` | `true` | Accept direct messages. |
| `ENABLE_GROUP_CHAT` | `false` | Accept messages in groups and supergroups. |

## AI provider

| Variable | Default | Description |
| :--- | :--- | :--- |
| `AI_PROVIDER` | `openai` | Provider used at startup. One of `9router`, `deepseek`, `anthropic`, `google`, `openai`, `openrouter`, `ollama`, `opencode-zen`, `opencode-go`, `custom`. |
| `AI_API_KEY` | *(empty)* | API key for the startup provider. |
| `AI_MODEL` | `gpt-4o` | Model for the startup provider. |
| `AI_BASE_URL` | *(empty)* | Override the endpoint. Needed for gateways and self-hosted servers, e.g. `http://localhost:20128/v1`. |
| `AI_TEMPERATURE` | `0.2` | Sampling temperature, 0.0–2.0. |
| `AI_MAX_TOKENS` | `2048` | Maximum tokens in a single completion. |
| `AI_TIMEOUT_SECONDS` | `60` | Per-request timeout for model calls. |
| `OPENCODE_SERVER_URL` | `http://127.0.0.1:4096` | Local `opencode serve` endpoint for `/oc` and mirror mode. Must be loopback. |

A malformed number here (`AI_TEMPERATURE=abc`) stops startup with a message naming the
offending key instead of a bare `ValueError`.

### Per-provider credentials

Add credentials for any provider you want to switch to at runtime with `/provider`, without
restarting. Any provider without credentials is listed as `no credentials` and cannot be
selected. Each provider keeps its own active model, so switching never leaks a model
across providers.

| Provider | Variables |
| :--- | :--- |
| 9router | `NINE_ROUTER_API_KEY`, `NINE_ROUTER_BASE_URL`, `NINE_ROUTER_MODEL` |
| DeepSeek | `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` |
| Anthropic | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL` |
| Google | `GOOGLE_API_KEY`, `GOOGLE_BASE_URL`, `GOOGLE_MODEL` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` |
| OpenRouter | `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL` |
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` (no key needed) |
| OpenCode Zen | `OPENCODE_ZEN_API_KEY`, `OPENCODE_ZEN_BASE_URL`, `OPENCODE_ZEN_MODEL` |
| OpenCode Go | `OPENCODE_GO_API_KEY`, `OPENCODE_GO_BASE_URL`, `OPENCODE_GO_MODEL` |
| Custom | `CUSTOM_API_KEY`, `CUSTOM_BASE_URL`, `CUSTOM_MODEL` |

The startup provider also inherits `AI_API_KEY`, `AI_BASE_URL` and `AI_MODEL` when its own
per-provider values are unset.

## Agent persona

| Variable | Default | Description |
| :--- | :--- | :--- |
| `AGENT_NAME` | `Assistant` | Name shown in `/start`. |
| `AGENT_PERSONALITY` | `Professional` | Personality shown in `/settings`. |
| `AGENT_SYSTEM_PROMPT` | *(built-in)* | Base system prompt for the orchestrator persona. The `/agent` personas override it. |

## Tools

Each key below defaults to `true` unless stated otherwise. A disabled tool is not registered
at all, so the model never sees it.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ENABLE_WEB_SEARCH` | `true` | DuckDuckGo web search. |
| `ENABLE_HTTP_FETCH` | `true` | Fetch a page and extract article text. SSRF-guarded. |
| `HTTP_FETCH_TIMEOUT_SECONDS` | `15` | Timeout for `http_fetch`. |
| `ENABLE_CHART` | `true` | Render charts as QuickChart links plus an ASCII fallback. |
| `ENABLE_PYTHON_SANDBOX` | `true` | Run Python for maths, statistics and data work. |
| `PYTHON_SANDBOX_TIMEOUT_SECONDS` | `5` | Sandbox timeout, capped at 30. |
| `ENABLE_WEATHER` | `true` | Open-Meteo forecast and geocoding (no API key). |
| `WEATHER_TIMEOUT_SECONDS` | `12` | Timeout for `get_weather`. |
| `ENABLE_GITHUB` | `true` | GitHub REST access. Works on public repos without a token. |
| `GITHUB_TOKEN` | *(empty)* | Personal access token: raises the rate limit, enables private repos. |
| `GITHUB_DEFAULT_REPO` | *(empty)* | `owner/repo` used when a tool call omits the repository. |
| `GITHUB_ALLOW_WRITE` | `false` | Allow issue creation. |
| `ENABLE_FILESYSTEM` | `true` | File read/write/edit/delete/list tools. |
| `FILESYSTEM_ROOT_DIR` | `./data` | Workspace root. `.` gives the agent the whole project directory. Every path is jailed to this directory. |
| `FILESYSTEM_READ_ONLY` | `true` | When true, `file_write`, `file_edit` and `file_delete` refuse to run. |
| `ALLOW_SHELL` | `false` | **High risk.** Enable `shell_execute`. |
| `ALLOW_DESTRUCTIVE_SHELL` | `false` | **High risk.** Allow commands such as `rm -rf`. Only relevant when `ALLOW_SHELL=true`. |
| `SHELL_TIMEOUT_SECONDS` | `30` | Timeout for `shell_execute`. |
| `REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE` | `true` | Ask for an inline Telegram confirmation before a high-risk tool runs. Setting this to `false` lets destructive tools run unattended. |

## Storage and memory

| Variable | Default | Description |
| :--- | :--- | :--- |
| `MEMORY_ENABLED` | `true` | When false, stored memories are not injected into the prompt and `/memory` reports it as disabled. Per-user settings (active provider, model, language) are stored separately and keep working. |
| `STORAGE_PROVIDER` | `sqlite` | Storage backend. |
| `DATABASE_PATH` | `data/agent.db` | SQLite file holding sessions, messages, memories and scheduled jobs. |
| `DATA_RETENTION_DAYS` | `0` | Delete stored memories older than this at startup. `0` keeps them forever. |

## Rate limiting

| Variable | Default | Description |
| :--- | :--- | :--- |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `15` | Per-user sliding-window limit. Exceeding it replies "rate limit exceeded" instead of calling the model. |

---

## Renamed and removed keys

**Renamed** — both spellings work, the canonical name wins when both are set:

| Old | Canonical |
| :--- | :--- |
| `MEMORY_PROVIDER` | `STORAGE_PROVIDER` |
| `MEMORY_RETENTION_DAYS` | `DATA_RETENTION_DAYS` |

**Removed in v2.1.0** — these were read into the configuration object but never used by any
code path, so they are now rejected as inert keys instead of pretending to work:

| Variable | Why it went |
| :--- | :--- |
| `TELEGRAM_MODE` | The agent is long-polling only; webhook mode was never implemented. |
| `TELEGRAM_WEBHOOK_URL` | Ditto. |
| `PORT` | Nothing ever listened on a port. |
| `DAILY_BUDGET_USD` | A spend cap needs a per-model price table that does not exist; the setting had no effect. |

`agent doctor` lists any of these still present in your `.env`.
