"""Web market research, paid providers, load balancing across every connected AI, diff repair and
the background ideation room."""

import json
from collections import Counter

import httpx

from app import catalog, db
from app.factory import games
from app.factory.api import get_factory
from app.providers import ExecuteRequest, build_adapter

from .conftest import CSRF
from .test_collaboration import _setup

RESULTS = [{"title": f"좀비 게임 기사 {i}", "url": f"https://news.example.com/zombie-{i}", "content": f"플레이어들은 기지 방어를 좋아함 {i}"} for i in range(5)]


def _entry(client, provider_id):
    return catalog.provider(client.app.state.settings.catalog_dir, provider_id)


def _tavily(http, calls):
    def search(req):
        calls.append(json.loads(req.content))
        if req.headers.get("authorization") != "Bearer tvly-test-1234567890":
            return httpx.Response(401, json={"detail": "invalid key"})
        return httpx.Response(200, json={"results": RESULTS})

    http.add("POST", "api.tavily.com/search", search)


def test_search_adapters_parse_each_api(client):
    t = client.app.state.settings.catalog_dir
    brave = httpx.MockTransport(lambda r: httpx.Response(200, json={"web": {"results": [{"title": "B", "url": "https://b.example", "description": "brave"}]}}))
    serper = httpx.MockTransport(lambda r: httpx.Response(200, json={"organic": [{"title": "S", "link": "https://s.example", "snippet": "serper"}]}))
    hits = build_adapter(catalog.provider(t, "brave-search"), secret="k", transport=brave).search("q", 3)
    assert [(h.title, h.url, h.snippet) for h in hits] == [("B", "https://b.example", "brave")]
    hits = build_adapter(catalog.provider(t, "serper"), secret="k", transport=serper).search("q", 3)
    assert hits[0].url == "https://s.example"
    bad = httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [{"title": "x", "url": "javascript:alert(1)", "content": "y"}]}))
    assert build_adapter(catalog.provider(t, "tavily"), secret="k", transport=bad).search("q") == []


def test_search_connection_is_a_tool_not_an_ai_employee(signed_in, http):
    calls = []
    _tavily(http, calls)
    res = signed_in.post("/providers/connections", json={"catalog_id": "tavily", "auth_type": "api_key", "api_key": "tvly-test-1234567890"}, headers=CSRF)
    assert res.json()["status"] == "online" and len(calls) == 1  # verified with one real query
    bad = signed_in.post("/providers/connections", json={"catalog_id": "serper", "auth_type": "api_key", "api_key": "wrong"}, headers=CSRF)
    assert bad.json()["status"] != "online"
    f = get_factory(signed_in.app)
    with db.transaction() as conn:
        user_id = signed_in.get("/auth/me").json()["id"]
        assert f.employees(conn, user_id) == []  # never routed chat tasks
        assert f.search_tool(conn, user_id) is not None


def test_market_research_grounds_the_ideation_room(signed_in, http):
    calls = []
    _tavily(http, calls)
    studio = _setup(signed_in, http)
    signed_in.post("/providers/connections", json={"catalog_id": "tavily", "auth_type": "api_key", "api_key": "tvly-test-1234567890"}, headers=CSRF)
    project_id = signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF).json()["id"]
    project = next(p for p in signed_in.get("/state").json()["projects"] if p["id"] == project_id)
    research = project["research"]
    assert project["status"] == "ready"
    assert len(research["queries"]) == 4 and len(calls) == 1 + 4
    assert research["brief"]["summary"].startswith("좀비 생존물") and research["analyst"]
    assert research["brief"]["references"][0]["url"] == "https://news.example.com/zombie-0"
    invent = [p for p in studio.prompts if "distinct game concepts" in p]
    assert all("live web search" in p and "기지 방어" in p for p in invent)
    assert any("Market research" in p for p in studio.prompts if "Score every concept" in p)
    ideas = signed_in.get(f"/projects/{project_id}/ideas").json()
    assert all(i["concept"]["research"] for i in ideas)
    # the brief also reaches production tasks
    line_id = signed_in.get("/lines").json()[0]["id"]
    signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
    assert any("# Market research (web search brief" in p for p in studio.prompts)
    logs = [l["type"] for l in signed_in.get("/logs").json()]
    assert "RESEARCH" in logs


