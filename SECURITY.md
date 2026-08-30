# Security Policy

## Reporting Security Vulnerabilities

If you discover a security vulnerability in this project, do not open a public issue. Please submit a report directly to the repository maintainer.

Reports should include:
- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact

## Security Practices in this Codebase

- **No Secrets in Logs**: All structured JSON logs run through an automated regex scrubber before output.
- **SSRF Prevention**: All outbound HTTP fetch operations validate resolved IP addresses against loopback, private, and cloud metadata ranges.
- **Strict Allowlist**: Telegram user IDs are validated on message ingress before any message processing or AI generation starts.
- **Interactive Confirmations**: Tools with destructive capabilities (`rm`, `git push --force`, table drops) require explicit Telegram inline button confirmation.
- **File System Sandboxing**: All file read/write operations enforce directory jail boundaries via path resolution.
