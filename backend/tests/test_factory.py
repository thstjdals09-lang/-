import json
import re
import subprocess

import httpx
import pytest

from app import catalog, config, db
from app.factory.ideation import generate_ideas
from app.factory.leader import workspace_root
from app.factory.workspace import LineWorkspace, WorkspaceError

from .conftest import CSRF

# Captured from docs/js/engine.js generateIdeas (node) — the browser and server must agree.
JS_FIXTURES = [
    ("홀덤", "자동선택", "Windows PC", [["Puzzle Strategy", 82.6, 88, 83], ["Deckbuilder", 80.3, 89, 81], ["Roguelike Core", 79.9, 91, 82], ["Survivor", 78.9, 95, 82], ["Management RPG", 78.8, 75, 78], ["Tactical", 77, 71, 80], ["Arcade Score", 76.3, 63, 63], ["Social Party", 76.1, 94, 82], ["Extraction Lite", 74.7, 70, 80], ["Tycoon", 72.5, 73, 69]]),
    ("zombie", "Survivor", "Web", [["Roguelike Core", 81.9, 84, 82], ["Survivor", 79.4, 99, 81], ["Tycoon", 79.3, 89, 76], ["Puzzle Strategy", 78.8, 91, 80], ["Social Party", 78.6, 88, 82], ["Tactical", 78.4, 68, 73], ["Deckbuilder", 76.9, 69, 74], ["Extraction Lite", 76.1, 85, 78], ["Arcade Score", 74.9, 69, 74], ["Management RPG", 71.8, 66, 64]]),
]
BRANCH = re.compile(r"^ai-factory/[^/]+/[^/]+/[^/]+/[a-z]+-[\w-]+$")


@pytest.mark.parametrize("topic,genre,platform,expected", JS_FIXTURES)
def test_ideation_matches_browser_engine(topic, genre, platform, expected):
    studio = catalog.studio(config.load().catalog_dir)
    ideas = generate_ideas(topic, genre, platform, studio)
    assert [[i["type"], i["score"], i["metrics"]["fun"], i["reviews"][0]["score"]] for i in ideas] == expected


def _lines(client):
    return client.get("/lines").json()


def test_simulated_line_runs_through_git_worktrees_to_ceo_gate(signed_in, settings):
    assert signed_in.post("/projects", json={"topic": "홀덤"}, headers=CSRF).status_code == 201
    lines = _lines(signed_in)
    assert len(lines) == 3 and all(l["status"] == "running" for l in lines)
    line_id = lines[0]["id"]

    res = signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()
    assert res["status"] == "awaiting_ceo"
    detail = signed_in.get(f"/lines/{line_id}").json()
    assert [b["version"] for b in detail["builds"]] == ["1.0.0", "0.9.0", "0.8.0", "0.5.0", "0.1.0"]
    assert all(b["smoke"]["passed"] for b in detail["builds"])
    assert detail["commits"] and all(BRANCH.match(c["branch"]) for c in detail["commits"])
    coding = [t for s in detail["stages"].values() for t in s["tasks"] if t["kind"] == "coding"]
    assert coding and all(t["reviewer"] for t in coding)

    user_id = signed_in.get("/auth/me").json()["id"]
    ws = LineWorkspace(workspace_root(settings.workspace_dir, user_id, line_id))
    assert len(ws.worktrees()) == 1  # every task worktree was removed after merge
    branches = subprocess.run(["git", "branch", "--list"], cwd=ws.repo, capture_output=True, text=True).stdout.split()
    assert branches == ["*", "main"]
    assert "merge ai-factory/" in "\n".join(ws.log(200))
    assert ws.read("release/index.html").startswith("<!doctype html>")

    review = next(r for r in signed_in.get("/reviews").json() if r["line_id"] == line_id and r["blocking"])
    play = signed_in.get(f"/builds/{review['build_id']}/play")
    assert play.status_code == 200 and "sandbox allow-scripts" in play.headers["content-security-policy"]

    assert signed_in.post(f"/reviews/{review['id']}/approve", headers=CSRF).status_code == 200
    assert signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "complete"


def _connect(client, http, provider, models_url, models_payload):
    http.add("GET", models_url, lambda r: httpx.Response(200, json=models_payload))
    res = client.post("/providers/connections", json={"catalog_id": provider, "auth_type": "api_key", "api_key": f"{provider}-secret-123456"}, headers=CSRF)
    assert res.status_code == 201 and res.json()["status"] == "online", res.text
    return res.json()["id"]