def test_all_connected_ais_share_the_work_and_a_new_one_is_used_at_once(signed_in, http):
    _setup(signed_in, http)  # groq + gemini
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    for _ in range(4):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
    workers = Counter(t["assignee"]["name"] for s in signed_in.get(f"/lines/{line_id}").json()["stages"].values() for t in s["tasks"] if t["assignee"])
    assert {"Groq Fast Worker", "Gemini Planner"} <= set(workers)

    # an AI connected in the middle of production gets the next assignments
    http.add("GET", "api.mistral.ai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "mistral-small-latest"}]}))
    assert signed_in.post("/providers/connections", json={"catalog_id": "mistral", "auth_type": "api_key", "api_key": "mistral-key-1234567890"},
                          headers=CSRF).json()["status"] == "online"
    signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
    after = Counter(t["assignee"]["name"] for s in signed_in.get(f"/lines/{line_id}").json()["stages"].values() for t in s["tasks"] if t["assignee"])
    mistral = _entry(signed_in, "mistral")["name"]
    assert mistral not in workers and after[mistral] >= 1


def test_paid_adapters_speak_their_apis(client):
    seen = []

    def anthropic(req):
        seen.append(req)
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}]})
        body = json.loads(req.content)
        assert req.headers["x-api-key"] == "sk-ant-x" and req.headers["anthropic-version"]
        assert body["system"] == "sys" and body["messages"][0]["content"] == "hi"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hello"}], "usage": {"input_tokens": 3, "output_tokens": 2}, "model": body["model"]})

    a = build_adapter(_entry(client, "anthropic"), secret="sk-ant-x", transport=httpx.MockTransport(anthropic))
    assert a.list_models() == ["claude-sonnet-5"]
    out = a.execute(ExecuteRequest(prompt="hi", system="sys"))
    assert out.text == "hello" and out.usage.total_tokens == 5

    bodies = []

    def openai(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    o = build_adapter(_entry(client, "openai"), secret="sk-x", model="gpt-5", transport=httpx.MockTransport(openai))
    o.execute(ExecuteRequest(prompt="p", max_tokens=1000))
    assert "max_tokens" not in bodies[0] and "temperature" not in bodies[0] and bodies[0]["max_completion_tokens"] == 9000


def test_paid_provider_connects_with_a_chosen_model(signed_in, http):
    http.add("GET", "api.openai.com/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "gpt-5"}, {"id": "gpt-4.1"}, {"id": "dall-e-3"}]}))
    res = signed_in.post("/providers/connections", json={"catalog_id": "openai", "auth_type": "api_key", "api_key": "sk-test-1234567890", "model": "gpt-4.1"},
                         headers=CSRF).json()
    assert res["status"] == "online" and res["model"] == "gpt-4.1"
    providers = json.loads((signed_in.app.state.settings.catalog_dir / "providers.json").read_text(encoding="utf-8"))["providers"]
    paid = [p for p in providers if not p["free"]]
    assert {"openai", "anthropic", "xai", "deepseek", "gemini-pro", "openrouter-paid"} <= {p["id"] for p in paid}
    assert all("paid" in p["categories"] and p["adapter_status"] == "available" for p in paid)


def test_a_diff_reply_is_applied_to_the_current_game():
    game = "<!doctype html>\n<body data-ai-factory-game=\"v2\">\n<script>\nfunction startGame(){\n  let speed = 5;\n  go(speed);\n}\n</script>\n</body>\n"
    diff = "notes\n```diff\n--- a/index.html\n+++ b/index.html\n@@ -3,4 +3,4 @@\n function startGame(){\n-  let speed = 5;\n+  let speed = 3;\n   go(speed);\n```"
    assert "let speed = 3;" in games.apply_patch(game, diff)
    wrong = "```diff\n@@ -1 +1 @@\n-  let speed = 99;\n+  let speed = 1;\n```"
    assert games.apply_patch(game, wrong) is None  # a hunk that does not match is never half-applied


def test_ideation_room_runs_in_the_background(signed_in, http):
    _setup(signed_in, http)
    f = get_factory(signed_in.app)
    user_id = signed_in.get("/auth/me").json()["id"]
    jobs = []
    start = f._start_ideation
    f._start_ideation = lambda *a: jobs.append(start(*a)) or jobs[-1]
    f.background_ideation = True
    try:
        with db.transaction() as conn:
            project_id = f.create_project(conn, user_id, topic="좀비")
        assert signed_in.get("/state").json()["projects"][0]["status"] in ("ideating", "ready")
        jobs[0].join(timeout=60)
    finally:
        del f._start_ideation
    project = next(p for p in signed_in.get("/state").json()["projects"] if p["id"] == project_id)
    assert project["status"] == "ready"
    assert len(signed_in.get(f"/projects/{project_id}/ideas").json()) == 10
