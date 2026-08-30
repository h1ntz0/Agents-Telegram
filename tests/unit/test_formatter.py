"""Unit tests for Telegram HTML message formatting."""

from src.infrastructure.telegram.formatter import markdown_to_telegram_html, split_message_chunks, render_progress_bar


def test_markdown_to_telegram_html_bold_and_italic():
    raw = "Here is **bold text** and __another bold__ and *italic text* and _another italic_."
    formatted = markdown_to_telegram_html(raw)
    assert "<b>bold text</b>" in formatted
    assert "<b>another bold</b>" in formatted
    assert "<i>italic text</i>" in formatted
    assert "<i>another italic</i>" in formatted


def test_markdown_to_telegram_html_headers_and_dividers():
    raw = "# Main Title\n## Subtitle\n---\nContent here\n***\nMore content"
    formatted = markdown_to_telegram_html(raw)
    assert "<b>Main Title</b>" in formatted
    assert "<b>Subtitle</b>" in formatted
    assert "──────────────" in formatted
    assert "---" not in formatted


def test_markdown_to_telegram_html_lists():
    raw = "Frameworks:\n- React\n* Vue\n+ Svelte"
    formatted = markdown_to_telegram_html(raw)
    assert "• React" in formatted
    assert "• Vue" in formatted
    assert "• Svelte" in formatted


def test_markdown_to_telegram_html_code_blocks_and_escaping():
    raw = "Use `print('1 < 2 & 3 > 0')` in code:\n```python\ndef test():\n    return 1 < 2\n```"
    formatted = markdown_to_telegram_html(raw)
    assert "&lt; 2" in formatted
    assert '<pre><code class="language-python">' in formatted
    assert "def test():" in formatted
