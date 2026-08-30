"""GitHub integration tool for inspecting repositories, issues, and pull requests."""

from typing import Any, Dict, Optional
import httpx
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult
from src.infrastructure.security.prompt_guard import wrap_untrusted_content


class GitHubTool(BaseTool):
    """GitHub API client for repository and issue exploration."""

    def __init__(self, token: str = "", default_repo: str = "", allow_write: bool = False, timeout: float = 20.0):
        self.token = token
        self.default_repo = default_repo
        self.allow_write = allow_write
        self.timeout = timeout
        self.base_url = "https://api.github.com"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="github",
            description="Access GitHub API to view repository details, read issues, or inspect pull requests.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get_repo", "list_issues", "get_issue", "create_issue"],
                        "description": "GitHub action to perform."
                    },
                    "repo": {
                        "type": "string",
                        "description": "Target repository formatted as 'owner/repo'. Defaults to configured repo."
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
        action = arguments.get("action", "")
        repo = arguments.get("repo") or self.default_repo

        if not repo or "/" not in repo:
            return ToolResult(content="Repository name must be specified as 'owner/repo'.", is_error=True)

        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if action == "get_repo":
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

                elif action == "list_issues":
                    url = f"{self.base_url}/repos/{repo}/issues?state=open&per_page=10"
                    res = await client.get(url, headers=headers)
                    if res.status_code != 200:
                        return ToolResult(content=f"GitHub API Error: {res.status_code} - {res.text}", is_error=True)
                    issues = res.json()
                    if not issues:
                        return ToolResult(content=f"No open issues found for {repo}.")
                    lines = [f"#{i['number']} - {i['title']} (by {i['user']['login']})" for i in issues]
                    return ToolResult(content=wrap_untrusted_content("\n".join(lines), source=f"GitHub Issues: {repo}"))

                elif action == "get_issue":
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

                elif action == "create_issue":
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
                    return ToolResult(content=f"Unknown GitHub action: {action}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"GitHub operation failed: {str(e)}", is_error=True)
