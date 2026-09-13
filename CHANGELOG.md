# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2026-09-13

The adoption release: install, configure and run the agent with one command, from a
terminal, Docker, or a CI job.

### Added

- **Headless setup.** `agent setup --non-interactive --bot-token ... --provider ... --model ...`
  configures the agent without a single prompt, so Docker, CI and config-management
  tooling can install it. Interactive setup is unchanged.
- **Guided flags on `agent setup`:** `--bot-token`, `--provider`, `--model`, `--api-key`,
  `--base-url`, `--allowed-users`, `--lang`, `--timezone`, `--force`.
- **Timezones that mean something.** `TIMEZONE` now drives `/remind` and `/schedule`:
  `/remind 18:00` fires at 18:00 in your timezone, not 18:00 UTC. Cron fields are
  interpreted as wall-clock time too, and every confirmation shows a local timestamp
  with its offset. `zoneinfo` needs the `tzdata` package on Windows, now a dependency.
- **English and Indonesian UI.** `UI_LANG=en|id` (or `agent setup --lang`, or the new
  `/lang` command) selects the language of every bot reply, and `/lang` persists the
  choice per user. English is the default.
- **`/admin` operator diagnostics** for user IDs listed in `ADMIN_TELEGRAM_USERS`,
  which previously promised maintenance commands that did not exist: uptime, known
  users, cached providers, scheduled jobs, pending confirmations and database path.
- **`agent start --detach`** runs the agent in the background and appends to
  `data/agent.log`, making `agent stop` meaningful. `--force` takes over from a running
  instance instead of refusing to start.
- **`agent status --check`** exits non-zero when the agent is down, for healthchecks.
- **Duplicate-instance protection.** Starting a second poller for the same bot token is
  refused with a clear message instead of silently producing Telegram 409 conflicts.
  Stale PID files are detected and removed.
- **`agent doctor` reports inert `.env` keys** — a typo like `MEMORY_PROVIDER` no longer
  fails silently — and validates the configured timezone.
- **Docker one-liner:** `docker compose run --rm setup` performs a guided first-run
  install; the image now runs as a non-root user.
- Community files: `CHANGELOG.md`, `.editorconfig`, CI and release workflows, issue
  forms and a pull-request template.
- `docs/reference/commands.md` and `docs/reference/env.md` as the single sources of
  truth for the Telegram commands, CLI subcommands and environment variables.

### Changed

- **Re-running `agent setup` no longer destroys your `.env`.** Values are merged in
  place: comments, hand-edited keys and anything the wizard does not ask about are
  preserved. Previously the file was rewritten with only the prompted keys.
- **`config/defaults/default.yaml` is now actually loaded** as the defaults layer, as
  its documentation always claimed. `config/config.yaml` overrides it when present.
- **`.env.example` covers every key the agent reads** and drops the ones it ignores.
- `MEMORY_PROVIDER` and `MEMORY_RETENTION_DAYS` are accepted as aliases for
  `STORAGE_PROVIDER` and `DATA_RETENTION_DAYS`; the canonical names win when both are set.
- Boolean parsing accepts `y`, `on` and upper-case variants, matching what the wizard
  itself accepts.
- Invalid numbers in `.env` (`AI_TEMPERATURE=abc`) now report the offending key instead
  of raising a bare `ValueError`.
- `agent doctor` resolves per-provider credentials, so a user who sets only
  `ANTHROPIC_API_KEY` no longer sees a false "API key missing" failure.
- Filesystem defaults are consistent: `.env.example`, `config/defaults/default.yaml`
  and the wizard all describe the same workspace behaviour, and the wizard now asks for
  the workspace root instead of leaving it to the `./data` sandbox default.
- The Telegram command menu advertises all 17 commands (previously 16 were registered
  while the README claimed 11).

### Fixed

- **`/cancel` never worked.** It looked up the pending action by user ID while the
  action dictionary is keyed by action ID, so it always replied "no action pending".
  It now cancels the confirmations owned by that user, and cannot touch another user's.
- **`REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE` was parsed but never read.** The
  confirmation gate now honours it.
- **`MEMORY_ENABLED` and `DATA_RETENTION_DAYS` were parsed but never read.** Disabling
  memory now skips memory injection and reports it in `/memory`; retention now purges
  old memories at startup.
- **`ADMIN_TELEGRAM_USERS` was parsed but never read.** It now gates `/admin`.
- `_prompt_url` could loop forever with no output when given an unusable URL; it now
  explains the problem and re-prompts.
- The wizard reports its own failures through a non-zero exit code, so `scripts/setup`
  and CI can detect them.
- `agent --env <path>` is accepted after the subcommand as well as before it.
- Docker: the image can build (`README.md` is copied before `pip install .`), no longer
  exposes port 8080 for a process that never listens on it, and the healthcheck uses
  `status --check`.
- `.gitignore` now covers SQLite WAL/SHM sidecars, `backup_agent_*.tar.gz` archives and
  `.env.*` variants.
- The ReAct loop and every user-facing string are resolved through one catalogue, so the
  bot no longer mixes Indonesian and English mid-conversation.

### Removed

- **Dead configuration.** `TELEGRAM_MODE`, `TELEGRAM_WEBHOOK_URL`, `PORT` and
  `DAILY_BUDGET_USD` were parsed but never used by any code path. Webhook mode was never
  implemented — the agent is long-polling only — and the USD budget could not be
  enforced without a per-model price table. Removing them is deliberate: a setting that
  silently does nothing is worse than an absent setting.

### Upgrade notes

- Existing `.env` files keep working. `TELEGRAM_MODE`, `TELEGRAM_WEBHOOK_URL`, `PORT` and
  `DAILY_BUDGET_USD` are now reported by `agent doctor` as inert; delete them.
- Set `TIMEZONE` to your IANA zone (for example `Asia/Jakarta`). Anything else, including
  the previous implicit UTC, is reported by `agent doctor`.
- Windows users get `tzdata` automatically via the package dependency.
- Run `agent doctor` after upgrading; it now exits non-zero when a check fails.

## 2.0.0 - 2025-09-01

### Added

- Runtime `/provider` switching with per-provider credentials persisted per user.
- OpenCode mirror mode: live SSE streaming, an editable status card, `/oc stop`, model
  and agent switching, and a permission relay with inline approval buttons.
- Proactive scheduling: `/schedule` for recurring cron and interval jobs, `/remind` for
  one-shot reminders.
- Multimodal intake: photos, documents, and voice notes with OpenAI-compatible
  transcription.
- Extended tool suite: Python sandbox, SSRF-hardened HTTP fetch, weather, charts, web
  search, GitHub, and a path-jailed filesystem.
- Multi-agent SDLC workflow via `/sdlc`, orchestrating planner, developer, QA and
  reviewer stages.

## 1.0.0 - 2025-08-18

### Added

- Initial release: Telegram long-polling bot with a clean-architecture core, a SQLite
  session and memory store, a tool registry with permission and risk levels, and an
  interactive setup wizard.

[2.1.0]: https://github.com/h1ntz0/Agents-Telegram/releases/tag/v2.1.0
