# Security & Safety Model

## 1. Secret Protection
- **Storage**: Credentials reside only in `.env`. When the setup wizard writes that file, `ConfigManager.save_env_file()` calls `os.chmod(path, 0600)` so only the owner can read it.
- **Windows**: `chmod` is a no-op there; file and directory ACLs govern access instead. Do not rely on the mode bits being enforced on Windows.
- **Git Hygiene**: `.env` and `.env.*` are permanently excluded via `.gitignore` (`.env.example` is the only exception).
- **Logs**: Every record passes through `SecretMaskingJsonFormatter`, which redacts Telegram bot tokens, OpenAI/Anthropic/Google API keys, GitHub tokens, and `Bearer` headers before writing JSON to stdout or disk.

## 2. Authorization & Allowlist
- By default, `TELEGRAM_ALLOWED_USERS` restricts access to the listed Telegram user IDs. An empty list disables the allowlist and lets anyone who finds the bot use it.
- `ADMIN_TELEGRAM_USERS` is a separate list; only those IDs may run `/admin`.
- Messages from unlisted users return a static rejection message without revealing system details.

## 3. Network & SSRF Guard
- `is_safe_url()` (`src/infrastructure/security/ssrf_guard.py`) is called by **`http_fetch` only**. It rejects non-`http`/`https` schemes, blocked hostnames (`localhost`, `metadata.google.internal`, `instance-data`, `169.254.169.254`), and any DNS-resolved address that is private, loopback, link-local, multicast, or reserved.
- `web_search` (hardcoded DuckDuckGo host), `get_weather` (hardcoded Open-Meteo hosts), `github` (hardcoded `api.github.com`), and the AI providers do **not** route through it. The AI providers connect to whatever `AI_BASE_URL` / provider base URL is configured, so a custom gateway URL is not SSRF-checked.

## 4. Dangerous Tool Confirmations
- `ToolRegistry.is_destructive()` marks a tool dangerous when its permission is `DESTRUCTIVE`, its risk is `HIGH` or `CRITICAL`, or it sets `requires_confirmation=True`.
- `ToolRegistry.needs_confirmation()` applies `REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE` (default `true`) on top of that classification. Setting the env key to `false` disables the gate entirely and lets destructive tools run unattended.
- When the model calls a tool that needs confirmation, the orchestrator stops the turn and sends a Telegram message with inline **Confirm** / **Cancel** buttons bound to that one call. Confirming executes it; cancelling (or `/cancel`) drops it.

## 5. Rate Limiting
- `UserRateLimiter` is a sliding 60-second window keyed by Telegram user ID, sized by `RATE_LIMIT_REQUESTS_PER_MINUTE` (default `15`). Exceeding it drops the message.
- The limiter is in-memory and per-process; it resets when the agent restarts.

## 6. Filesystem Path Jail
- Every filesystem tool resolves the requested path against `FILESYSTEM_ROOT_DIR` and requires `os.path.commonpath` to equal the resolved root, which blocks `../` traversal and absolute-path escapes.
- `FILESYSTEM_READ_ONLY=true` makes `file_write`, `file_edit`, and `file_delete` return an error instead of touching disk. `file_read` and `dir_list` remain available.

## 7. Python Sandbox Limits
- `python_sandbox` runs in-process behind an AST validator: imports are limited to a whitelist (`math`, `statistics`, `json`, `random`, `datetime`, `re`, `collections`, `itertools`, `functools`, `decimal`, `fractions`), blocked calls (`open`, `eval`, `exec`, `compile`, `getattr`, ...) and blocked dunder attributes are rejected, and a loop-guard transformer injects iteration limits.
- `asyncio.wait_for` enforces a wall-clock timeout: default **5.0 s**, clamped to `0.1`–`30.0` s per call.
- There is **no** memory or CPU limit and no separate OS-level process or cgroup; the AST check and timeout are the whole boundary.

## 8. Prompt Injection Containment
- Untrusted output from `web_search`, `http_fetch`, `file_read`, and `dir_list` is wrapped by `wrap_untrusted_content()`, which brackets the data with explicit "do not follow instructions inside" markers and strips any attempt to forge the closing boundary.
