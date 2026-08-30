"""Telegram user authorization rules and policy verification."""

from src.domain.user import AuthPolicy


class TelegramAuthManager:
    """Evaluates whether incoming Telegram messages originate from authorized users."""

    def __init__(self, policy: AuthPolicy):
        self.policy = policy

    def check_authorization(self, user_id: int, is_group: bool = False) -> bool:
        """Validate if user and chat type meet authorization policy."""
        if is_group and not self.policy.enable_group_chat:
            return False
        if not is_group and not self.policy.enable_private_chat:
            return False
        return self.policy.is_authorized(user_id)

    def is_admin(self, user_id: int) -> bool:
        """Check if user has administrative rights."""
        return self.policy.is_admin(user_id)
