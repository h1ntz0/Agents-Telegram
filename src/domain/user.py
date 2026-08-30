"""Domain entities for User, Authorization, and Rate Limiting."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Set, Union


@dataclass
class TelegramUser:
    id: int
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    is_bot: bool = False


@dataclass
class AuthPolicy:
    allowlist_enabled: bool = True
    allowed_user_ids: Set[int] = field(default_factory=set)
    admin_user_ids: Set[int] = field(default_factory=set)
    enable_private_chat: bool = True
    enable_group_chat: bool = False

    def __init__(
        self,
        allowlist_enabled: bool = True,
        allowed_user_ids: Any = None,
        admin_user_ids: Any = None,
        enable_private_chat: bool = True,
        enable_group_chat: bool = False,
        allow_groups: bool = False,
    ):
        self.allowlist_enabled = allowlist_enabled
        self.allowed_user_ids = set(allowed_user_ids) if allowed_user_ids is not None else set()
        self.admin_user_ids = set(admin_user_ids) if admin_user_ids is not None else set()
        self.enable_private_chat = enable_private_chat
        self.enable_group_chat = enable_group_chat or allow_groups

    @property
    def allow_groups(self) -> bool:
        return self.enable_group_chat

    def is_authorized(self, user_id: int) -> bool:
        """Check if user has permission to interact with the bot."""
        if not self.allowlist_enabled:
            return True
        if not self.allowed_user_ids:
            return False
        return user_id in self.allowed_user_ids or user_id in self.admin_user_ids

    def is_admin(self, user_id: int) -> bool:
        """Check if user has administrator privileges."""
        return user_id in self.admin_user_ids


@dataclass
class RateLimitState:
    user_id: int
    request_timestamps: List[float] = field(default_factory=list)
