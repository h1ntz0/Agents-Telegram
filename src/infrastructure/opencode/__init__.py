"""OpenCode session bridge: remote-control a local OpenCode server over HTTP."""

from src.infrastructure.opencode.bridge import OpenCodeBridge, OpenCodeError

__all__ = ["OpenCodeBridge", "OpenCodeError"]
