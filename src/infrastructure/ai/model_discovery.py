"""Dynamic model discovery querying live provider APIs."""

import logging
import re
import urllib.parse
from typing import List, Optional, Tuple
import httpx
from src.domain.provider import PROVIDER_MODELS_CATALOG, ProviderType

logger = logging.getLogger(__name__)


def normalize_base_url(value: str) -> Optional[str]:
    """Return a usable http(s) base URL, or None when the value cannot be one.

    Accepts full URLs (``http://host:port/v1``) and bare ``host:port/path`` forms,
    which are upgraded to ``http://``. Rejects credentials or junk that a user may
    paste into a URL prompt (e.g. an API key), instead of letting httpx fail later
    with a confusing "Request URL is missing a protocol" error.
    """
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip("/")
    if not cleaned:
        return None

    if "://" not in cleaned:
        host_part = cleaned.split("/")[0]
        host_only = host_part.split(":")[0]
        # A bare value is only plausible as a host when it is localhost, has a
        # dotted hostname, or carries an explicit port.
        if "." not in host_only and host_only.lower() != "localhost" and ":" not in host_part:
            return None
        cleaned = "http://" + cleaned

    try:
        parsed = urllib.parse.urlparse(cleaned)
    except ValueError:
        return None

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return cleaned


def base_url_lacks_api_path(value: str) -> bool:
    """True when a base URL has no path, which usually means a missing /v1 suffix."""
    normalized = normalize_base_url(value)
    if not normalized:
        return False
    try:
        return not urllib.parse.urlparse(normalized).path.strip("/")
    except ValueError:
        return False


async def fetch_available_models_ex(
    provider_name: str,
    api_key: str = "",
    base_url: str = "",
    timeout: float = 10.0
) -> Tuple[List[str], bool]:
    """Fetch live models and report whether a live provider response was obtained.

    Returns ``(models, live_ok)``. ``live_ok`` is False when the provider could not
    be reached and the returned list came from the offline fallback catalog, so the
    caller can tell the user the list may be stale instead of silently showing it.
    """
    p_name = (provider_name or "").lower().strip()
    discovered_models: List[str] = []
    live_ok = False

    # 1. Ollama Tag Listing
    if p_name == ProviderType.OLLAMA.value:
        url = normalize_base_url(base_url) or "http://localhost:11434"
        url = url.rstrip("/") + "/api/tags"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    live_ok = True
                    data = res.json()
                    for m in data.get("models", []):
                        if "name" in m:
                            discovered_models.append(m["name"])
        except Exception as e:
            logger.warning(f"Failed to fetch Ollama models: {str(e)}")

    # 2. Anthropic Models API
    elif p_name in (ProviderType.ANTHROPIC.value, "claude", "claude_code"):
        if api_key:
            url = "https://api.anthropic.com/v1/models"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        live_ok = True
                        data = res.json()
                        for m in data.get("data", []):
                            if "id" in m:
                                discovered_models.append(m["id"])
            except Exception as e:
                logger.warning(f"Failed to fetch Anthropic models: {str(e)}")

    # 3. Google Gemini Models API
    elif p_name == ProviderType.GOOGLE.value:
        if api_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.get(url)
                    if res.status_code == 200:
                        live_ok = True
                        data = res.json()
                        for m in data.get("models", []):
                            raw_name = m.get("name", "")
                            # Strip "models/" prefix (e.g., "models/gemini-2.0-flash" -> "gemini-2.0-flash")
                            clean_name = raw_name.replace("models/", "") if raw_name.startswith("models/") else raw_name
                            if "gemini" in clean_name and "embedding" not in clean_name:
                                discovered_models.append(clean_name)
            except Exception as e:
                logger.warning(f"Failed to fetch Gemini models: {str(e)}")

    # 4. Standard OpenAI-compatible /v1/models (9router, DeepSeek, OpenCode Zen, OpenCode Go, OpenAI, OpenRouter, Custom)
    else:
        target_url = ""
        normalized_base = normalize_base_url(base_url)
        if normalized_base:
            target_url = normalized_base + "/models"
        elif base_url:
            # A base_url was supplied but is not a usable URL (e.g. an API key was
            # pasted into the URL prompt). Fall back to the provider default rather
            # than issuing a malformed request.
            logger.warning(
                f"Ignoring invalid base_url for {p_name}: {base_url!r} "
                "(expected something like http://host:port/v1)"
            )
            target_url = _default_models_url(p_name)
        else:
            target_url = _default_models_url(p_name)

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(target_url, headers=headers)
                if res.status_code == 200:
                    live_ok = True
                    data = res.json()
                    # Parse standard {data: [{id: ...}]}
                    for item in data.get("data", []):
                        if isinstance(item, dict) and "id" in item:
                            discovered_models.append(item["id"])
                        elif isinstance(item, str):
                            discovered_models.append(item)
        except Exception as e:
            logger.warning(f"Failed to fetch models from {target_url}: {str(e)}")

    # Fallback to provider-specific catalog if live discovery returned no models
    if not discovered_models:
        discovered_models = PROVIDER_MODELS_CATALOG.get(p_name, [])

    # De-duplicate while preserving order
    seen = set()
    unique_models = []
    for m in discovered_models:
        if m and m not in seen:
            seen.add(m)
            unique_models.append(m)

    return unique_models, live_ok


def _default_models_url(p_name: str) -> str:
    """Return the built-in /models endpoint for a known OpenAI-compatible provider."""
    if p_name == ProviderType.DEEPSEEK.value:
        return "https://api.deepseek.com/v1/models"
    if p_name in (ProviderType.OPENCODE_ZEN.value, "opencode", "zen"):
        return "https://api.opencode.ai/v1/models"
    if p_name in (ProviderType.OPENCODE_GO.value, "go"):
        return "https://go.opencode.ai/v1/models"
    if p_name == ProviderType.OPENROUTER.value:
        return "https://openrouter.ai/api/v1/models"
    if p_name == ProviderType.NINE_ROUTER.value:
        return "http://localhost:20128/v1/models"
    return "https://api.openai.com/v1/models"


async def fetch_available_models(
    provider_name: str,
    api_key: str = "",
    base_url: str = "",
    timeout: float = 10.0
) -> List[str]:
    """Fetch live available model list from provider API using provided credentials."""
    models, _ = await fetch_available_models_ex(
        provider_name, api_key=api_key, base_url=base_url, timeout=timeout
    )
    return models
