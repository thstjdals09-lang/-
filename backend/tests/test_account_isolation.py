"""Each signed-in account has its own AI employees, keys, projects and lines."""

import httpx

from .conftest import CSRF


def _login(client, email):
    client.post("/auth/logout", headers=CSRF)
    assert client.post("/auth/dev-login", json={"email": email}, headers=CSRF).status_code == 200


def test_accounts_keep_their_own_ais_and_production(client, http):
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    http.add("GET", "generativelanguage.googleapis.com/v1beta/models", lambda r: httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash"}]}))
    seen_keys = []
    http.add("POST", "chat/completions", lambda r: (seen_keys.append(r.headers["authorization"]), httpx.Response(200, json={"choices": [{"message": {"content": "ok\nRESULT: PASS"}}]}))[1])

    # A signs in and adds Groq with A's key
    _login(client, "alice@example.com")
    a_conn = client.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_alice_key_123456"}, headers=CSRF).json()
    client.post("/projects", json={"topic": "홀덤"}, headers=CSRF)
    a_lines = [l["id"] for l in client.get("/lines").json()]

    # B signs in: sees nothing of A, adds a different AI
    _login(client, "bob@example.com")
    assert client.get("/providers/connections").json() == []
    assert client.get("/lines").json() == [] and client.get("/projects").json() == []
    assert client.get(f"/lines/{a_lines[0]}").status_code == 404
    assert client.delete(f"/providers/connections/{a_conn['id']}", headers=CSRF).status_code == 404
    assert client.post(f"/providers/connections/{a_conn['id']}/verify", headers=CSRF).status_code == 404
    b_conn = client.post("/providers/connections", json={"catalog_id": "gemini", "auth_type": "api_key", "api_key": "AIza_bob_key_123456"}, headers=CSRF).json()
    # B can also add Groq with B's own key (same provider, separate credential)
    client.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_bob_key_654321"}, headers=CSRF)
    assert {c["catalog_id"] for c in client.get("/providers/connections").json()} == {"gemini", "groq"}

    # B's production only ever uses B's keys
    client.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    b_line = client.get("/lines").json()[0]["id"]
    seen_keys.clear()
    client.post(f"/lines/{b_line}/run", headers=CSRF, params={"max_waves": 4})
    assert seen_keys and all("bob" in k for k in seen_keys)

    # A still sees only A's AI and lines
    _login(client, "alice@example.com")
    assert [c["catalog_id"] for c in client.get("/providers/connections").json()] == ["groq"]
    assert sorted(l["id"] for l in client.get("/lines").json()) == sorted(a_lines)
    assert b_conn["id"] not in str(client.get("/state").json())
