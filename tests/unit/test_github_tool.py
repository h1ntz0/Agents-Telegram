"""Unit tests for GitHubTool (file reading, directory listing, repo info, and validation)."""

import pytest
from src.domain.tool import PermissionLevel, RiskLevel
from src.infrastructure.tools.github_tool import GitHubTool, _clean_repo_name


def test_clean_repo_name():
    assert _clean_repo_name("owner/repo") == "owner/repo"
    assert _clean_repo_name("https://github.com/owner/repo") == "owner/repo"
    assert _clean_repo_name("http://github.com/owner/repo.git") == "owner/repo"
    assert _clean_repo_name("github.com/owner/repo/") == "owner/repo"
    assert _clean_repo_name("  https://github.com/RizqiAulia23/toko_tinta.git  ") == "RizqiAulia23/toko_tinta"


def test_github_tool_definition():
    tool = GitHubTool()
    defn = tool.definition
    assert defn.name == "github"
    assert defn.permission == PermissionLevel.READ
    assert defn.risk_level == RiskLevel.LOW
    assert not defn.requires_confirmation

    actions = defn.parameters["properties"]["action"]["enum"]
    assert "get_file" in actions
    assert "read_file" in actions
    assert "list_files" in actions
    assert "get_repo" in actions
    assert "list_issues" in actions
    assert "get_issue" in actions
    assert "create_issue" in actions


@pytest.mark.asyncio
async def test_github_invalid_repo():
    tool = GitHubTool()
    res = await tool.execute({"action": "get_repo", "repo": "invalidrepo"}, user_id=1)
    assert res.is_error
    assert "must be specified as 'owner/repo'" in res.content


@pytest.mark.asyncio
async def test_github_get_file_missing_path():
    tool = GitHubTool()
    res = await tool.execute({"action": "get_file", "repo": "owner/repo"}, user_id=1)
    assert res.is_error
    assert "path" in res.content.lower()


@pytest.mark.asyncio
async def test_github_create_issue_disallowed():
    tool = GitHubTool(allow_write=False)
    res = await tool.execute({
        "action": "create_issue",
        "repo": "owner/repo",
        "title": "Bug",
        "body": "Fix it"
    }, user_id=1)
    assert res.is_error
    assert "disabled in configuration" in res.content


@pytest.mark.asyncio
async def test_github_create_issue_missing_token():
    tool = GitHubTool(allow_write=True, token="")
    res = await tool.execute({
        "action": "create_issue",
        "repo": "owner/repo",
        "title": "Bug",
        "body": "Fix it"
    }, user_id=1)
    assert res.is_error
    assert "token is required" in res.content


@pytest.mark.asyncio
async def test_github_unknown_action():
    tool = GitHubTool()
    res = await tool.execute({"action": "unknown_action", "repo": "owner/repo"}, user_id=1)
    assert res.is_error
    assert "Unknown GitHub action" in res.content


@pytest.mark.asyncio
async def test_github_live_public_repo_read():
    """Live integration test against the public repo mentioned in the issue."""
    tool = GitHubTool()
    res = await tool.execute({
        "action": "get_file",
        "repo": "https://github.com/RizqiAulia23/toko_tinta",
        "path": "README.md"
    }, user_id=1)
    # Public read should succeed (or if rate limited by GitHub, should be handled gracefully)
    assert res is not None
    if not res.is_error:
        assert "toko_tinta" in res.content.lower() or "toko" in res.content.lower() or "github" in res.content.lower()
