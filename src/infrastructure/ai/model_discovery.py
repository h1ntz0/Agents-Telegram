"""Dynamic model discovery querying live provider APIs."""

import logging
from typing import List, Optional
import httpx
from src.domain.provider import PROVIDER_MODELS_CATALOG, ProviderType

logger = logging.getLogger(__name__)


async def fetch_available_models(
    provider_name: str,
    api_key: str = "",
    base_url: str = "",
    timeout: float = 10.0
) -> List[str]:
    """Fetch live available model list from provider API using provided credentials."""
    p_name = (provider_name or "").lower().strip()
    discovered_models: List[str] = []

    # 1. Ollama Tag Listing
    if p_name == ProviderType.OLLAMA.value:
        url = (base_url or "http://localhost:11434").rstrip("/") + "/api/tags"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(url)
                if res.status_code == 200:
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
        if base_url:
            target_url = base_url.rstrip("/") + "/models"
        elif p_name == ProviderType.DEEPSEEK.value:
            target_url = "https://api.deepseek.com/v1/models"
        elif p_name in (ProviderType.OPENCODE_ZEN.value, "opencode", "zen"):
            target_url = "https://api.opencode.ai/v1/models"
        elif p_name in (ProviderType.OPENCODE_GO.value, "go"):
            target_url = "https://go.opencode.ai/v1/models"
        elif p_name == ProviderType.OPENROUTER.value:
            target_url = "https://openrouter.ai/api/v1/models"
        else:
            target_url = "https://api.openai.com/v1/models"

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(target_url, headers=headers)
                if res.status_code == 200:
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

    return unique_models
