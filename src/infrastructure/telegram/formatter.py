"""Message formatting and chunking utilities for Telegram Bot API."""

from typing import List


def render_progress_bar(percentage: int, width: int = 10) -> str:
    """Render a clean text-based progress bar."""
    clamped = max(0, min(100, percentage))
    filled_len = int(width * clamped / 100)
    empty_len = width - filled_len
    bar = "█" * filled_len + "░" * empty_len
    return f"[{bar}] {clamped}%"


def split_message_chunks(text: str, max_chunk_size: int = 4000) -> List[str]:
    """Split long text into safe chunks under Telegram's 4096 character limit."""
    if not text:
        return []
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            if len(line) > max_chunk_size:
                # Break extraordinarily long single lines
                for i in range(0, len(line), max_chunk_size):
                    chunks.append(line[i:i + max_chunk_size])
            else:
                current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks
