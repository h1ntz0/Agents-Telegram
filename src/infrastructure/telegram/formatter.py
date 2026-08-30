import html
import re
from typing import List


def render_progress_bar(percentage: int, width: int = 10) -> str:
    """Render a clean text-based progress bar."""
    clamped = max(0, min(100, percentage))
    filled_len = int(width * clamped / 100)
    empty_len = width - filled_len
    bar = "█" * filled_len + "░" * empty_len
    return f"[{bar}] {clamped}%"


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard LLM Markdown into valid Telegram HTML format.

    Replaces raw markdown symbols (**bold**, _italic_, ---, ```code```) with
    clean native Telegram HTML tags (<b>, <i>, <code>, <pre>) and clean dividers.
    """
    if not text:
        return ""

    # 1. Protect fenced code blocks: ```lang\ncode\n```
    code_blocks = []

    def _save_code_block(match: re.Match) -> str:
        lang = (match.group(1) or "").strip()
        code = match.group(2)
        idx = len(code_blocks)
        code_blocks.append((lang, code))
        return f"TOKENCODEBLOCK{idx}XYZ"

    text = re.sub(r"```(\w*)\n?(.*?)```", _save_code_block, text, flags=re.DOTALL)

    # 2. Protect inline code: `code`
    inline_codes = []

    def _save_inline_code(match: re.Match) -> str:
        idx = len(inline_codes)
        inline_codes.append(match.group(1))
        return f"TOKENINLINECODE{idx}XYZ"

    text = re.sub(r"`([^`\n]+)`", _save_inline_code, text)

    # 3. Escape HTML special characters for safe regular text
    text = html.escape(text)

    # 4. Headers: # Header -> <b>Header</b>
    text = re.sub(r"^[ \t]*#{1,6}[ \t]+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 5. Horizontal rules: --- or *** or ___ -> clean divider
    text = re.sub(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", "──────────────", text, flags=re.MULTILINE)

    # 6. Bullet lists: - item, * item, + item -> • item
    text = re.sub(r"^[ \t]*[-*+][ \t]+(.+)$", r"• \1", text, flags=re.MULTILINE)

    # 7. Bold: **text** or __text__ -> <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)

    # 8. Italic: *text* or _text_ -> <i>text</i>
    text = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # 9. Strikethrough: ~~text~~ -> <s>text</s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.DOTALL)

    # 10. Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r'<a href="\2">\1</a>', text)

    # 11. Restore inline code
    for idx, code in enumerate(inline_codes):
        escaped_code = html.escape(code)
        text = text.replace(f"TOKENINLINECODE{idx}XYZ", f"<code>{escaped_code}</code>")

    # 12. Restore code blocks
    for idx, (lang, code) in enumerate(code_blocks):
        escaped_code = html.escape(code.strip())
        if lang:
            tag = f'<pre><code class="language-{html.escape(lang)}">{escaped_code}</code></pre>'
        else:
            tag = f"<pre><code>{escaped_code}</code></pre>"
        text = text.replace(f"TOKENCODEBLOCK{idx}XYZ", tag)

    return text


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
