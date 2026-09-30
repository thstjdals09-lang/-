import dataclasses

import httpx
import pytest

from app import auth, db

from .conftest import CSRF


@pytest.fixture(autouse=True)
def fresh_throttle():
    auth.throttle.failures.clear()
    yield


def test_register_login_and_password_is_hashed(client):
    res = client.post("/auth/register", json={"email": "Alice@Example.com", "password": "correct horse"}, headers=CSRF)
    assert res.status_code == 200 and res.json()["email"] == "alice@example.com"
    assert client.get("/account").json()["signIn"] == "password"
    with db.transaction() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    client.post("/auth/logout", headers=CSRF)
    assert client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong pass"}, headers=CSRF).status_code == 401
    assert client.post("/auth/login", json={"email": "ALICE@example.com", "password": "correct horse"}, headers=CSRF).status_code == 200
    assert client.get("/auth/me").json()["email"] == "alice@example.com"


def test_register_rules(client, settings):
    assert client.post("/auth/register", json={"email": "not-an-email", "password": "12345678"}, headers=CSRF).status_code == 400
    assert client.post("/auth/register", json={"email": "a@b.co", "password": "short"}, headers=CSRF).status_code == 422
    assert client.post("/auth/register", json={"email": "a@b.co", "password": "12345678"}, headers=CSRF).status_code == 200
    assert client.post("/auth/register", json={"email": "A@B.co", "password": "12345678"}, headers=CSRF).status_code == 409
    client.app.state.settings = dataclasses.replace(settings, signup_mode="allowlist", allowed_emails=["ok@b.co"])
    assert client.post("/auth/register", json={"email": "no@b.co", "password": "12345678"}, headers=CSRF).status_code == 403
    assert client.post("/auth/register", json={"email": "ok@b.co", "password": "12345678"}, headers=CSRF).status_code == 200


def test_failed_logins_are_throttled(client):
    client.post("/auth/register", json={"email": "t@b.co", "password": "12345678"}, headers=CSRF)
    client.post("/auth/logout", headers=CSRF)
    codes = [client.post("/auth/login", json={"email": "t@b.co", "password": "nope-nope"}, headers=CSRF).status_code for _ in range(9)]
    assert codes[:8] == [401] * 8 and codes[8] == 429
    assert client.post("/auth/login", json={"email": "t@b.co", "password": "12345678"}, headers=CSRF).status_code == 429


def test_public_server_keeps_local_endpoints_for_the_owner(client, http, settings):
    public = dataclasses.replace(settings, public_url="https://factory.example.com", dev_login=False, admin_emails=["owner@b.co"],
                                 allowed_origins=settings.allowed_origins + ["https://factory.example.com"])
    client.app.state.settings = public
    http.add("GET", "127.0.0.1:11434/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "qwen2.5:3b"}]}))
    client.post("/auth/register", json={"email": "member@b.co", "password": "12345678"}, headers=CSRF)
    res = client.post("/providers/connections", json={"catalog_id": "local-ollama", "auth_type": "local"}, headers=CSRF)
    assert res.status_code == 403 and res.json()["detail"] == "local_endpoints_admin_only"
    assert client.post("/providers/connections", json={"catalog_id": "custom-endpoint", "auth_type": "custom_endpoint", "endpoint": "http://192.168.0.1/v1"}, headers=CSRF).status_code == 403
    # a hosted provider cannot be pointed at another address by a member
    seen = []
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: (seen.append(str(r.url)), httpx.Response(200, json={"data": [{"id": "x"}]}))[1])
    client.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_member_1234567", "endpoint": "http://192.168.0.1/v1"}, headers=CSRF)
    assert seen and all(u.startswith("https://api.groq.com/") for u in seen)
    # members are capped on a shared server
    assert client.patch("/settings", json={"max_parallel": 10, "workers_per_line": 8}, headers=CSRF).json()["max_parallel"] == 3
    # the owner may connect this PC's Ollama
    client.post("/auth/logout", headers=CSRF)
    client.post("/auth/register", json={"email": "owner@b.co", "password": "12345678"}, headers=CSRF)
    res = client.post("/providers/connections", json={"catalog_id": "local-ollama", "auth_type": "local"}, headers=CSRF)
    assert res.status_code == 201 and res.json()["status"] == "online" and res.json()["model"] == "qwen2.5:3b"