def test_real_providers_are_routed_with_failover_and_usage(signed_in, http):
    groq = _connect(signed_in, http, "groq", "api.groq.com/openai/v1/models", {"data": [{"id": "llama"}]})
    gemini = _connect(signed_in, http, "gemini", "generativelanguage.googleapis.com/v1beta/models", {"models": [{"name": "models/gemini-2.5-flash"}]})
    calls = {"groq": 0}

    def groq_chat(req):
        # the first production-task call is rate limited (the ideation room's calls come earlier)
        if "# Stage" in json.loads(req.content)["messages"][-1]["content"]:
            calls["groq"] += 1
            if calls["groq"] == 1:
                return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "groq artifact\nRESULT: PASS"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50}})

    http.add("POST", "api.groq.com/openai/v1/chat/completions", groq_chat)
    http.add("POST", ":generateContent", lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "gemini artifact\nRESULT: PASS"}]}}], "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20}}))

    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    signed_in.post(f"/lines/{line_id}/run", headers=CSRF, params={"max_waves": 3})

    detail = signed_in.get(f"/lines/{line_id}").json()
    workers = {t["assignee"]["name"] for s in detail["stages"].values() for t in s["tasks"] if t["assignee"]}
    assert workers <= {"Groq Fast Worker", "Gemini Planner"} and workers
    logs = signed_in.get("/logs").json()
    assert any(l["type"] == "FAILOVER" for l in logs)
    conns = {c["id"]: c for c in signed_in.get("/providers/connections").json()}
    assert conns[gemini]["quota_used"] > 0 or conns[groq]["quota_used"] > 0
    with db.transaction() as conn:
        outcomes = {r[0] for r in conn.execute("SELECT outcome FROM usage_logs")}
    assert outcomes == {"ok", "error"}
    assert "secret-123456" not in json.dumps(logs)


