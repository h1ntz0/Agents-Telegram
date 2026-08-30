# Security & Safety Model

## 1. Secret Protection
- **Storage**: Credentials reside only in `.env` with strict `0600` permissions.
- **Git Hygiene**: `.env` is permanently excluded via `.gitignore`.
- **Logs**: All logs pass through regex scrubbing before writing to stdout or disk.

## 2. Authorization & Allowlist
- By default, `TELEGRAM_ALLOWED_USERS` restricts access to specified Telegram user IDs.
- Messages from unlisted users return a static rejection message without revealing system details.

## 3. Network & SSRF Guard
- All outbound HTTP requests pass through `is_safe_url()`.
- Resolves DNS hostnames and rejects private RFC 1918 ranges, localhost, link-local addresses, and cloud metadata IPs (`169.254.169.254`).

## 4. Dangerous Tool Confirmations
- Tools marked with `DESTRUCTIVE` permissions or `HIGH`/`CRITICAL` risk pause execution and send an interactive confirmation prompt with inline buttons to the Telegram chat.
