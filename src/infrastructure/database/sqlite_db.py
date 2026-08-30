"""SQLite asynchronous database layer for session, conversation history, and memory persistence."""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import aiosqlite
from src.domain.agent import AgentState, Message, Role, Session, ToolCall, ToolResponse


class SqliteDatabase:
    """Async SQLite database manager with automatic schema migration and multi-user isolation."""

    def __init__(self, database_path: str = "data/agent.db"):
        self.db_path = database_path
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Establish database connection and run schema migrations."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._run_migrations()

    async def close(self) -> None:
        """Close active database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _run_migrations(self) -> None:
        """Create tables if they do not exist."""
        assert self._db is not None
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'idle',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls_json TEXT,
                tool_responses_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                memory_key TEXT NOT NULL,
                memory_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, memory_key)
            );
        """)

        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON agent_memory(user_id);")
        await self._db.commit()

    async def get_or_create_session(self, user_id: int, chat_id: int) -> Session:
        """Retrieve existing active session or initialize a fresh one."""
        assert self._db is not None
        session_id = f"user_{user_id}_chat_{chat_id}"
        cursor = await self._db.execute(
            "SELECT session_id, user_id, chat_id, state, created_at, updated_at FROM sessions WHERE session_id = ?",
            (session_id,)
        )
        row = await cursor.fetchone()

        now_iso = datetime.now(timezone.utc).isoformat()
        if not row:
            await self._db.execute(
                "INSERT INTO sessions (session_id, user_id, chat_id, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, user_id, chat_id, AgentState.IDLE.value, now_iso, now_iso)
            )
            await self._db.commit()
            return Session(session_id=session_id, user_id=user_id, chat_id=chat_id)

        # Load message history
        msg_cursor = await self._db.execute(
            "SELECT role, content, tool_calls_json, tool_responses_json, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        )
        msg_rows = await msg_cursor.fetchall()
        messages: List[Message] = []
        for mr in msg_rows:
            tool_calls = []
            if mr["tool_calls_json"]:
                raw_tc = json.loads(mr["tool_calls_json"])
                tool_calls = [ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"]) for tc in raw_tc]

            tool_responses = []
            if mr["tool_responses_json"]:
                raw_tr = json.loads(mr["tool_responses_json"])
                tool_responses = [ToolResponse(tool_call_id=tr["tool_call_id"], name=tr["name"], content=tr["content"], is_error=tr.get("is_error", False)) for tr in raw_tr]

            messages.append(Message(
                role=Role(mr["role"]),
                content=mr["content"],
                tool_calls=tool_calls,
                tool_responses=tool_responses,
                timestamp=datetime.fromisoformat(mr["created_at"])
            ))

        return Session(
            session_id=session_id,
            user_id=user_id,
            chat_id=chat_id,
            state=AgentState(row["state"]),
            messages=messages,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )

    async def save_message(self, session_id: str, user_id: int, message: Message) -> None:
        """Persist a message into session history."""
        assert self._db is not None
        tc_json = json.dumps([{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in message.tool_calls]) if message.tool_calls else None
        tr_json = json.dumps([{"tool_call_id": tr.tool_call_id, "name": tr.name, "content": tr.content, "is_error": tr.is_error} for tr in message.tool_responses]) if message.tool_responses else None

        now_iso = message.timestamp.isoformat()
        await self._db.execute(
            "INSERT INTO messages (session_id, user_id, role, content, tool_calls_json, tool_responses_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, user_id, message.role.value, message.content, tc_json, tr_json, now_iso)
        )
        await self._db.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (now_iso, session_id)
        )
        await self._db.commit()

    async def clear_session(self, session_id: str) -> None:
        """Purge message history for a given session."""
        assert self._db is not None
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE sessions SET state = 'idle', updated_at = ? WHERE session_id = ?",
            (now_iso, session_id)
        )
        await self._db.commit()

    async def set_memory(self, user_id: int, key: str, value: str) -> None:
        """Store or update user memory entry."""
        assert self._db is not None
        now_iso = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO agent_memory (user_id, memory_key, memory_value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, memory_key) DO UPDATE SET
                memory_value = excluded.memory_value,
                updated_at = excluded.updated_at
            """,
            (user_id, key.strip(), value.strip(), now_iso, now_iso)
        )
        await self._db.commit()

    async def get_memories(self, user_id: int) -> Dict[str, str]:
        """Fetch all stored memories for a user."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT memory_key, memory_value FROM agent_memory WHERE user_id = ?",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return {r["memory_key"]: r["memory_value"] for r in rows}

    async def purge_expired_memories(self, retention_days: int) -> int:
        """Delete memories older than retention_days. If retention_days <= 0, no retention purge."""
        if retention_days <= 0 or not self._db:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        cursor = await self._db.execute("DELETE FROM agent_memory WHERE updated_at < ?", (cutoff,))
        await self._db.commit()
        return cursor.rowcount
