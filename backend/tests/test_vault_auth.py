import base64
import json
import time

import httpx
import pytest
from fastapi import HTTPException

from app import auth, config, db, vault

from .conftest import CSRF


def _id_token(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return enc({"alg": "RS256"}) + "." + enc(claims) + ".sig"


def test_vault_roundtrip_is_bound_to_user():
    db.migrate()
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(id, email) VALUES ('u1','a@x'), ('u2','b@x')")
        cid = vault.store(conn, "u1", "gsk_supersecretvalue123")
        raw = conn.execute("SELECT ciphertext FROM encrypted_credentials WHERE id=?", (cid,)).fetchone()[0]
        assert b"supersecret" not in raw
        assert vault.reveal(conn, "u1", cid) == "gsk_supersecretvalue123"
        with pytest.raises(vault.VaultError):
            vault.reveal(conn, "u2", cid)
        conn.execute("UPDATE encrypted_credentials SET user_id='u2' WHERE id=?", (cid,))
        with pytest.raises(vault.VaultError):
            vault.reveal(conn, "u2", cid)  # AAD binds the ciphertext to its original owner


def test_vault_requires_master_key(monkeypatch):
    monkeypatch.delenv(vault.KEY_ENV)
    assert not vault.configured()


def test_redact_strips_known_and_shaped_secrets():
    text = "Authorization: Bearer abcdefghijklmnop key=AIzaSyA1234567890abcdef leaked gsk_1234567890abcdefgh mine"
    out = vault.redact(text, "mine")
    assert "abcdefghijklmnop" not in out and "AIzaSy" not in out and "gsk_" not in out and "mine" not in out
    assert "Authorization: Bearer [REDACTED]" in out


def test_dev_login_is_off_by_default(client):
    client.app.state.settings = config.load()
    assert client.post("/auth/dev-login", json={"email": "x@y.z"}, headers=CSRF).status_code == 404


def test_session_lifecycle(signed_in):
    me = signed_in.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "ceo@example.com"
    assert signed_in.post("/auth/logout", headers=CSRF).status_code == 204
    assert signed_in.get("/auth/me").status_code == 401


def test_csrf_guard_blocks_missing_header_and_foreign_origin(signed_in):
    assert signed_in.post("/auth/logout").status_code == 403
    res = signed_in.post("/auth/logout", headers={**CSRF, "Origin": "https://evil.example"})
    assert res.status_code == 403


def test_return_to_is_allow_listed(settings):
    assert auth.safe_return_to("https://thstjdals09-lang.github.io/-/", settings) == "https://thstjdals09-lang.github.io/-/"
    assert auth.safe_return_to("https://evil.example/phish", settings) == settings.allowed_origins[0] + "/"
    assert auth.safe_return_to("https://thstjdals09-lang.github.io.evil.example/", settings).startswith(settings.allowed_origins[0])


def test_id_token_claim_validation():
    good = {"iss": "https://accounts.google.com", "aud": "cid", "exp": time.time() + 60, "email": "a@b.c", "email_verified": True, "sub": "1"}
    assert auth.validate_id_token(_id_token(good), "cid")["email"] == "a@b.c"
    for bad in ({"aud": "other"}, {"iss": "https://evil"}, {"exp": time.time() - 5}, {"email_verified": False}):
        with pytest.raises(HTTPException):
            auth.validate_id_token(_id_token({**good, **bad}), "cid")


def test_google_login_callback_flow(client, http, settings):
    import dataclasses

    client.app.state.settings = dataclasses.replace(settings, google_client_id="cid", google_client_secret="csecret")
    res = client.get("/auth/google/login", params={"return_to": "https://thstjdals09-lang.github.io/-/"}, follow_redirects=False)
    assert res.status_code == 302 and "code_challenge" in res.headers["location"]
    state = httpx.URL(res.headers["location"]).params["state"]

    def token(request: httpx.Request):
        form = dict(x.split("=") for x in request.content.decode().split("&"))
        assert form["code_verifier"] and form["client_secret"] == "csecret"
        claims = {"iss": "accounts.google.com", "aud": "cid", "exp": time.time() + 300, "email": "ceo@gmail.test", "email_verified": True, "sub": "g-1", "name": "CEO"}
        return httpx.Response(200, json={"id_token": _id_token(claims)})

    http.add("POST", "oauth2.googleapis.com/token", token)
    cb = client.get("/auth/google/callback", params={"state": state, "code": "abc"}, follow_redirects=False)
    assert cb.status_code == 302
    assert cb.headers["location"] == "https://thstjdals09-lang.github.io/-/?login=ok"
    assert "httponly" in cb.headers["set-cookie"].lower()
    assert client.get("/auth/me").json()["email"] == "ceo@gmail.test"
    # state is single use
    assert client.get("/auth/google/callback", params={"state": state, "code": "abc"}, follow_redirects=False).status_code == 400
