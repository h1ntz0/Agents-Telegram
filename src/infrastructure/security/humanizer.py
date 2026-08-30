"""Humanizer: Universal Anti-AI Trope and Robotic Fluff Elimination Engine."""

import re
from typing import List

# Blacklisted robotic opening phrases
BANNED_INTRO_PATTERNS = [
    re.compile(r"^(certainly|sure thing|absolutely|of course|as an ai|i would be happy to|here is a breakdown of|here is the|here is a|here are the|let\'s delve into|let\'s dive into)[\s,:!-]*", re.IGNORECASE),
    re.compile(r"^(tentu saja|baiklah|sebagai ai|mari kita telusuri|mari kita selami|berikut ini adalah|berikut adalah)[\s,:!-]*", re.IGNORECASE),
]

# Blacklisted unprompted summary headers
BANNED_SUMMARY_HEADERS = [
    re.compile(r"\n+(#+\s*(Conclusion|Summary|Overall|In Conclusion|Wrap-up|Secara Keseluruhan|Kesimpulan)[\s\S]*$)", re.IGNORECASE),
]

# Blacklisted AI buzzwords and their clean replacements
BUZZWORD_REPLACEMENTS = [
    (re.compile(r"\bdelve\s+into\b", re.IGNORECASE), "investigate"),
    (re.compile(r"\bdelves\s+into\b", re.IGNORECASE), "investigates"),
    (re.compile(r"\bdelve\b", re.IGNORECASE), "explore"),
    (re.compile(r"\bstands\s+as\s+a\s+testament\s+to\b", re.IGNORECASE), "shows"),
    (re.compile(r"\brich\s+tapestry\b", re.IGNORECASE), "history"),
    (re.compile(r"\btapestry\b", re.IGNORECASE), "collection"),
    (re.compile(r"\bpivotal\s+role\b", re.IGNORECASE), "key role"),
    (re.compile(r"\bpivotal\b", re.IGNORECASE), "critical"),
    (re.compile(r"\bgame-changer\b", re.IGNORECASE), "major improvement"),
    (re.compile(r"\bseamlessly\b", re.IGNORECASE), "directly"),
    (re.compile(r"\bseamless\b", re.IGNORECASE), "direct"),
    (re.compile(r"\bmercusuar\b", re.IGNORECASE), "contoh"),
    (re.compile(r"\bbukti\s+nyata\b", re.IGNORECASE), "bukti"),
    (re.compile(r"\bmenyelami\b", re.IGNORECASE), "mempelajari"),
    (re.compile(r"\brajutan\s+kaya\b", re.IGNORECASE), "rangkaian"),
]


def humanize_response(text: str) -> str:
    """Strip robotic AI prefixes, fluff buzzwords, and unprompted conclusion sections."""
    if not text:
        return ""

    cleaned = text.strip()

    # 1. Strip all chained robotic greeting preambles
    changed = True
    while changed:
        changed = False
        for pattern in BANNED_INTRO_PATTERNS:
            new_cleaned = pattern.sub("", cleaned).strip()
            if new_cleaned != cleaned:
                cleaned = new_cleaned
                changed = True

    # 2. Strip unprompted closing conclusions
    for pattern in BANNED_SUMMARY_HEADERS:
        cleaned = pattern.sub("", cleaned).strip()

    # 3. Replace high-frequency AI slop words
    for pattern, replacement in BUZZWORD_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)

    return cleaned
