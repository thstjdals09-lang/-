"""Anthropic Messages API adapter (paid Claude models on the user's own key)."""

from __future__ import annotations

import base64

from .base import ExecuteRequest, ExecuteResult, ProviderAdapter, QuotaInfo, Usage, parse_reset

API_VERSION = "2023-06-01"


class AnthropicAdapter(ProviderAdapter):
    adapter_id = "anthropic"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._secret or "", "anthropic-version": API_VERSION, "content-type": "application/json"}

    def list_models(self) -> list[str]:
        res = self._request("GET", self.base_url + "/models", headers=self._headers(), params={"limit": 100})
        return [m["id"] for m in res.json().get("data") or [] if isinstance(m, dict) and m.get("id")]

    def execute(self, request: ExecuteRequest) -> ExecuteResult:
        content: list[dict] | str = request.prompt
        if request.images:
            content = [{"type": "text", "text": request.prompt}] + [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(img).decode()}}
                for img in request.images
            ]
        model = request.model or self.model
        body = {"model": model, "max_tokens": request.max_tokens, "temperature": request.temperature,
                "messages": [{"role": "user", "content": content}]}
        if request.system:
            body["system"] = request.system
        start = self._timer()
        res = self._request("POST", self.base_url + "/messages", headers=self._headers(), json=body)
        self._capture_quota(res)
        payload = res.json()
        text = "".join(part.get("text", "") for part in payload.get("content") or [] if part.get("type") == "text")
        return ExecuteResult(text=text, model=payload.get("model", model or ""), usage=self.usage_parser(payload), latency_ms=self._elapsed_ms(start))

    def usage_parser(self, payload: dict) -> Usage:
        usage = payload.get("usage") or {}
        return Usage(prompt_tokens=int(usage.get("input_tokens", 0) or 0), completion_tokens=int(usage.get("output_tokens", 0) or 0))

    def _capture_quota(self, res) -> None:
        h = res.headers
        limit, remaining = h.get("anthropic-ratelimit-requests-limit"), h.get("anthropic-ratelimit-requests-remaining")
        if limit is not None and remaining is not None:
            try:
                self.last_quota = QuotaInfo(unit="requests", limit=float(limit), remaining=float(remaining),
                                            reset_at=parse_reset(h.get("anthropic-ratelimit-requests-reset")), source="headers")
            except ValueError:
                pass
