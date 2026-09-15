"""Structured JSON logging with automated secret masking."""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict

SECRET_PATTERNS = [
    # Telegram Bot Token (e.g., 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ).
    # No \b anchor: Telegram API URLs glue the token straight onto "/bot", and
    # both characters either side of that seam are word characters, so a word
    # boundary never exists where the token starts. A \b there meant
    # "GET https://api.telegram.org/bot<id>:<secret>/getMe" -- the exact shape
    # httpx logs at INFO -- was written to stdout and log files unmasked.
    re.compile(r"(?<!\d)\d{8,12}:[A-Za-z0-9_-]{30,45}"),
    # OpenAI API Key
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    # Anthropic API Key
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    # Google Gemini API Key
    re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b"),
    # GitHub Personal Access Token
    re.compile(r"\bghp_[0-9a-zA-Z]{36}\b"),
    re.compile(r"\bgithub_pat_[0-9a-zA-Z_]{60,}\b"),
    # Bearer tokens
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
]


def mask_secrets(text: str) -> str:
    """Replace credentials with masked placeholders."""
    if not text:
        return ""
    result = str(text)
    for pattern in SECRET_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    return result


class SecretMaskingJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON with masked secrets."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": mask_secrets(record.getMessage()),
        }
        if record.exc_info:
            log_payload["exception"] = mask_secrets(self.formatException(record.exc_info))
        return json.dumps(log_payload)


def configure_logging(level_name: str = "INFO") -> logging.Logger:
    """Configure root logger with JSON secret-masking handler."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))

    # Remove existing handlers
    while root_logger.handlers:
        root_logger.handlers.pop()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SecretMaskingJsonFormatter())
    root_logger.addHandler(handler)

    return root_logger
