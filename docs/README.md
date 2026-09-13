# Documentation

Operator and integrator documentation for the Telegram Agent Platform (v2.1.0). Every page is written against the v2.1.0 source tree; where a claim is checkable in code, the source file is named.

For the feature tour and quick start, see the project [README](../README.md).

## Guides

| Page | Answers |
| :--- | :--- |
| [architecture/overview.md](architecture/overview.md) | How the layers fit together, what the ReAct loop does, how attachments are handled, and how the process is supervised. |
| [integrations/tools.md](integrations/tools.md) | Every built-in tool with its real parameters, permission and risk tier, defaults, the env key that gates it, plus the OpenCode mirror mode and how to add a tool. |
| [security/model.md](security/model.md) | How secrets, the allowlist, the SSRF guard, the confirmation gate, rate limiting, the filesystem jail, and the Python sandbox actually behave. |
| [setup/guide.md](setup/guide.md) | Installing, running, supervising, containerising, and troubleshooting an installation. |

## Reference

| Page | Answers |
| :--- | :--- |
| [reference/commands.md](reference/commands.md) | Every Telegram command and CLI subcommand with its flags, generated from `BOT_COMMAND_KEYS` and `build_parser()`. |
| [reference/env.md](reference/env.md) | Every environment variable the agent reads, its default, and the keys that no longer do anything. |

Both reference pages are the single source of truth for the surfaces they cover. `.env.example` is the checked-in template the setup wizard writes; `agent doctor` compares your `.env` against it and reports inert keys.
