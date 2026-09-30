import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, vault
from app.main import create_app

CSRF = {"X-AI-Factory": "1"}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_FACTORY_DB", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv(vault.KEY_ENV, vault.generate_key())
    monkeypatch.setenv("AI_FACTORY_WORKSPACE", str(tmp_path / "workspaces"))
    monkeypatch.setenv("AI_FACTORY_AUTOPILOT_SECONDS", "0")  # tests drive the Leader explicitly
    monkeypatch.setenv("AI_FACTORY_RUNTIME_QA", "off")  # enabled explicitly by runtime QA tests
    yield


class Router:
    """Tiny programmable httpx transport: register (method, url-substring) → handler."""

    def __init__(self):
        self.routes = []
        self.requests: list[httpx.Request] = []

    def add(self, method, fragment, handler):
        self.routes.append((method, fragment, handler))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for method, fragment, handler in self.routes:
            if request.method == method and fragment in str(request.url):
                return handler(request)
        return httpx.Response(404, json={"error": "no route"})


@pytest.fixture
def http():
    return Router()


@pytest.fixture
def settings(tmp_path):
    base = config.load()
    return dataclasses.replace(base, dev_login=True, cookie_secure=False, cookie_samesite="lax", workspace_dir=tmp_path / "workspaces")


@pytest.fixture
def client(settings, http):
    app = create_app(settings)
    app.state.http_transport = httpx.MockTransport(http)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


@pytest.fixture
def signed_in(client):
    res = client.post("/auth/dev-login", json={"email": "ceo@example.com", "name": "CEO"}, headers=CSRF)
    assert res.status_code == 200
    return client