def test_qa_failure_spawns_repair_and_retest(signed_in, http):
    _connect(signed_in, http, "groq", "api.groq.com/openai/v1/models", {"data": [{"id": "llama"}]})
    seen = {"fail": 0}

    def chat(req):
        body = json.loads(req.content)
        prompt = body["messages"][-1]["content"]
        if "RESULT: PASS" in prompt and seen["fail"] == 0 and "리스크" in prompt:
            seen["fail"] += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": "risk found\nRESULT: FAIL"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok\nRESULT: PASS"}}]})

    http.add("POST", "chat/completions", chat)
    signed_in.post("/projects", json={"topic": "타이핑"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    signed_in.post(f"/lines/{line_id}/run", headers=CSRF, params={"max_waves": 12})
    tasks = signed_in.get(f"/lines/{line_id}").json()["stages"]["greenlight"]["tasks"]
    keys = [t["id"] for t in tasks]
    assert "risk-fix1" in keys and "risk-retest1" in keys
    gate = next(t for t in tasks if t["id"] == "gate")
    assert "risk-retest1" in gate["depends"]
    assert all(t["status"] == "completed" for t in tasks)


def test_feedback_and_revision(signed_in):
    signed_in.post("/projects", json={"topic": "카지노 운영"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    assert signed_in.post(f"/lines/{line_id}/feedback", json={"text": "튜토리얼을 더 쉽게"}, headers=CSRF).status_code == 201
    tasks = signed_in.get(f"/lines/{line_id}").json()["stages"]["greenlight"]["tasks"]
    assert any(t["id"] == "ceo-1" and t["critical"] for t in tasks)
    signed_in.post(f"/lines/{line_id}/run", headers=CSRF)
    review = next(r for r in signed_in.get("/reviews").json() if r["line_id"] == line_id and r["blocking"])
    signed_in.post(f"/reviews/{review['id']}/revise", json={"text": "색을 더 밝게"}, headers=CSRF)
    line = signed_in.get(f"/lines/{line_id}").json()
    assert line["status"] == "running" and line["stage"] == "polish"
    assert signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "awaiting_ceo"


def test_backlog_capacity_and_ownership(signed_in, client):
    project = signed_in.post("/projects", json={"topic": "홀덤"}, headers=CSRF).json()["id"]
    ideas = signed_in.get(f"/projects/{project}/ideas").json()
    backlog = [i for i in ideas if i["status"] == "backlog"]
    assert len(backlog) == 7
    assert signed_in.post(f"/ideas/{backlog[0]['id']}/build", headers=CSRF).status_code == 409
    signed_in.patch("/settings", json={"max_parallel": 4}, headers=CSRF)
    assert signed_in.post(f"/ideas/{backlog[0]['id']}/build", headers=CSRF).status_code == 201
    line_id = _lines(signed_in)[0]["id"]
    signed_in.post("/auth/logout", headers=CSRF)
    signed_in.post("/auth/dev-login", json={"email": "other@example.com"}, headers=CSRF)
    assert signed_in.get(f"/lines/{line_id}").status_code == 404


def test_workspace_rejects_unsafe_paths(tmp_path):
    ws = LineWorkspace(tmp_path / "ws")
    ws.ensure("t")
    for bad in ("../escape.txt", ".git/config", "/abs.txt", r"\abs.txt", "C:/x.txt", "a/../../x.txt"):
        with pytest.raises(WorkspaceError):
            ws.commit_task(branch="ai-factory/p/l/a/s-t", files={bad: "x"}, message="m", author="a")


def test_state_snapshot_and_autopilot_pass(signed_in, client):
    from app.factory.api import get_factory
    from app.factory.leader import autopilot_pass

    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    assert autopilot_pass(get_factory(client.app)) == 3
    snap = signed_in.get("/state").json()
    assert len(snap["ideas"]) == 10 and len(snap["lines"]) == 3
    assert all(any(s["tasks"] for s in l["stages"].values()) for l in snap["lines"])
    assert snap["counters"]["tasksDone"] >= 3
    line_id = snap["lines"][0]["id"]
    signed_in.post(f"/lines/{line_id}/autopilot", json={"on": False}, headers=CSRF)
    assert autopilot_pass(get_factory(client.app)) == 2


VALID_GAME = """```html
<!doctype html><html><body data-ai-factory-game="v2"><h1>GENERATED-BY-MODEL</h1>
<script>function startGame(){document.body.dataset.started="1"}startGame()</script></body></html>
```"""


def _game_writer(game_block):
    def chat(req):
        prompt = json.loads(req.content)["messages"][-1]["content"]
        text = "notes\n" + game_block if "# Game deliverable" in prompt else "ok\nRESULT: PASS"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10}})
    return chat


def test_model_written_game_flows_into_builds_and_windows_package(signed_in, http, settings):
    _connect(signed_in, http, "groq", "api.groq.com/openai/v1/models", {"data": [{"id": "llama"}]})
    http.add("POST", "chat/completions", _game_writer(VALID_GAME))
    signed_in.post("/projects", json={"topic": "타이핑"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    assert signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "awaiting_ceo"
    assert any(l["type"] == "GAME UPDATE" for l in signed_in.get("/logs").json())
    for build in signed_in.get(f"/lines/{line_id}").json()["builds"]:
        assert "GENERATED-BY-MODEL" in signed_in.get(f"/builds/{build['id']}/play").text
    ws = LineWorkspace(workspace_root(settings.workspace_dir, signed_in.get("/auth/me").json()["id"], line_id))
    assert "GENERATED-BY-MODEL" in ws.read("release/windows/index.html")
    assert ws.read("release/windows/Play.cmd").startswith("@echo off")


def test_invalid_model_games_are_rejected_and_never_replaced_by_the_template(signed_in, http):
    _connect(signed_in, http, "groq", "api.groq.com/openai/v1/models", {"data": [{"id": "llama"}]})
    http.add("POST", "chat/completions", _game_writer("```html\n<!doctype html><body>no marker, no entry point</body>\n```"))
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    signed_in.post(f"/lines/{line_id}/run", headers=CSRF)
    types = [l["type"] for l in signed_in.get("/logs").json()]
    assert "GAME REJECTED" in types and types.count("GAME REWRITE") == 2 and "LINE PAUSED" in types
    detail = signed_in.get(f"/lines/{line_id}").json()
    assert detail["status"] == "paused" and detail["builds"] == []  # no template build presented as the AI's game


def test_wave_runs_provider_calls_in_parallel(signed_in, http):
    import threading
    import time as _time

    _connect(signed_in, http, "groq", "api.groq.com/openai/v1/models", {"data": [{"id": "llama"}]})
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow_chat(req):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        _time.sleep(0.4)
        with lock:
            live["now"] -= 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok\nRESULT: PASS"}}]})

    http.add("POST", "chat/completions", slow_chat)
    signed_in.post("/projects", json={"topic": "홀덤"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    wave = signed_in.post(f"/lines/{line_id}/tick", headers=CSRF).json()
    assert wave["executed"] == 3  # greenlight: loop, scope, tech have no dependencies
    assert live["peak"] >= 2
    tasks = signed_in.get(f"/lines/{line_id}").json()["stages"]["greenlight"]["tasks"]
    assert sum(t["status"] == "completed" for t in tasks) == 3


def _prompt_recorder(game_reply):
    prompts = []

    def chat(req):
        prompt = json.loads(req.content)["messages"][-1]["content"]
        prompts.append(prompt)
        text = "notes\n" + game_reply(prompt) if "# Game deliverable" in prompt else "ok\nRESULT: PASS"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})
    return chat, prompts


def _run_to_build(signed_in, topic, count=2):
    signed_in.post("/projects", json={"topic": topic}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    for _ in range(90):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
        detail = signed_in.get(f"/lines/{line_id}").json()
        if len(detail["builds"]) >= count:
            return line_id, detail
    raise AssertionError("not enough builds")


def test_fallback_template_is_never_the_base_for_ai_game_work(signed_in, http):
    _connect(signed_in, http, "groq", "api.groq.com/openai/v1/models", {"data": [{"id": "llama"}]})
    chat, prompts = _prompt_recorder(lambda p: "```html\n<!doctype html><body>broken, no entry point</body>\n```")
    http.add("POST", "chat/completions", chat)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    signed_in.post(f"/lines/{_lines(signed_in)[0]['id']}/run", headers=CSRF)
    game_prompts = [p for p in prompts if "# Game deliverable" in p]
    assert len(game_prompts) >= 2
    assert all("No game exists yet" in p and "# Current game source" not in p for p in game_prompts)
    assert any(l["type"] == "TEMPLATE FALLBACK" for l in signed_in.get("/logs").json())


def test_template_echo_is_rejected_and_marker_is_added_to_real_games(signed_in, http, settings):
    from app.factory import games

    _connect(signed_in, http, "groq", "api.groq.com/openai/v1/models", {"data": [{"id": "llama"}]})
    template = games.render(settings.catalog_dir, title="t", topic="x", game_type="Survivor")
    own = "<html><body><canvas></canvas><script>function startGame(){window.OWN_GAME=1}</script><p>OWN-GAME</p></body></html>"
    calls = {"n": 0}

    def reply(prompt):
        calls["n"] += 1
        return "```html\n" + (template if calls["n"] == 1 else own) + "\n```"

    chat, _ = _prompt_recorder(reply)
    http.add("POST", "chat/completions", chat)
    line_id, detail = _run_to_build(signed_in, "좀비")
    logs = signed_in.get("/logs").json()
    assert any(l["type"] == "GAME REJECTED" and "템플릿" in l["text"] for l in logs)
    html = signed_in.get(f"/builds/{detail['builds'][0]['id']}/play").text
    assert "OWN-GAME" in html and 'data-ai-factory-game="v2"' in html and not games.is_fallback(html)


def test_relative_workspace_paths_never_commit_into_an_enclosing_repository(tmp_path, monkeypatch):
    """Regression: a relative workspace root made task commits land in the enclosing repo."""
    import os

    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(outer)], check=True)
    subprocess.run(["git", "-C", str(outer), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "outer"], check=True)
    before = subprocess.run(["git", "-C", str(outer), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    monkeypatch.chdir(outer)
    ws = LineWorkspace(os.path.join("data", "ws"))  # relative, inside the outer repository
    ws.ensure("t")
    ws.commit_task(branch="ai-factory/p/l/a/s-t", files={"x.md": "hello"}, message="task", author="a")
    assert subprocess.run(["git", "-C", str(outer), "rev-parse", "HEAD"], capture_output=True, text=True).stdout == before
    assert "merge ai-factory/p/l/a/s-t" in "\n".join(ws.log())
    assert ws.read("x.md") == "hello"


def test_retired_model_is_switched_automatically(signed_in, http):
    models = {"models": [{"name": "models/gemini-flash-latest"}, {"name": "models/gemini-3-flash-preview"}, {"name": "models/gemini-2.5-flash-preview-tts"}]}
    http.add("GET", "generativelanguage.googleapis.com/v1beta/models", lambda r: httpx.Response(200, json=models))
    res = signed_in.post("/providers/connections", json={"catalog_id": "gemini", "auth_type": "api_key", "api_key": "AIza-test-1234567890"}, headers=CSRF).json()
    assert res["model"] == "gemini-flash-latest"
    used = []

    def generate(req):
        model = str(req.url).split("/models/")[1].split(":")[0]
        used.append(model)
        if model == "gemini-flash-latest":
            return httpx.Response(404, text='{"error":{"message":"This model models/gemini-flash-latest is no longer available to new users."}}')
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok\nRESULT: PASS"}]}}]})

    http.add("POST", ":generateContent", generate)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
    signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
    conn = signed_in.get("/providers/connections").json()[0]
    assert conn["model"] == "gemini-3-flash-preview"  # never the TTS model
    assert any(l["type"] == "MODEL SWITCH" for l in signed_in.get("/logs").json())
    assert "gemini-3-flash-preview" in used


def test_restart_requeues_interrupted_tasks(signed_in):
    from app.factory.api import get_factory

    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = _lines(signed_in)[0]["id"]
    signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
    with db.transaction() as conn:
        conn.execute("UPDATE tasks SET status='in_progress' WHERE line_id=? AND status='ready'", (line_id,))
        stuck = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='in_progress'").fetchone()[0]
        assert stuck > 0
        assert get_factory(signed_in.app).recover_on_startup(conn)["tasks_requeued"] == stuck
    assert signed_in.post(f"/lines/{line_id}/tick", headers=CSRF).json()["executed"] > 0
