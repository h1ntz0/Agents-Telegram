"""Integration tests for SQLite persistence, multi-user isolation, and memory retention."""

import pytest
from src.domain.agent import Message, Role, ToolCall
from src.infrastructure.database.sqlite_db import SqliteDatabase


@pytest.mark.asyncio
async def test_session_isolation_and_persistence(temp_db):
    user_a = 101
    user_b = 202
    chat_id = 999

    session_a = await temp_db.get_or_create_session(user_a, chat_id)
    session_b = await temp_db.get_or_create_session(user_b, chat_id)

    assert session_a.session_id != session_b.session_id

    # Add message for User A
    msg_a = Message(role=Role.USER, content="Hello from User A")
    await temp_db.save_message(session_a.session_id, user_a, msg_a)

    # Reload session for User A and User B
    reloaded_a = await temp_db.get_or_create_session(user_a, chat_id)
    reloaded_b = await temp_db.get_or_create_session(user_b, chat_id)

    assert len(reloaded_a.messages) == 1
    assert reloaded_a.messages[0].content == "Hello from User A"
    assert len(reloaded_b.messages) == 0


@pytest.mark.asyncio
async def test_agent_memory_kv(temp_db):
    user_id = 555
    await temp_db.set_memory(user_id, "favorite_color", "blue")
    await temp_db.set_memory(user_id, "timezone", "UTC")

    memories = await temp_db.get_memories(user_id)
    assert memories == {"favorite_color": "blue", "timezone": "UTC"}

    # Update existing key
    await temp_db.set_memory(user_id, "favorite_color", "green")
    updated_memories = await temp_db.get_memories(user_id)
    assert updated_memories["favorite_color"] == "green"
