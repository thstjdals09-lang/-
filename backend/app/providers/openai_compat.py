"""OpenAI-compatible chat adapter: Groq, Cerebras, OpenRouter, Mistral, GitHub Models,
Hugging Face router, Cloudflare Workers AI, llama.cpp, Ollama and custom endpoints."""

from __future__ import annotations

import base64

import httpx

from .base import ExecuteRequest, ExecuteResult, ProviderAdapter, QuotaInfo, Usage, parse_reset


class OpenAICompatibleAdapter(ProviderAdapter):
    adapter_id = "openai_compatible"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._secret:
            headers["Authorization"] = "Bearer " + self._secret
        return headers

    def list_models(self) -> list[str]:
        res = self._request("GET", self.base_url + "/models", headers=self._headers())
        self._capture_quota(res)
        data = self._json(res)
        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        return [m.get("id") or m.get("name") for m in items if isinstance(m, dict)]

    def execute(self, request: ExecuteRequest) -> ExecuteResult:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        if request.images:
            parts = [{"type": "text", "text": request.prompt}]
            parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(img).decode()}} for img in request.images]
            messages.append({"role": "user", "content": parts})
        else:
            messages.append({"role": "user", "content": request.prompt})
        model = request.model or self.model
        start = self._timer()
        res = self._request("POST", self.base_url + "/chat/completions", headers=self._headers(), json=self._body(model, messages, request))
        self._capture_quota(res)
        payload = self._json(res)
        choice = (payload.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or choice.get("text") or ""
        return ExecuteResult(text=text, model=payload.get("model", model or ""), usage=self.usage_parser(payload), latency_ms=self._elapsed_ms(start))

    def _body(self, model, messages, request: ExecuteRequest) -> dict:
        return {"model": model, "messages": messages, "max_tokens": request.max_tokens, "temperature": request.temperature}

    def usage_parser(self, payload: dict) -> Usage:
        usage = payload.get("usage") or {}
        return Usage(prompt_tokens=int(usage.get("prompt_tokens", 0) or 0), completion_tokens=int(usage.get("completion_tokens", 0) or 0))

    def _capture_quota(self, res: httpx.Response) -> None:
        """Groq/Cerebras/OpenRouter-style x-ratelimit-* headers. Prefers the daily bucket."""
        h = res.headers
        for unit, suffix in (("tokens", "tokens-day"), ("requests", "requests-day"), ("tokens", "tokens"), ("requests", "requests")):
            limit = h.get(f"x-ratelimit-limit-{suffix}")
            remaining = h.get(f"x-ratelimit-remaining-{suffix}")
            if limit is not None and remaining is not None:
                try:
                    self.last_quota = QuotaInfo(unit=unit, limit=float(limit), remaining=float(remaining), reset_at=parse_reset(h.get(f"x-ratelimit-reset-{suffix}")), source="headers")
                except ValueError:
                    continue
                return


class OpenAIAdapter(OpenAICompatibleAdapter):
    """api.openai.com: reasoning models (gpt-5, o-series) take max_completion_tokens, which also pays
    for hidden reasoning, and only the default temperature."""

    adapter_id = "openai"
    REASONING = ("gpt-5", "o1", "o3", "o4")

    def _body(self, model, messages, request: ExecuteRequest) -> dict:
        if str(model or "").startswith(self.REASONING):
            return {"model": model, "messages": messages, "max_completion_tokens": request.max_tokens + 8000}
        return {"model": model, "messages": messages, "max_completion_tokens": request.max_tokens, "temperature": request.temperature}


class OpenRouterAdapter(OpenAICompatibleAdapter):
    adapter_id = "openrouter"

    def quota_probe(self) -> QuotaInfo | None:
        res = self._request("GET", self.base_url + "/key", headers=self._headers())
        data = self._json(res).get("data", {})
        limit = data.get("limit")
        remaining = data.get("limit_remaining")
        if limit is None:
            return self.last_quota
        return QuotaInfo(unit="credits", limit=float(limit), remaining=float(remaining if remaining is not None else limit), source="key_endpoint")


class CloudflareAdapter(OpenAICompatibleAdapter):
    """Workers AI OpenAI-compatible endpoint. `account_id` fills the catalog URL template."""

    adapter_id = "cloudflare"

    def __init__(self, *, base_url: str, account_id: str | None = None, **kwargs):
        if "{account_id}" in base_url:
            if not account_id:
                raise ValueError("cloudflare adapter requires an account id")
            base_url = base_url.replace("{account_id}", account_id)
        super().__init__(base_url=base_url, **kwargs)
