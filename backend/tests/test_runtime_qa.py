import json

import httpx
import pytest

from app import config
from app.factory import games, runtime_qa

from .conftest import CSRF


@pytest.fixture
def runtime_on(monkeypatch):
    monkeypatch.setenv("AI_FACTORY_RUNTIME_QA", "auto")
    if not runtime_qa.available():
        pytest.skip("node + playwright not available for runtime QA")


def test_template_game_passes_runtime_qa_with_screenshot(runtime_on):
    html = games.render(config.load().catalog_dir, title="t", topic="x", game_type="Survivor")
    res = runtime_qa.run(html)
    assert res["status"] == "passed", res
    assert res["screenshot"].startswith(b"\x89PNG")


def test_runtime_errors_and_network_are_caught(runtime_on):
    broken = '<!doctype html><body data-ai-factory-game="v2"><p>x</p><script>function startGame(){fetch("https://example.com/x")}</script></body>'
    res = runtime_qa.run(broken)
    checks = {c["id"]: c["ok"] for c in res["checks"]}
    assert res["status"] == "failed" and checks["no_network"] is False
    crash = '<!doctype html><body data-ai-factory-game="v2"><script>function startGame(){}; missing();</script></body>'
    res = runtime_qa.run(crash)
    assert res["status"] == "failed" and any("missing" in e for e in res["errors"])


def test_runner_reports_unavailable_when_disabled(monkeypatch):
    monkeypatch.setenv("AI_FACTORY_RUNTIME_QA", "off")
    assert runtime_qa.run("<!doctype html>")["status"] == "unavailable"


CRASHING_GAME = """```html
<!doctype html><html><body data-ai-factory-game="v2"><h1>CRASH</h1><script>function startGame(){}; notDefined();</script></body></html>
```"""


def test_failed_runtime_gate_repairs_then_reverts_to_safe_game(runtime_on, signed_in, http):
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_test_1234567890"}, headers=CSRF)

    def chat(req):
        prompt = json.loads(req.content)["messages"][-1]["content"]
        text = "notes\n" + CRASHING_GAME if "# Game deliverable" in prompt else "ok\nRESULT: PASS"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    http.add("POST", "chat/completions", chat)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    for _ in range(40):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
        detail = signed_in.get(f"/lines/{line_id}").json()
        if detail["builds"]:
            break
    types = [l["type"] for l in signed_in.get("/logs").json()]
    assert types.count("RUNTIME QA FAIL") == 2 and "RUNTIME REVERT" in types
    keys = [t["id"] for t in detail["stages"]["prototype"]["tasks"]]
    assert "runtime-fix1" in keys and "runtime-fix2" in keys
    build = detail["builds"][0]
    assert build["runtime"] == "passed" and build["screenshot"]
    shot = signed_in.get(f"/builds/{build['id']}/screenshot.png")
    assert shot.status_code == 200 and shot.content.startswith(b"\x89PNG")
    assert "CRASH" not in signed_in.get(f"/builds/{build['id']}/play").text


def test_vision_qa_receives_the_runtime_screenshot(runtime_on, signed_in, http):
    from .test_collaboration import _setup

    studio = _setup(signed_in, http)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    for _ in range(80):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
        tasks = signed_in.get(f"/lines/{line_id}").json()["stages"].get("vertical", {}).get("tasks", [])
        if any(t["id"] == "visualqa" and t["status"] == "completed" for t in tasks):
            break
    assert studio.images >= 1
    assert any("qa/runtime-now.json" in p for p in studio.prompts if "비전 기반 화면 QA" in p)
