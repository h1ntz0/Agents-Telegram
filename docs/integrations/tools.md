# Tool Integration Guide

## Available Built-in Tools

1. **`web_search`**:
   - Searches the web using DuckDuckGo HTML endpoint.
   - Wraps snippets in untrusted prompt delimiters.
   - Permission: `READ` | Risk: `LOW`.

2. **`file_read` & `file_write`**:
   - Reads and writes files within `FILESYSTEM_ROOT_DIR`.
   - Prevents path traversal using common path resolution.
   - Permission: `READ` / `WRITE` | Risk: `LOW` / `MEDIUM`.

3. **`github`**:
   - Inspects repositories, reads issues, and lists PRs.
   - Optional issue creation requiring `GITHUB_ALLOW_WRITE=true`.
   - Permission: `READ` / `WRITE` | Risk: `LOW`.

4. **`shell_execute`**:
   - Disabled by default (`ALLOW_SHELL=false`).
   - Filters destructive commands (`rm -rf`, `mkfs`, `dd`, `shutdown`).
   - Permission: `EXECUTE` | Risk: `HIGH` (Requires confirmation).
