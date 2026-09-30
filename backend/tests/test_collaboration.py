"""Multi-AI collaboration: AI ideation + cross-scoring, design dossier to code, reviews and judges
that send work back, and a game written from scratch (no template)."""

import json
import re

import httpx

from .conftest import CSRF

def concepts(n, call=0):
    return [{"title": f"좀비 콘셉트 {call}-{i}", "type": f"Genre{i}", "family": ["strategy", "action", "management"][i % 3],
             "pitch": f"피치 {i}", "loop": ["a", "b", "c", "d"], "mechanics": [f"mechanic-{i}-x", f"mechanic-{i}-y"],
             "why_fun": f"fun-{i}", "market_fit": f"fit-{i}", "scope": f"scope-{i}"} for i in range(n)]


BRIEF = {"summary": "좀비 생존물은 짧은 세션과 기지 운영이 인기", "trends": ["기지 방어 [0]"], "popular_mechanics": ["웨이브 방어 [1]"],
         "pain_points": ["반복적인 파밍 [0]"], "saturated": ["뱀서류 재탕"], "opportunities": ["협상·거래"], "references": [{"idx": 0, "why": "참고"}]}


class Studio:
    """Answers like a small team of models, keyed on what each prompt asks for."""

    def __init__(self):
        self.prompts: list[str] = []
        self.review_calls = 0
        self.fun_calls = 0
        self.images = 0
        self.invent_calls = 0

    def respond(self, prompt: str) -> str:
        self.prompts.append(prompt)
        m = re.search(r"Invent (\d+) distinct game concepts", prompt)
        if m:
            self.invent_calls += 1
            return "```json\n" + json.dumps(concepts(int(m.group(1)), self.invent_calls), ensure_ascii=False) + "\n```"
        if "# Web search results" in prompt:
            return json.dumps(BRIEF, ensure_ascii=False)
        if "# Rebuttal round" in prompt:
            return json.dumps([{"idx": int(i), "rebuttal": "반론-" + i, "revision": ["수정-" + i]} for i in re.findall(r"^\[(\d+)\]", prompt, re.M)])
        if "# Consensus round" in prompt:
            return json.dumps([{"idx": int(i), "decision": "go", "consensus": "합의-" + i, "final_mechanics": ["final-" + i], "risks": ["위험"]}
                               for i in re.findall(r"^\[(\d+)\]", prompt, re.M)])
        if "Score every concept" in prompt:
            bias = len(self.prompts) % 7
            scores = [{"idx": i, **{k: 50 + (i * 5 + bias) % 50 for k in ("fun", "coreLoop", "cost", "schedule", "novelty", "feasibility", "market", "scalability", "risk")},
                       "note": f"note-{i}"} for i in range(10)]
            return json.dumps({"scores": scores})
        if "# Game deliverable" in prompt:
            marker = "FROM-SCRATCH" if "No game exists yet" in prompt else "IMPROVED"
            return ("notes\n```html\n<!doctype html><html><body data-ai-factory-game=\"v2\"><h1>" + marker +
                    "</h1><script>function startGame(){}</script></body></html>\n```")
        if "코드 리뷰" in prompt:
            self.review_calls += 1
            return "missing restart button\nRESULT: FAIL" if self.review_calls == 1 else "looks good\nRESULT: PASS"
        if "재미 검증 리뷰" in prompt and "You are a gate" in prompt:
            self.fun_calls += 1
            return "core loop is not fun: no risk\nRESULT: FAIL" if self.fun_calls == 1 else "fun now\nRESULT: PASS"
        return "artifact body\nRESULT: PASS"

    def openai(self, req: httpx.Request):
        content = json.loads(req.content)["messages"][-1]["content"]
        if isinstance(content, list):
            self.images += sum(1 for p in content if p.get("type") == "image_url")
            content = next(p["text"] for p in content if p.get("type") == "text")
        return httpx.Response(200, json={"choices": [{"message": {"content": self.respond(content)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10}})

    def gemini(self, req: httpx.Request):
        parts = json.loads(req.content)["contents"][0]["parts"]
        self.images += sum(1 for p in parts if "inline_data" in p)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": self.respond(parts[0]["text"])}]}}],
                                         "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 5}})


def _setup(signed_in, http):
    studio = Studio()
    http.add("GET", "api.groq.com/openai/v1/models", lambda r: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    http.add("GET", "generativelanguage.googleapis.com/v1beta/models", lambda r: httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash"}]}))
    http.add("POST", "chat/completions", studio.openai)
    http.add("POST", ":generateContent", studio.gemini)
    for provider in ("groq", "gemini"):
        res = signed_in.post("/providers/connections", json={"catalog_id": provider, "auth_type": "api_key", "api_key": provider + "-key-1234567890"}, headers=CSRF)
        assert res.json()["status"] == "online"
    return studio


def test_ai_ideation_invents_critiques_debates_and_agrees(signed_in, http):
    studio = _setup(signed_in, http)
    project = signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF).json()["id"]
    ideas = signed_in.get(f"/projects/{project}/ideas").json()
    assert len(ideas) == 10
    # two different AIs invented concepts; the second was told what the first already proposed
    assert {i["concept"]["creator"] for i in ideas} == {"Groq Fast Worker", "Gemini Planner"}
    invent = [p for p in studio.prompts if "distinct game concepts" in p]
    assert len(invent) == 2 and "already proposed" in invent[1]
    reviewers = {r["reviewer"] for i in ideas for r in i["reviews"]}
    assert reviewers == {"Groq Fast Worker", "Gemini Planner"}  # critique spread across different AIs
    assert [i["score"] for i in ideas] == sorted((i["score"] for i in ideas), reverse=True)
    # authors answered their critiques and a moderator recorded the consensus production follows
    top = [i for i in ideas if i["concept"].get("consensus")]
    assert len(top) == 5
    assert all(i["concept"]["rebuttal"].startswith("반론") and i["concept"]["mechanics"][0].startswith("final-") for i in top)
    assert all(i["concept"]["original_mechanics"] for i in top)
    logs = [l["type"] for l in signed_in.get("/logs").json()]
    assert "IDEATION" in logs and logs.count("CRITIQUE") == 4 and "DEBATE" in logs and "CONSENSUS" in logs
    assert sum("Score every concept" in p for p in studio.prompts) == 4
    # no search API: the room is told it has no live research
    assert all("no web search connected" in p for p in invent)


def test_unparseable_creator_is_replaced_by_another_ai(signed_in, http):
    studio = _setup(signed_in, http)
    original = studio.respond

    def broken_first(prompt):
        if "distinct game concepts" in prompt and studio.invent_calls == 0:
            studio.invent_calls += 1
            studio.prompts.append(prompt)
            return "sorry, here are some ideas in prose"
        return original(prompt)

    studio.respond = broken_first
    project = signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF).json()["id"]
    ideas = signed_in.get(f"/projects/{project}/ideas").json()
    assert len(ideas) >= 3 and all(i["concept"] for i in ideas)  # not the offline pattern generator
    logs = [l["text"] for l in signed_in.get("/logs").json()]
    assert any("다른 AI에게 발상 요청" in t for t in logs)
    assert not any("오프라인" in t for t in logs)


def test_design_flows_into_code_reviews_and_judges_send_work_back(signed_in, http):
    studio = _setup(signed_in, http)
    signed_in.post("/projects", json={"topic": "좀비"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    for _ in range(60):
        signed_in.post(f"/lines/{line_id}/tick", headers=CSRF)
        detail = signed_in.get(f"/lines/{line_id}").json()
        if detail["builds"]:
            break

    # the first game-writing prompt starts from scratch with the design dossier and the room's consensus
    first_game = next(p for p in studio.prompts if "# Game deliverable" in p)
    assert "# Design dossier" in first_game and "GDD.md" in first_game and "# Concept" in first_game
    assert "Room consensus" in first_game and "never a diff" in first_game
    assert "No game exists yet" in first_game and "코어를 회수" not in first_game and "# Current game source" not in first_game
    # the core-loop programmer builds on the AI's game with the same dossier
    core = next(p for p in studio.prompts if "핵심 루프 구현" in p and "# Game deliverable" in p)
    assert "# Design dossier" in core and "GDD.md" in core

    # code review rejection became a fix task that received the review notes
    logs = [l["type"] for l in signed_in.get("/logs").json()]
    assert "REVIEW REJECT" in logs
    assert any("missing restart button" in p and "자동 수정" in p for p in studio.prompts)

    # a failing judge (fun review) sent the game back for a revision with its notes
    assert "JUDGE FAIL" in logs
    proto = detail["stages"]["prototype"]["tasks"]
    assert {"fun-fix1", "fun-retest1"} <= {t["id"] for t in proto}
    assert any("core loop is not fun" in p for p in studio.prompts if "자동 수정: 재미 검증 리뷰" in p)

    # the playable build is the AI-written game, not a template
    build = detail["builds"][0]
    html = signed_in.get(f"/builds/{build['id']}/play").text
    assert "FROM-SCRATCH" in html or "IMPROVED" in html
    assert "TEMPLATE FALLBACK" not in logs
