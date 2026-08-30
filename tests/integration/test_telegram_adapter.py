"""Integration tests for Telegram formatter and message chunking."""

from src.infrastructure.telegram.formatter import render_progress_bar, split_message_chunks


def test_progress_bar_rendering():
    assert render_progress_bar(0) == "[░░░░░░░░░░] 0%"
    assert render_progress_bar(50) == "[█████░░░░░] 50%"
    assert render_progress_bar(100) == "[██████████] 100%"


def test_split_message_chunks_under_limit():
    short_text = "Hello world"
    chunks = split_message_chunks(short_text, max_chunk_size=100)
    assert chunks == ["Hello world"]


def test_split_message_chunks_over_limit():
    long_text = "\n".join([f"Line number {i} with some content" for i in range(100)])
    chunks = split_message_chunks(long_text, max_chunk_size=200)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 250  # Allows line padding bounds
