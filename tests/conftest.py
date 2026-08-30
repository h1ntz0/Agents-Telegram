"""Shared pytest fixtures and test doubles."""

import os
import pytest
from typing import Any, Dict, List
from src.application.config_manager import RootConfig
from src.domain.agent import Message, Role
from src.domain.provider import AIProvider, CompletionRequest, CompletionResponse, ProviderType, TokenUsage
from src.infrastructure.database.sqlite_db import SqliteDatabase


class MockAIProvider(AIProvider):
    """Predictable mock AI provider for unit and integration testing."""

    def __init__(self, fixed_response: str = "Test response", tool_calls: List[Any] = None):
        self._fixed_response = fixed_response
        self._tool_calls = tool_calls or []
        self.request_history: List[CompletionRequest] = []

    @property
    def recorded_requests(self) -> List[CompletionRequest]:
        return self.request_history

    @property
    def provider_type(self) -> ProviderType:

        return ProviderType.OPENAI

    async def validate_credentials(self) -> bool:
        return True

    async def generate_response(self, request: CompletionRequest) -> CompletionResponse:
        self.request_history.append(request)
        return CompletionResponse(
            content=self._fixed_response,
            tool_calls=self._tool_calls,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )


@pytest.fixture
async def temp_db(tmp_path):
    """Provide clean isolated SQLite database."""
    db_file = str(tmp_path / "test_agent.db")
    db = SqliteDatabase(database_path=db_file)
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def mock_config(tmp_path):
    """Provide a standard test configuration."""
    cfg = RootConfig()
    cfg.storage.database_path = str(tmp_path / "test.db")
    cfg.telegram.bot_token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz12345"
    cfg.telegram.allowed_users = [111, 222]
    cfg.telegram.admin_users = [111]
    cfg.ai.provider = "openai"
    cfg.ai.api_key = "sk-mock-key-1234567890"
    cfg.ai.model = "gpt-4o"
    return cfg
