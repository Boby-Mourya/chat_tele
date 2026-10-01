"""Provider catalog and safe runtime helpers for agent model connections.

The catalog is deliberately data-only. Provider credentials never enter an agent
profile or API response; they are encrypted in ``llm_connections`` and resolved
only inside the request that calls the selected model.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderId = Literal["nvidia", "openai", "anthropic", "google", "ollama", "openai-compatible"]


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    provider: ProviderId
    context_window: int = Field(alias="contextWindow")
    supports_reasoning: bool = Field(default=False, alias="supportsReasoning")


class ProviderDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ProviderId
    name: str
    description: str
    protocol: Literal["openai-compatible", "anthropic-messages", "gemini"]
    default_base_url: str = Field(alias="defaultBaseUrl")
    requires_api_key: bool = Field(alias="requiresApiKey")
    supports_local_url: bool = Field(alias="supportsLocalUrl")
    models: list[ProviderModel]


def _models(provider: ProviderId, values: list[tuple[str, str, str, int, bool]]) -> list[ProviderModel]:
    return [
        ProviderModel(
            id=model_id,
            name=name,
            description=description,
            provider=provider,
            contextWindow=context,
            supportsReasoning=reasoning,
        )
        for model_id, name, description, context, reasoning in values
    ]


PROVIDER_CATALOG: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        id="nvidia",
        name="NVIDIA AI Endpoints",
        description="NVIDIA-hosted Nemotron, Llama, Mistral, Qwen, DeepSeek, and Gemma models.",
        protocol="openai-compatible",
        defaultBaseUrl="https://integrate.api.nvidia.com/v1",
        requiresApiKey=True,
        supportsLocalUrl=False,
        models=_models(
            "nvidia",
            [
                ("nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra 550B", "Frontier reasoning and generation", 262144, True),
                ("nvidia/nemotron-3-super-120b-a12b", "Nemotron 3 Super 120B", "High quality general assistant", 131072, True),
                ("nvidia/nemotron-3-nano-30b-a3b", "Nemotron 3 Nano 30B", "Fast reasoning and chat", 131072, True),
                ("meta/llama-3.3-70b-instruct", "Llama 3.3 70B Instruct", "General instruction following", 131072, False),
                ("meta/llama-3.1-405b-instruct", "Llama 3.1 405B Instruct", "Large-context general assistant", 131072, False),
                ("meta/llama-3.1-70b-instruct", "Llama 3.1 70B Instruct", "Balanced general assistant", 131072, False),
                ("mistralai/mistral-large-2-instruct", "Mistral Large 2", "Multilingual instruction following", 131072, False),
                ("qwen/qwen2.5-72b-instruct", "Qwen 2.5 72B", "Multilingual and coding", 131072, False),
                ("deepseek-ai/deepseek-r1", "DeepSeek R1", "Open reasoning model", 163840, True),
                ("google/gemma-3-27b-it", "Gemma 3 27B", "Open multimodal-capable assistant", 131072, False),
            ],
        ),
    ),
    ProviderDefinition(
        id="openai",
        name="OpenAI",
        description="OpenAI Chat Completions models using your own API key.",
        protocol="openai-compatible",
        defaultBaseUrl="https://api.openai.com/v1",
        requiresApiKey=True,
        supportsLocalUrl=False,
        models=_models(
            "openai",
            [
                ("gpt-4.1", "GPT-4.1", "High-quality general reasoning", 1047576, False),
                ("gpt-4.1-mini", "GPT-4.1 mini", "Fast, cost-efficient reasoning", 1047576, False),
                ("gpt-4o", "GPT-4o", "Multimodal general assistant", 128000, False),
                ("gpt-4o-mini", "GPT-4o mini", "Fast general assistant", 128000, False),
                ("o3", "o3", "Deep reasoning", 200000, True),
                ("o4-mini", "o4-mini", "Fast reasoning", 200000, True),
            ],
        ),
    ),
    ProviderDefinition(
        id="anthropic",
        name="Anthropic Claude",
        description="Claude Messages API with Sonnet, Opus, and Haiku models.",
        protocol="anthropic-messages",
        defaultBaseUrl="https://api.anthropic.com",
        requiresApiKey=True,
        supportsLocalUrl=False,
        models=_models(
            "anthropic",
            [
                ("claude-opus-4-1", "Claude Opus 4.1", "Highest-capability Claude", 200000, True),
                ("claude-sonnet-4", "Claude Sonnet 4", "Balanced quality and speed", 200000, True),
                ("claude-3-7-sonnet-latest", "Claude 3.7 Sonnet", "Reasoning and coding", 200000, True),
                ("claude-3-5-haiku-latest", "Claude 3.5 Haiku", "Fast and affordable", 200000, False),
            ],
        ),
    ),
    ProviderDefinition(
        id="google",
        name="Google Gemini",
        description="Gemini generateContent models using a Google AI Studio API key.",
        protocol="gemini",
        defaultBaseUrl="https://generativelanguage.googleapis.com/v1beta",
        requiresApiKey=True,
        supportsLocalUrl=False,
        models=_models(
            "google",
            [
                ("gemini-2.5-pro", "Gemini 2.5 Pro", "Advanced reasoning", 1048576, True),
                ("gemini-2.5-flash", "Gemini 2.5 Flash", "Fast general assistant", 1048576, True),
                ("gemini-2.0-flash", "Gemini 2.0 Flash", "Fast multimodal assistant", 1048576, False),
            ],
        ),
    ),
    ProviderDefinition(
        id="ollama",
        name="Ollama / local server",
        description="A local Ollama model reachable from the API server.",
        protocol="openai-compatible",
        defaultBaseUrl="http://127.0.0.1:11434/v1",
        requiresApiKey=False,
        supportsLocalUrl=True,
        models=_models(
            "ollama",
            [
                ("llama3.3", "Llama 3.3", "Local general assistant", 131072, False),
                ("qwen2.5", "Qwen 2.5", "Local multilingual and coding", 131072, False),
                ("deepseek-r1", "DeepSeek R1", "Local reasoning model", 131072, True),
                ("mistral", "Mistral", "Local fast assistant", 32768, False),
            ],
        ),
    ),
    ProviderDefinition(
        id="openai-compatible",
        name="Custom OpenAI-compatible API",
        description="Any server exposing /chat/completions, including vLLM, LM Studio, and hosted gateways.",
        protocol="openai-compatible",
        defaultBaseUrl="http://127.0.0.1:8000/v1",
        requiresApiKey=False,
        supportsLocalUrl=True,
        models=[],
    ),
)

PROVIDER_BY_ID = {item.id: item for item in PROVIDER_CATALOG}


def provider_catalog() -> list[dict[str, Any]]:
    return [item.model_dump(by_alias=True) for item in PROVIDER_CATALOG]


def validate_endpoint(value: str, *, allow_local: bool) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Endpoint cannot contain credentials, a query string, or a fragment")
    if not allow_local and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("This provider does not permit a local endpoint")
    return normalized
