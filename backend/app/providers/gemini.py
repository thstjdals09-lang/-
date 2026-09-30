"""Google Gemini (Generative Language API) adapter. The key travels in the x-goog-api-key header,
never in the URL, so it cannot leak through access logs."""

from __future__ import annotations

from .base import ExecuteRequest, ExecuteResult, ProviderAdapter, Usage


class GeminiAdapter(ProviderAdapter):
    adapter_id = "gemini"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._secret:
            headers["x-goog-api-key"] = self._secret
        return headers

    def list_models(self) -> list[str]:
        res = self._request("GET", self.base_url + "/models", headers=self._headers())
        return [m["name"].removeprefix("models/") for m in res.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", ["generateContent"])]

    def execute(self, request: ExecuteRequest) -> ExecuteResult:
        model = request.model or self.model or "gemini-2.5-flash"
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": {"maxOutputTokens": request.max_tokens, "temperature": request.temperature},
        }
        if request.system:
            body["systemInstruction"] = {"parts": [{"text": request.system}]}
        start = self._timer()
        res = self._request("POST", f"{self.base_url}/models/{model}:generateContent", headers=self._headers(), json=body)
        payload = res.json()
        parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        return ExecuteResult(text=text, model=model, usage=self.usage_parser(payload), latency_ms=self._elapsed_ms(start))

    def usage_parser(self, payload: dict) -> Usage:
        meta = payload.get("usageMetadata") or {}
        return Usage(prompt_tokens=int(meta.get("promptTokenCount", 0)), completion_tokens=int(meta.get("candidatesTokenCount", 0)))
