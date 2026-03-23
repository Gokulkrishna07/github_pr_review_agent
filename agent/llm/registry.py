"""Provider registry — maps provider names to modules and model catalogs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import gemini_provider, groq_provider, perplexity_provider

if TYPE_CHECKING:
    from types import ModuleType


@dataclass
class ProviderConfig:
    name: str
    display_name: str
    models: list[str] = field(default_factory=list)
    default_model: str = ""
    api_key_setting: str = ""
    module: ModuleType | None = None


PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        name="groq",
        display_name="Groq",
        models=[
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "mixtral-8x7b-32768",
        ],
        default_model="llama-3.3-70b-versatile",
        api_key_setting="groq_api_key",
        module=groq_provider,
    ),
    "gemini": ProviderConfig(
        name="gemini",
        display_name="Gemini",
        models=[
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-pro",
        ],
        default_model="gemini-2.0-flash",
        api_key_setting="gemini_api_key",
        module=gemini_provider,
    ),
    "perplexity": ProviderConfig(
        name="perplexity",
        display_name="Perplexity",
        models=[
            "sonar",
            "sonar-pro",
            "sonar-reasoning",
        ],
        default_model="sonar-pro",
        api_key_setting="perplexity_api_key",
        module=perplexity_provider,
    ),
}


def get_available_providers(settings) -> list[dict]:
    """Return providers whose API key is configured."""
    result = []
    for name, cfg in PROVIDERS.items():
        api_key = getattr(settings, cfg.api_key_setting, "")
        if api_key:
            result.append({
                "name": cfg.name,
                "display_name": cfg.display_name,
                "models": cfg.models,
                "default_model": cfg.default_model,
            })
    return result


def get_provider_api_key(provider_name: str, settings) -> str:
    """Get the API key for a provider from settings."""
    cfg = PROVIDERS.get(provider_name)
    if not cfg:
        raise ValueError(f"Unknown provider: {provider_name}")
    key = getattr(settings, cfg.api_key_setting, "")
    if not key:
        raise ValueError(f"API key not configured for provider: {provider_name}")
    return key
