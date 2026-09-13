"""S5: the JSON config schema must stay in sync with the provider factory."""

import json
import pathlib

from src.domain.provider import ProviderType


def test_config_schema_lists_every_supported_provider():
    """Every provider the factory accepts must appear in the schema enum."""
    schema = json.loads(
        pathlib.Path("config/schema/config.schema.json").read_text(encoding="utf-8")
    )
    enum = set(schema["properties"]["ai"]["properties"]["provider"]["enum"])
    expected = {p.value for p in ProviderType}
    assert expected.issubset(enum), f"schema is missing providers: {sorted(expected - enum)}"
