from __future__ import annotations

import pytest

from northstar_api.llm_providers import PROVIDER_BY_ID, provider_catalog, validate_endpoint


def test_provider_catalog_includes_managed_and_local_options() -> None:
    providers = {item["id"] for item in provider_catalog()}
    assert {"nvidia", "openai", "anthropic", "google", "ollama", "openai-compatible"} <= providers
    assert PROVIDER_BY_ID["nvidia"].models
    assert PROVIDER_BY_ID["openai-compatible"].models == []


def test_local_endpoint_is_restricted_to_local_capable_providers() -> None:
    assert validate_endpoint("http://host.docker.internal:11434/v1", allow_local=True).endswith("/v1")
    with pytest.raises(ValueError):
        validate_endpoint("http://127.0.0.1:8000/v1", allow_local=False)


def test_endpoint_rejects_embedded_credentials_and_query_strings() -> None:
    with pytest.raises(ValueError):
        validate_endpoint("https://user:secret@example.com/v1", allow_local=False)
    with pytest.raises(ValueError):
        validate_endpoint("https://example.com/v1?key=secret", allow_local=False)
