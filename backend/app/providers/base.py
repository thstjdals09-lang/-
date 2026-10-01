"""Provider Adapter contract.

Every provider plugs into the factory through the same six operations:
health_check, list_models, execute, quota_probe, usage_parser and error_classifier.
Adapters hold a secret only in memory for the duration of a call and never log it.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from ..vault import redact


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ExecuteRequest:
    prompt: str
    system: str | None = None
    model: str | None = None
    max_tokens: int = 2048
    temperature: float = 0.4
    images: list[bytes] = field(default_factory=list)  # PNG screenshots for vision-capable models


@dataclass
class ExecuteResult:
    text: str
    model: str
    usage: Usage
    latency_ms: int


@dataclass
class QuotaInfo:
    unit: str | None = None
    limit: float | None = None
    remaining: float | None = None
    reset_at: datetime | None = None
    source: str = "headers"


@dataclass
class HealthResult:
    ok: bool
    models: list[str] = field(default_factory=list)
    detail: str | None = None


@dataclass
class ErrorInfo:
    kind: str  # rate_limited | auth_error | context_exceeded | transient | quota_exhausted | no_credit | bad_request | unknown
    retryable: bool
    cooldown_seconds: float = 0


class ProviderError(RuntimeError):
    def __init__(self, info: ErrorInfo, message: str, status: int | None = None):
        super().__init__(message)
        self.info = info
        self.status = status


MODEL_GONE_HINTS = ("no longer available", "decommissioned", "deprecated", "does not exist", "model_not_found",
                    "not found for api version", "terms acceptance", "model_terms_required", "unknown model", "invalid model")


NO_CREDIT_HINTS = ("credit balance is too low", "insufficient credit", "insufficient balance", "insufficient_quota", "insufficient funds",
                   "purchase credits", "billing hard limit", "payment required", "exceeded your current quota")


def classify_error(status: int | None, body: str = "") -> ErrorInfo:
    """Shared classifier. Mirrors classifyError in docs/js/router.js and adds body hints."""
    text = (body or "").lower()
    if status in (400, 403, 404) and "model" in text and any(h in text for h in MODEL_GONE_HINTS):
        return ErrorInfo("model_unavailable", True)
    if status == 402 or (status in (400, 403, 429) and any(h in text for h in NO_CREDIT_HINTS)):
        return ErrorInfo("no_credit", False)  # a paid account without balance: every call would fail the same way
    if status == 429:
        if "quota" in text and ("day" in text or "exceeded" in text):
            return ErrorInfo("quota_exhausted", True, 3600)
        return ErrorInfo("rate_limited", True, 45)
    if status in (401, 403):
        return ErrorInfo("auth_error", False)
    if status == 413 or "context_length" in text or "maximum context" in text or "too many tokens" in text:
        return ErrorInfo("context_exceeded", True)
    if status is None or status == 408 or 500 <= status < 600:
        return ErrorInfo("transient", True, 10)
    if 400 <= status < 500:
        return ErrorInfo("bad_request", False)
    return ErrorInfo("unknown", True, 5)


class ProviderAdapter(ABC):
    """Base class. Subclasses implement the HTTP details of one provider family."""

    adapter_id = "base"

    def __init__(self, *, base_url: str, secret: str | None = None, model: str | None = None, transport: httpx.BaseTransport | None = None, timeout: float = 60):
        self.base_url = (base_url or "").rstrip("/")
        self._secret = secret
        self.model = model
        self._transport = transport
        self._timeout = timeout
        self.last_quota: QuotaInfo | None = None

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def _raise_for(self, res: httpx.Response) -> None:
        if res.status_code < 400:
            return
        body = redact(res.text[:500], self._secret or "")
        raise ProviderError(self.error_classifier(res.status_code, body), f"{self.adapter_id} HTTP {res.status_code}: {body}", res.status_code)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            with self._client() as client:
                res = client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError(ErrorInfo("transient", True, 10), f"{self.adapter_id} timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ErrorInfo("transient", True, 10), f"{self.adapter_id} unreachable: {type(exc).__name__}") from exc
        self._raise_for(res)
        return res

    def _json(self, res: httpx.Response):
        """Body of a successful reply. A provider that answers 200 with something that is not JSON
        (a gateway page, a bare "OK") failed this call: the caller fails over to the next AI."""
        try:
            return res.json()
        except ValueError as exc:
            body = redact(res.text[:120], self._secret or "")
            raise ProviderError(ErrorInfo("transient", True, 60), f"{self.adapter_id} unexpected reply (not JSON): {body!r}") from exc

    # ---- contract ----

    def health_check(self) -> HealthResult:
        try:
            return HealthResult(True, self.list_models())
        except ProviderError as exc:
            return HealthResult(False, [], str(exc))

    @abstractmethod
    def list_models(self) -> list[str]: ...

    @abstractmethod
    def execute(self, request: ExecuteRequest) -> ExecuteResult: ...

    def quota_probe(self) -> QuotaInfo | None:
        """Best-effort live quota. Default: whatever the last response headers revealed."""
        return self.last_quota

    @abstractmethod
    def usage_parser(self, payload: dict) -> Usage: ...

    def error_classifier(self, status: int | None, body: str = "") -> ErrorInfo:
        return classify_error(status, body)

    # ---- helpers ----

    @staticmethod
    def _timer() -> float:
        return time.perf_counter()

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.perf_counter() - start) * 1000)


def parse_reset(value: str | None, now: datetime | None = None) -> datetime | None:
    """Parses rate-limit reset headers such as '2m59.56s', '7.66s', '120' or an epoch."""
    if not value:
        return None
    now = now or datetime.now(timezone.utc)
    value = value.strip()
    try:
        seconds = float(value)
        if seconds > 10**9:
            return datetime.fromtimestamp(seconds, timezone.utc)
        return datetime.fromtimestamp(now.timestamp() + seconds, timezone.utc)
    except ValueError:
        pass
    total = 0.0
    number = ""
    for ch in value:
        if ch.isdigit() or ch == ".":
            number += ch
        elif ch in "hms" and number:
            total += float(number) * {"h": 3600, "m": 60, "s": 1}[ch]
            number = ""
    if value.endswith("ms"):
        return now
    return datetime.fromtimestamp(now.timestamp() + total, timezone.utc) if total else None
