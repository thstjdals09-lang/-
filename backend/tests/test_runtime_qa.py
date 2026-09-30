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


def test_failed_runtime_gate_repairs_rewrites_then_pauses_without_template(runtime_on, signed_in, http):
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_test_1234567890"}, headers=CSRF)

    prompts = []

    def chat(req):
        prompt = json.loads(req.content)["messages"][-1]["content"]
        prompts.append(prompt)
        text = "notes\n" + CRASHING_GAME if "# Game deliverable" in prompt else "ok\nRESULT: PASS"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    http.add("POST", "chat/completions", chat)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    for _ in range(60):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
        detail = signed_in.get(f"/lines/{line_id}").json()
        if detail["status"] != "running":
            break
    types = [l["type"] for l in signed_in.get("/logs").json()]
    assert types.count("RUNTIME QA FAIL") == 2 and types.count("GAME REWRITE") == 2 and "LINE PAUSED" in types
    assert "RUNTIME REVERT" not in types and "RUNTIME ROLLBACK" not in types
    keys = [t["id"] for t in detail["stages"]["prototype"]["tasks"]]
    assert {"runtime-fix1", "runtime-fix2", "rewrite1", "rewrite2"} <= set(keys)
    # the emergency template is never shipped as the AI's build
    assert detail["status"] == "paused" and detail["builds"] == []
    rewrite = next(p for p in prompts if "게임 처음부터 다시 작성" in p)
    assert "No game exists yet" in rewrite and "# Current game source" not in rewrite
    # resuming grants another rewrite
    assert signed_in.post(f"/lines/{line_id}/resume", headers=CSRF).json()["status"] == "running"
    keys = [t["id"] for t in signed_in.get(f"/lines/{line_id}").json()["stages"]["prototype"]["tasks"]]
    assert any(k.startswith("rewrite-r") for k in keys)


def test_last_passing_ai_game_is_restored_after_failed_fixes(runtime_on, signed_in, http):
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    signed_in.post("/providers/connections", json={"catalog_id": "groq", "auth_type": "api_key", "api_key": "gsk_test_1234567890"}, headers=CSRF)
    good = """```html
<!doctype html><html><body data-ai-factory-game="v2"><h1>GOOD-GAME</h1><button id="b">go</button><canvas width="10" height="10"></canvas>
<script>function startGame(){document.getElementById('b').textContent='started'};document.addEventListener('keydown',()=>{document.body.dataset.k=1});startGame();</script></body></html>
```"""
    state = {"crash": False}

    def chat(req):
        prompt = json.loads(req.content)["messages"][-1]["content"]
        if "# Game deliverable" in prompt:
            return httpx.Response(200, json={"choices": [{"message": {"content": "notes\n" + (CRASHING_GAME if state["crash"] else good)}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok\nRESULT: PASS"}}]})

    http.add("POST", "chat/completions", chat)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    for _ in range(40):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
        if signed_in.get(f"/lines/{line_id}").json()["builds"]:
            break
    assert signed_in.get(f"/lines/{line_id}").json()["builds"][0]["runtime"] == "passed"
    state["crash"] = True  # later programmers break the game and cannot fix it
    for _ in range(60):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
        detail = signed_in.get(f"/lines/{line_id}").json()
        if len(detail["builds"]) >= 2:
            break
    types = [l["type"] for l in signed_in.get("/logs").json()]
    assert "RUNTIME ROLLBACK" in types
    latest = detail["builds"][0]
    assert "GOOD-GAME" in signed_in.get(f"/builds/{latest['id']}/play").text


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
