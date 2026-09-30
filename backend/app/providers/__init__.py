"""Provider adapter registry."""

from __future__ import annotations

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
    "QuotaInfo", "Usage", "classify_error", "build_adapter", "AdapterUnavailable",
]


class AdapterUnavailable(RuntimeError):
    """The catalog lists this provider but its adapter is not implemented yet."""


def build_adapter(entry: dict, *, secret: str | None = None, endpoint: str | None = None, model: str | None = None, transport: httpx.BaseTransport | None = None) -> ProviderAdapter:
    adapter = entry.get("adapter")
    if entry.get("adapter_status") == "planned":
        raise AdapterUnavailable(f"{entry['id']} adapter is planned")
    model = model or entry.get("default_model")
    if adapter == "gemini":
        return GeminiAdapter(base_url=entry["base_url"], secret=secret, model=model, transport=transport)
    if adapter == "cloudflare":
        return CloudflareAdapter(base_url=entry["base_url"], account_id=endpoint, secret=secret, model=model, transport=transport)
    if adapter == "openai_compatible":
        base_url = endpoint or entry.get("base_url")
        if not base_url:
            raise ValueError("endpoint is required for " + entry["id"])
        cls = OpenRouterAdapter if entry["id"] == "openrouter" else OpenAICompatibleAdapter
        return cls(base_url=base_url, secret=secret, model=model, transport=transport)
    raise AdapterUnavailable(f"no adapter for {adapter}")
