"""Provider adapter registry."""

from __future__ import annotations

import re

import httpx

from .base import (
    ErrorInfo,
    ExecuteRequest,
    ExecuteResult,
    HealthResult,
    ProviderAdapter,
    ProviderError,
    QuotaInfo,
    Usage,
    classify_error,
)
from .gemini import GeminiAdapter
from .openai_compat import CloudflareAdapter, OpenAICompatibleAdapter, OpenRouterAdapter

__all__ = [
    "ErrorInfo", "ExecuteRequest", "ExecuteResult", "HealthResult", "ProviderAdapter", "ProviderError",
    "QuotaInfo", "Usage", "classify_error", "build_adapter", "AdapterUnavailable", "choose_model",
]


NON_CHAT = re.compile(r"(tts|whisper|orpheus|guard|embed|image|imagen|audio|transcrib|moderation|rerank|veo|lyria|live|robotics|computer-use)", re.I)


def choose_model(entry: dict, models: list[str], exclude: set[str] | None = None) -> str | None:
    """Picks a chat model the provider actually serves: catalog default, then preferred prefixes,
    then any listed model that is not speech/embedding/image/safety-only."""
    exclude = exclude or set()
    default = entry.get("default_model")
    # Some keys can spend money on any listed model (OpenRouter): only the catalog's free pattern is allowed.
    allowed = re.compile(entry["model_pattern"]) if entry.get("model_pattern") else None
    usable = [m for m in models if m not in exclude and (allowed is None or allowed.search(m))]
    if default and entry.get("default_alias") and default not in exclude:
        return default  # a routing alias the provider serves even though it is not in the model list
    if not usable:
        return None
    if default in usable and not NON_CHAT.search(default):
        return default
    for prefix in entry.get("preferred_models") or []:
        for m in usable:
            if m.startswith(prefix) and not NON_CHAT.search(m):
                return m
    return next((m for m in usable if not NON_CHAT.search(m)), usable[0])


class AdapterUnavailable(RuntimeError):
    """The catalog lists this provider but its adapter is not implemented yet."""


def build_adapter(entry: dict, *, secret: str | None = None, endpoint: str | None = None, model: str | None = None, transport: httpx.BaseTransport | None = None) -> ProviderAdapter:
    adapter = entry.get("adapter")
    if entry.get("adapter_status") == "planned":
        raise AdapterUnavailable(f"{entry['id']} adapter is planned")
    model = model or entry.get("default_model")
    # Local models on consumer GPUs can take minutes to write a whole game.
    timeout = 900 if "local" in entry.get("auth_types", []) else 120
    if adapter == "gemini":
        return GeminiAdapter(base_url=entry["base_url"], secret=secret, model=model, transport=transport, timeout=timeout)
    if adapter == "cloudflare":
        return CloudflareAdapter(base_url=entry["base_url"], account_id=endpoint, secret=secret, model=model, transport=transport, timeout=timeout)
    if adapter == "openai_compatible":
        base_url = endpoint or entry.get("base_url")
        if not base_url:
            raise ValueError("endpoint is required for " + entry["id"])
        cls = OpenRouterAdapter if entry["id"] == "openrouter" else OpenAICompatibleAdapter
        return cls(base_url=base_url, secret=secret, model=model, transport=transport, timeout=timeout)
    raise AdapterUnavailable(f"no adapter for {adapter}")
