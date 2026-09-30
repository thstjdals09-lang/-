import dataclasses
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.factory.api import get_factory
from app.main import create_app

from .conftest import CSRF

GH_TOKEN = "ghp_alicetoken_1234567890abcdef"


def _login(client, email):
    client.post("/auth/logout", headers=CSRF)
    return client.post("/auth/dev-login", json={"email": email}, headers=CSRF)


def _github_user(http, login="alice", scopes="repo, read:org", status=200):
    http.add("GET", "api.github.com/user", lambda r: httpx.Response(status, headers={"x-oauth-scopes": scopes}, json={"login": login}))


def test_first_login_creates_account_with_profile_and_counts(signed_in):
    acc = signed_in.get("/account").json()
    assert acc["email"] == "ceo@example.com" and acc["role"] == "member" and acc["signIn"] == "local"
    assert acc["github"] == {"connected": False, "login": None}
    assert acc["counts"]["ais"] == 0 and acc["counts"]["lines"] == 0
    signed_in.post("/projects", json={"topic": "홀덤"}, headers=CSRF)
    assert signed_in.get("/account").json()["counts"]["lines"] == 3


def test_signup_allowlist_and_admin_role(client, settings):
    client.app.state.settings = dataclasses.replace(settings, signup_mode="allowlist", allowed_emails=["friend@example.com"], admin_emails=["boss@example.com"])
    assert _login(client, "stranger@example.com").status_code == 403
    assert _login(client, "friend@example.com").json()["role"] == "member"
    assert _login(client, "boss@example.com").json()["role"] == "admin"


def test_personal_github_is_verified_and_kept_in_the_vault(signed_in, http):
    _github_user(http)
    acc = signed_in.put("/account/github", json={"token": GH_TOKEN}, headers=CSRF)
    assert acc.status_code == 200 and acc.json()["github"] == {"connected": True, "login": "alice"}
    assert GH_TOKEN not in acc.text
    with db.transaction() as conn:
        row = conn.execute("SELECT github_credential_id FROM users WHERE email='ceo@example.com'").fetchone()
        assert row["github_credential_id"] and GH_TOKEN.encode() not in conn.execute("SELECT ciphertext FROM encrypted_credentials").fetchone()[0]
    assert signed_in.delete("/account/github", headers=CSRF).json()["github"]["connected"] is False
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM encrypted_credentials").fetchone()[0] == 0


@pytest.mark.parametrize("status,scopes,detail", [(401, "", "github_token_rejected"), (200, "read:user", "github_token_needs_repo_scope")])
def test_bad_github_tokens_are_refused(signed_in, http, status, scopes, detail):
    _github_user(http, status=status, scopes=scopes)
    res = signed_in.put("/account/github", json={"token": GH_TOKEN}, headers=CSRF)
    assert res.status_code == 400 and res.json()["detail"] == detail


def test_publishing_uses_each_accounts_own_github(client, http, settings, monkeypatch):
    monkeypatch.setenv("AI_FACTORY_GITHUB_TOKEN", "ghp_servertoken_000000000000")
    client.app.state.settings = dataclasses.replace(settings, admin_emails=["boss@example.com"])
    factory = get_factory(client.app)
    ids = {}
    for email in ("alice@example.com", "bob@example.com", "boss@example.com"):
        ids[email] = _login(client, email).json()["id"]
        if email == "alice@example.com":
            _github_user(http, login="alice")
            client.put("/account/github", json={"token": GH_TOKEN}, headers=CSRF)
    with db.transaction() as conn:
        alice = factory.github_for(conn, ids["alice@example.com"])
        assert alice is not None and alice._token == GH_TOKEN  # Alice's games go to Alice's GitHub
        assert factory.github_for(conn, ids["bob@example.com"]) is None  # Bob has not connected: nothing is published for him
        assert factory.github_for(conn, ids["boss@example.com"])._token == "ghp_servertoken_000000000000"  # server token: admin only


def test_logout_all_devices(client, settings):
    other = TestClient(client.app, base_url="http://127.0.0.1:8000")
    _login(client, "a@example.com")
    other.post("/auth/dev-login", json={"email": "a@example.com"}, headers=CSRF)
    assert other.get("/auth/me").status_code == 200
    assert client.post("/account/logout-all", headers=CSRF).status_code == 204
    assert other.get("/auth/me").status_code == 401 and client.get("/auth/me").status_code == 401


def test_export_has_data_but_no_secrets(signed_in, http):
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_exportsecret_123456"}, headers=CSRF)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    res = signed_in.get("/account/export")
    data = json.loads(res.text)
    assert "attachment" in res.headers["content-disposition"]
    assert len(data["ideas"]) == 10 and data["ai_connections"][0]["catalog_id"] == "groq"
    assert "gsk_exportsecret_123456" not in res.text and "ciphertext" not in res.text and "credential_id" not in res.text


def test_delete_account_removes_everything(signed_in, http):
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_deleteme_1234567"}, headers=CSRF)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
    ws = get_factory(signed_in.app).workspace(signed_in.get("/auth/me").json()["id"], line_id).root
    assert ws.exists()
    assert signed_in.request("DELETE", "/account", json={"confirm_email": "wrong@example.com"}, headers=CSRF).status_code == 400
    assert signed_in.request("DELETE", "/account", json={"confirm_email": "CEO@example.com"}, headers=CSRF).status_code == 204
    assert signed_in.get("/auth/me").status_code == 401
    with db.transaction() as conn:
        for table in ("users", "sessions", "encrypted_credentials", "provider_connections", "projects", "ideas", "production_lines", "tasks", "factory_logs"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert not ws.exists()


def test_local_login_is_refused_on_a_public_server(settings):
    with pytest.raises(RuntimeError, match="DEV_LOGIN"):
        create_app(dataclasses.replace(settings, dev_login=True, public_url="https://factory.example.com"))
    create_app(dataclasses.replace(settings, dev_login=False, public_url="https://factory.example.com"))
