"""Domain entities for User, Authorization, and Rate Limiting."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Set


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
