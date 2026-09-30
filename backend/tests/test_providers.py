import json
import httpx
import pytest

from app import catalog, config
from app.providers import ExecuteRequest, ProviderError, build_adapter, classify_error

from .conftest import CSRF

SECRET = "gsk_testsecret_1234567890"


def entry(pid):
    return catalog.provider(config.load().catalog_dir, pid)


def mock(handler):
    return httpx.MockTransport(handler)


def test_openai_compatible_execute_usage_and_quota_headers():
    def handler(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer " + SECRET
        assert req.url.path == "/openai/v1/chat/completions"
        return httpx.Response(
            200,
            headers={"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "987", "x-ratelimit-reset-requests": "2m30s"},
            json={"model": "llama", "choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}},
        )

    adapter = build_adapter(entry("groq"), secret=SECRET, transport=mock(handler))
    result = adapter.execute(ExecuteRequest(prompt="hi", system="be brief"))
    assert result.text == "hello" and result.usage.total_tokens == 18
    q = adapter.quota_probe()
    assert (q.unit, q.limit, q.remaining) == ("requests", 1000, 987) and q.reset_at is not None


def test_gemini_keeps_key_out_of_url():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        assert req.headers["x-goog-api-key"] == SECRET
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "plan"}]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 9}})

    adapter = build_adapter(entry("gemini"), secret=SECRET, transport=mock(handler))
    assert adapter.list_models() == ["gemini-2.5-flash"]
    res = adapter.execute(ExecuteRequest(prompt="x"))
    assert res.text == "plan" and res.usage.completion_tokens == 9
    assert SECRET not in seen["url"]


def test_errors_are_classified_and_redacted():
    def handler(req):
        return httpx.Response(429, text="Rate limit reached for key " + SECRET)

    adapter = build_adapter(entry("cerebras"), secret=SECRET, transport=mock(handler))
    with pytest.raises(ProviderError) as err:
        adapter.execute(ExecuteRequest(prompt="x"))
    assert err.value.info.kind == "rate_limited"
    assert SECRET not in str(err.value)


def test_network_failure_is_transient():
    def handler(req):
        raise httpx.ConnectError("refused")

    adapter = build_adapter(entry("local-llamacpp"), transport=mock(handler))
    health = adapter.health_check()
    assert not health.ok
    with pytest.raises(ProviderError) as err:
        adapter.list_models()
    assert err.value.info.kind == "transient"


def test_classifier_table():
    assert classify_error(401).kind == "auth_error"
    assert classify_error(429, "quota exceeded for the day").kind == "quota_exhausted"
    assert classify_error(400, "maximum context length is 8192").kind == "context_exceeded"
    assert classify_error(503).kind == "transient"
    assert classify_error(None).kind == "transient"


def test_cloudflare_account_template():
    adapter = build_adapter(entry("cloudflare"), secret=SECRET, endpoint="acc123")
    assert adapter.base_url.endswith("/accounts/acc123/ai/v1")
    with pytest.raises(ValueError):
        build_adapter(entry("cloudflare"), secret=SECRET)


def test_connection_stores_secret_only_in_vault(signed_in, http):
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(
        200, headers={"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "990"}, json={"data": [{"id": "llama-3.3-70b-versatile"}]}))
    res = signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": SECRET}, headers=CSRF)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "online"
    assert body["credential_ref"].startswith("vault://")
    assert body["models"] == ["llama-3.3-70b-versatile"]
    assert body["quota_limit"] == 1000 and body["quota_used"] == 10
    assert SECRET not in res.text
    assert SECRET not in signed_in.get("/providers/connections").text
    assert signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": SECRET}, headers=CSRF).status_code == 409
    assert signed_in.delete("/providers/connections/" + body["id"], headers=CSRF).status_code == 204
    assert signed_in.get("/providers/connections").json() == []


def test_connection_with_rejected_key_needs_reauth(signed_in, http):
    http.add("GET", "api.cerebras.ai/v1/models", lambda r: httpx.Response(401, json={"error": "invalid key"}))
    res = signed_in.post("/providers/connections", json={"catalog_id": "cerebras", "auth_type": "api_key", "api_key": SECRET}, headers=CSRF)
    assert res.json()["status"] == "auth_required"


def test_connection_guards(signed_in, client, monkeypatch):
    assert signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key"}, headers=CSRF).status_code == 400
    assert signed_in.post("/providers/connections", json={"catalog_id": "nope", "auth_type": "api_key", "api_key": "x"}, headers=CSRF).status_code == 404
    assert signed_in.get("/providers/oauth/groq/start").status_code == 404  # groq has no login flow, only keys
    monkeypatch.delenv("AI_FACTORY_VAULT_KEY")
    assert signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "x"}, headers=CSRF).status_code == 503


def test_connections_require_login(client):
    assert client.get("/providers/connections").status_code == 401


def test_openrouter_login_issues_key_into_vault(signed_in, http):
    start = signed_in.get("/providers/oauth/openrouter/start", params={"return_to": "http://127.0.0.1:8000/console/"})
    assert start.status_code == 200
    url = httpx.URL(start.json()["authorize_url"])
    assert url.host == "openrouter.ai" and url.params["code_challenge_method"] == "S256"
    callback = httpx.URL(url.params["callback_url"])
    issued = "sk-or-v1-issuedkey1234567890"

    def exchange(req):
        body = json.loads(req.content)
        assert body["code"] == "code-123" and body["code_verifier"] and body["code_challenge_method"] == "S256"
        return httpx.Response(200, json={"key": issued})

    http.add("POST", "openrouter.ai/api/v1/auth/keys", exchange)
    http.add("GET", "openrouter.ai/api/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "openrouter/free"}]}))
    http.add("GET", "openrouter.ai/api/v1/key", lambda r: httpx.Response(200, json={"data": {"limit": None}}))
    back = signed_in.get(callback.path, params={"code": "code-123"}, follow_redirects=False)
    assert back.status_code == 302 and "connected=openrouter" in back.headers["location"] and "status=online" in back.headers["location"]
    conns = signed_in.get("/providers/connections").json()
    assert conns[0]["catalog_id"] == "openrouter" and conns[0]["auth_type"] == "oauth" and conns[0]["credential_ref"].startswith("vault://")
    assert issued not in json.dumps(conns)
    # state is single use and bound to the user who started the login
    assert signed_in.get(callback.path, params={"code": "code-123"}, follow_redirects=False).status_code == 400


def test_openrouter_login_rejects_another_session(signed_in, http):
    start = signed_in.get("/providers/oauth/openrouter/start").json()
    callback = httpx.URL(httpx.URL(start["authorize_url"]).params["callback_url"])
    signed_in.post("/auth/logout", headers=CSRF)
    signed_in.post("/auth/dev-login", json={"email": "intruder@example.com"}, headers=CSRF)
    back = signed_in.get(callback.path, params={"code": "x"}, follow_redirects=False)
    assert "connect_error=session_mismatch" in back.headers["location"]
    assert signed_in.get("/providers/connections").json() == []
