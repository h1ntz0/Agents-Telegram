# Security Policy

## Supported Versions

Security fixes are shipped for the current release line only.

| Version | Supported          |
| ------- | ------------------ |
| 2.1.x   | :white_check_mark: |
| < 2.1   | :x:                |

## Reporting Security Vulnerabilities

If you discover a security vulnerability in this project, do not open a public issue.
Please submit a report directly to the repository maintainer.

Reports should include:
- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact

We aim to acknowledge reports within a few days and will coordinate disclosure with
you once a fix is available.

## Secrets Never Leave Your Machine

This platform is self-hosted and privacy-preserving by design. There is no hosted
backend, no telemetry endpoint, and no inbound HTTP server: the agent only makes
**outbound** calls to the Telegram Bot API (long polling) and to the AI provider you
configure yourself.

What is stored locally, and where:

- **`.env`** — your Telegram bot token and AI provider API keys. The setup wizard
  writes it with `0600` permissions (`owner` read/write only) on macOS, Linux and
  Git Bash. On Windows, `chmod` semantics are limited, so the file inherits your user
  profile ACLs — keep it inside your user directory and never share it.
- **`data/agent.db`** — the SQLite database holding your chat history, sessions, tool
  results and scheduled jobs. It never leaves your machine and is excluded from git.
- **`.env` and the database under `data/`** are excluded by `.gitignore`. Never commit
  them, and never paste their contents into an issue, a pull request, or a bug report.

The only data that leaves your machine is what you send to the AI provider you
configured — the conversation text needed to produce a completion, sent directly to
that provider's API over HTTPS. If you switch to a local provider such as Ollama,
nothing leaves your machine at all.

Rotating a compromised secret is immediate: revoke the key at your provider, generate a
new one, then re-run `python -m src setup` (or edit `.env` directly) and restart the
agent.

## If a Credential Ends Up in a Commit

A token that reaches a public repository is public. Assume it has already been copied:
bots scrape new commits, forks and mirrors within minutes.

1. **Revoke before you clean up.** Rotate the credential at the source — BotFather
   `/revoke` for a Telegram bot token, your provider's key dashboard for an API key.
   Until a stolen bot token is revoked, whoever holds it can read the bot's update
   stream and impersonate the bot, so also set `TELEGRAM_ALLOWED_USERS` to your own
   user ID rather than leaving the allowlist empty.
2. **Write the new value to `.env`** and restart the agent. Never reuse the leaked value.
3. **Purge the history**, not just the current file:
   ```bash
   git filter-repo --replace-text replacements.txt   # "old-secret==>REDACTED"
   git push --force origin main
   ```
   Rewriting history changes every commit hash; coordinate with anyone who has a clone.
4. **Ask GitHub to drop the cached copies.** After a force push the old commits are
   unreachable but still served by direct SHA URL for a while. Use GitHub's
   "Sensitive data removal" contact form, quoting the affected commits.
5. **Confirm the purge.** `gitleaks git --config .gitleaks.toml` must report no leaks
   across the entire history, and `git log -S '<secret>' --all` must return nothing.

## Security Practices in this Codebase

- **No Secrets in Logs**: All structured JSON logs run through an automated regex scrubber before output. The scrubber matches credentials embedded in URLs (`https://api.telegram.org/bot<id>:<token>/getMe`), which is the shape `httpx` logs at INFO level.
- **Automated Secret Scanning**: Every push, pull request and a weekly schedule run `gitleaks` over the entire git history (`.github/workflows/secret-scan.yml`), with rules for the Telegram bot token and 9router key formats in `.gitleaks.toml`. The same config backs the optional pre-commit hook, so a credential is caught before it is committed.
- **SSRF Prevention**: All outbound HTTP fetch operations validate resolved IP addresses against loopback, private, and cloud metadata ranges.
- **Strict Allowlist**: Telegram user IDs are validated on message ingress before any message processing or AI generation starts.
- **Interactive Confirmations**: Tools with destructive capabilities (`rm`, `git push --force`, table drops) require explicit Telegram inline button confirmation.
- **File System Sandboxing**: All file read/write operations enforce directory jail boundaries via path resolution.
