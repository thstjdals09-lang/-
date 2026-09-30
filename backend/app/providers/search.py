"""Web search adapters (market research for the ideation room).

Search connections live in the same encrypted vault and connection table as AI providers, but they
are tools, not AI employees: the router never assigns tasks to them. Verification runs one real
query so a bad key is caught at connect time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import ExecuteRequest, ExecuteResult, ErrorInfo, HealthResult, ProviderAdapter, ProviderError, Usage


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


class SearchAdapter(ProviderAdapter):
    adapter_id = "search"

    def __init__(self, *, api: str, base_url: str, secret: str | None, transport=None, timeout: float = 20):
        super().__init__(base_url=base_url, secret=secret, transport=transport, timeout=timeout)
        self.api = api

    def search(self, query: str, n: int = 5) -> list[SearchHit]:
        if not self._secret:
            raise ProviderError(ErrorInfo("auth_error", False), "search key missing")
        n = max(1, min(10, n))
        if self.api == "tavily":
            res = self._request("POST", self.base_url + "/search", headers={"Authorization": f"Bearer {self._secret}"},
                                json={"query": query, "max_results": n, "search_depth": "basic", "include_answer": False})
            items = [(r.get("title"), r.get("url"), r.get("content")) for r in res.json().get("results") or []]
        elif self.api == "brave":
            res = self._request("GET", self.base_url + "/web/search", headers={"X-Subscription-Token": self._secret, "Accept": "application/json"},
                                params={"q": query, "count": n})
            items = [(r.get("title"), r.get("url"), r.get("description")) for r in ((res.json().get("web") or {}).get("results") or [])]
        elif self.api == "serper":
            res = self._request("POST", self.base_url + "/search", headers={"X-API-KEY": self._secret}, json={"q": query, "num": n})
            items = [(r.get("title"), r.get("link"), r.get("snippet")) for r in res.json().get("organic") or []]
        else:
            raise ProviderError(ErrorInfo("bad_request", False), f"unknown search api {self.api}")
        hits = []
        for title, url, snippet in items[:n]:
            if title and url and str(url).startswith(("http://", "https://")):
                hits.append(SearchHit(str(title)[:200], str(url)[:500], " ".join(str(snippet or "").split())[:600]))
        return hits

    def health_check(self) -> HealthResult:
        try:
            self.search("indie game trends", 1)
        except ProviderError as exc:
            return HealthResult(False, [], str(exc))
        return HealthResult(True, [])

    def list_models(self) -> list[str]:
        return []

    def execute(self, request: ExecuteRequest) -> ExecuteResult:
        raise ProviderError(ErrorInfo("bad_request", False), "search connections do not run chat tasks")

    def usage_parser(self, payload: dict) -> Usage:
        return Usage()
