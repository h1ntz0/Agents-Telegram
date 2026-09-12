"""GitHub integration tool for inspecting repositories, reading files, exploring directories, issues, and pull requests."""

from typing import Any, Dict, Optional
import httpx
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult
from src.infrastructure.security.prompt_guard import wrap_untrusted_content


def _clean_repo_name(repo: str) -> str:
    """Normalize and clean repository identifier into 'owner/repo' format."""
    clean = (repo or "").strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break
    clean = clean.strip("/").removesuffix(".git")
    return clean


class GitHubTool(BaseTool):
    """GitHub API client for repository file reading, directory exploration, and issue management."""

    def __init__(self, token: str = "", default_repo: str = "", allow_write: bool = False, timeout: float = 25.0):
        self.token = token
        self.default_repo = _clean_repo_name(default_repo)
        self.allow_write = allow_write
        self.timeout = timeout
        self.base_url = "https://api.github.com"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="github",
            description=(
                "Access GitHub REST API to read file contents, list files/directories, view repository "
                "details, read issues, or inspect pull requests. Works with any public repository without "
                "a token, or private repositories when GITHUB_TOKEN is set. "
                "Actions: 'get_file' (read file content), 'list_files' (browse directory contents), "
                "'get_repo' (repo metadata), 'list_issues', 'get_issue', 'create_issue'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "get_file",
                            "read_file",
                            "list_files",
                            "list_dir",
                            "get_repo",
                            "list_issues",
                            "get_issue",
                            "create_issue"
                        ],
                        "description": "GitHub action: 'get_file' to read file contents, 'list_files' to browse repository directory, 'get_repo' for repo info."
                    },
                    "repo": {
                        "type": "string",
                        "description": "Target repository in 'owner/repo' format (e.g. 'RizqiAulia23/toko_tinta')."
                    },
                    "path": {
                        "type": "string",
                        "description": "File or folder path in the repo (e.g. 'index.html', 'css/nota.css', 'src/'). Required for get_file and list_files."
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Alias for 'path'."
                    },
                    "ref": {
                        "type": "string",
                        "description": "Optional branch, tag, or commit SHA (e.g. 'main', 'master'). Defaults to default branch."
                    },
                    "issue_number": {
                        "type": "integer",
                        "description": "Issue or Pull Request number (for get_issue)."
                    },
                    "title": {
                        "type": "string",
                        "description": "Title for new issue (for create_issue)."
                    },
                    "body": {
                        "type": "string",
                        "description": "Body markdown for new issue (for create_issue)."
                    }
                },
                "required": ["action"]
            },
            permission=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            requires_confirmation=False
        )

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Telegram-Agent-Runtime"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        raw_action = (arguments.get("action") or "").strip().lower()
        raw_repo = arguments.get("repo") or self.default_repo
        repo = _clean_repo_name(raw_repo)

        if not repo or "/" not in repo:
            return ToolResult(
                content="Repository name must be specified as 'owner/repo' (e.g. 'RizqiAulia23/toko_tinta').",
                is_error=True
            )

        headers = self._get_headers()
        path = (arguments.get("path") or arguments.get("file_path") or "").strip().lstrip("/")
        ref = (arguments.get("ref") or arguments.get("branch") or "").strip()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # -------------------------------------------------------------
                # 1. READ FILE CONTENT (get_file / read_file)
                # -------------------------------------------------------------
                if raw_action in ("get_file", "read_file", "get_file_contents", "get_contents", "view_file"):
                    if not path:
                        return ToolResult(
                            content="Parameter 'path' (or 'file_path') is required to read a file from the repository.",
                            is_error=True
                        )

                    url = f"{self.base_url}/repos/{repo}/contents/{path}"
                    params = {"ref": ref} if ref else {}

                    # Use raw accept header to fetch content directly without base64 limits
                    raw_headers = dict(headers)
                    raw_headers["Accept"] = "application/vnd.github.v3.raw"
                    res = await client.get(url, headers=raw_headers, params=params)

                    if res.status_code == 200:
                        # Check if response is actually a directory listing JSON
                        ctype = res.headers.get("content-type", "")
                        if "json" in ctype and res.text.strip().startswith("["):
                            try:
                                items = res.json()
                                if isinstance(items, list):
                                    lines = [f"[{i.get('type', 'file')}] {i.get('name')}" for i in items]
                                    return ToolResult(
                                        content=f"'{path}' is a directory containing:\n" + "\n".join(lines) +
                                                "\n\nSpecify a file path to read its content."
                                    )
                            except Exception:
                                pass

                        text = res.text
                        max_chars = 120000
                        if len(text) > max_chars:
                            text = text[:max_chars] + f"\n\n... [Truncated: {len(res.text) - max_chars} characters remaining]"

                        return ToolResult(content=wrap_untrusted_content(text, source=f"GitHub: {repo}/{path}"))

                    elif res.status_code == 404:
                        return ToolResult(
                            content=f"File not found in {repo}: '{path}' (HTTP 404). Check if the path and branch are correct.",
                            is_error=True
                        )
                    else:
                        return ToolResult(
                            content=f"GitHub API Error [{res.status_code}]: {res.text[:300]}",
                            is_error=True
                        )

                # -------------------------------------------------------------
                # 2. LIST DIRECTORY / REPO CONTENTS (list_files / list_dir)
                # -------------------------------------------------------------
                elif raw_action in ("list_files", "list_dir", "list_directory", "get_tree", "ls"):
                    url = f"{self.base_url}/repos/{repo}/contents/{path}" if path else f"{self.base_url}/repos/{repo}/contents"
                    params = {"ref": ref} if ref else {}

                    res = await client.get(url, headers=headers, params=params)
                    if res.status_code == 200:
                        data = res.json()
                        if isinstance(data, list):
                            lines = [
                                f"[{item.get('type', 'file')}] {item.get('name')} "
                                f"(path: {item.get('path')}{', size: ' + str(item.get('size')) + ' bytes' if item.get('type') == 'file' else ''})"
                                for item in data
                            ]
                            return ToolResult(
                                content=wrap_untrusted_content(
                                    "\n".join(lines) if lines else "(empty directory)",
                                    source=f"GitHub Contents: {repo}/{path or '.'}"
                                )
                            )
                        elif isinstance(data, dict) and data.get("type") == "file":
                            return ToolResult(
                                content=f"'{path}' is a file ({data.get('size')} bytes). Use action='get_file' to read its content."
                            )
                        return ToolResult(content=str(data))
                    elif res.status_code == 404:
                        return ToolResult(
                            content=f"Directory or path not found in {repo}: '{path or '.'}' (HTTP 404).",
                            is_error=True
                        )
                    else:
                        return ToolResult(
                            content=f"GitHub API Error [{res.status_code}]: {res.text[:300]}",
                            is_error=True
                        )

                # -------------------------------------------------------------
                # 3. REPOSITORY METADATA (get_repo)
                # -------------------------------------------------------------
                elif raw_action == "get_repo":
                    url = f"{self.base_url}/repos/{repo}"
                    res = await client.get(url, headers=headers)
                    if res.status_code != 200:
                        return ToolResult(content=f"GitHub API Error: {res.status_code} - {res.text}", is_error=True)
                    data = res.json()
                    summary = (
                        f"Repository: {data.get('full_name')}\n"
                        f"Description: {data.get('description')}\n"
                        f"Stars: {data.get('stargazers_count')} | Forks: {data.get('forks_count')}\n"
                        f"Open Issues: {data.get('open_issues_count')}\n"
                        f"Default Branch: {data.get('default_branch')}"
                    )
                    return ToolResult(content=wrap_untrusted_content(summary, source=f"GitHub: {repo}"))

                # -------------------------------------------------------------
                # 4. LIST ISSUES (list_issues)
                # -------------------------------------------------------------
                elif raw_action == "list_issues":
                    url = f"{self.base_url}/repos/{repo}/issues?state=open&per_page=10"
                    res = await client.get(url, headers=headers)
                    if res.status_code != 200:
                        return ToolResult(content=f"GitHub API Error: {res.status_code} - {res.text}", is_error=True)
                    issues = res.json()
                    if not issues:
                        return ToolResult(content=f"No open issues found for {repo}.")
                    lines = [f"#{i['number']} - {i['title']} (by {i['user']['login']})" for i in issues]
                    return ToolResult(content=wrap_untrusted_content("\n".join(lines), source=f"GitHub Issues: {repo}"))

                # -------------------------------------------------------------
                # 5. GET ISSUE (get_issue)
                # -------------------------------------------------------------
                elif raw_action == "get_issue":
                    num = arguments.get("issue_number")
                    if not num:
                        return ToolResult(content="Issue number is required for get_issue.", is_error=True)
                    url = f"{self.base_url}/repos/{repo}/issues/{num}"
                    res = await client.get(url, headers=headers)
                    if res.status_code != 200:
                        return ToolResult(content=f"GitHub API Error: {res.status_code} - {res.text}", is_error=True)
                    issue = res.json()
                    detail = (
                        f"Issue #{issue['number']}: {issue['title']}\n"
                        f"State: {issue['state']}\n"
                        f"Author: {issue['user']['login']}\n\n"
                        f"Body:\n{issue.get('body', '')}"
                    )
                    return ToolResult(content=wrap_untrusted_content(detail, source=f"GitHub Issue #{num}"))

                # -------------------------------------------------------------
                # 6. CREATE ISSUE (create_issue)
                # -------------------------------------------------------------
                elif raw_action == "create_issue":
                    if not self.allow_write:
                        return ToolResult(content="GitHub write operations are disabled in configuration.", is_error=True)
                    if not self.token:
                        return ToolResult(content="GitHub token is required to create issues.", is_error=True)

                    title = arguments.get("title", "").strip()
                    body = arguments.get("body", "").strip()
                    if not title:
                        return ToolResult(content="Issue title cannot be empty.", is_error=True)

                    url = f"{self.base_url}/repos/{repo}/issues"
                    res = await client.post(url, headers=headers, json={"title": title, "body": body})
                    if res.status_code not in (200, 201):
                        return ToolResult(content=f"Failed to create issue: {res.status_code} - {res.text}", is_error=True)
                    new_issue = res.json()
                    return ToolResult(content=f"Created issue #{new_issue['number']}: {new_issue['html_url']}")

                else:
                    return ToolResult(
                        content=(
                            f"Unknown GitHub action: '{raw_action}'. "
                            f"Supported actions: get_file, list_files, get_repo, list_issues, get_issue, create_issue."
                        ),
                        is_error=True
                    )
        except Exception as e:
            return ToolResult(content=f"GitHub operation failed: {str(e)}", is_error=True)
