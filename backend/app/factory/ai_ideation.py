"""AI ideation room: several AIs invent concepts for the topic (grounded in web market research when a
search API is connected), other AIs critique and score them, the authors answer the critiques, and a
moderator AI records the consensus that production follows.

Returns None when no real provider can take the work, so the caller falls back to the offline
pattern generator (ideation.generate_ideas). Nothing here is templated per genre: titles, loops,
mechanics and the fun hypothesis come from the models.
"""

from __future__ import annotations

import json
import math
import re

from .. import routing, vault
from ..providers import AdapterUnavailable, ExecuteRequest, ProviderError
from . import research as market
from .executor import Attempt

FAMILIES = ("strategy", "action", "management")
APP_FAMILY = "app"  # programs that are not games (tools, utilities, apps)
CREATORS = 2  # different AIs inventing concepts (another AI steps in when one answers unusable JSON)
DEBATE_TOP = 5  # concepts that go through rebuttal + consensus


def _json_block(text: str):
    """First JSON array/object in a model reply (code fences and prose tolerated)."""
    fence = re.search(r"```(?:json)?\s*\n(.*?)```", text or "", re.S)
    body = fence.group(1) if fence else (text or "")
    for opener, closer in (("[", "]"), ("{", "}")):
        start = body.find(opener)
        end = body.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(body[start:end + 1])
            except ValueError:
                continue
    return None


def _clamp(value, lo=0, hi=100, default=60) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _key(title: str) -> str:
    return re.sub(r"\W+", "", str(title).lower())


def _research_block(research_text: str) -> str:
    if not research_text:
        return "# Market research\n(no web search connected: rely on your own knowledge and say where it may be outdated)\n\n"
    return f"# Market research (summarised from live web search — use it)\n{research_text}\n\n"


def app_concept_prompt(topic: str, platform: str, notes: str, count: int, research_text: str = "", taken: list[str] | None = None) -> ExecuteRequest:
    system = ("You are a Product Lead in a small software studio's ideation room. The product is a program people use to get "
              "something done (an app, tool or utility) — NOT a game. Invent genuinely different products, not one template "
              "with different labels. Answer with JSON only.")
    others = ""
    if taken:
        others = ("Others in the room already proposed these — yours must solve the need in a different way:\n"
                  + "\n".join(f"- {t}" for t in taken) + "\n\n")
    prompt = (
        f"Theme from the CEO: {topic}\nPlatform: {platform}\nNotes: {notes or '(none)'}\n\n"
        f"{_research_block(research_text)}{others}"
        f"Invent {count} distinct program concepts for this theme. They must differ in who uses them, the job they do and how the "
        "user works with them (calculator, tracker, planner, editor, generator, converter, dashboard, simulator, trainer, organizer, "
        "etc. as fits the theme). Use the market research: keep features that work, answer the user pain points, avoid saturated ideas. "
        "Each must be buildable as a single-file HTML program that runs offline in a browser, with no server and no accounts.\n\n"
        "Return a JSON array. Each item:\n"
        '{"title": "Korean product name", "type": "short product label", "family": "app", '
        '"pitch": "one Korean sentence", "loop": ["4-6 Korean steps of the main user flow"], "mechanics": ["3-5 concrete features"], '
        '"why_fun": "Korean: why people would keep using it", "market_fit": "Korean: which need/pain point this answers", '
        '"scope": "what the first usable version must contain"}'
    )
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=5000, temperature=0.9)


def concept_prompt(topic: str, genre: str, platform: str, notes: str, count: int, research_text: str = "", taken: list[str] | None = None,
                   kind: str = "game") -> ExecuteRequest:
    if kind == "app":
        return app_concept_prompt(topic, platform, notes, count, research_text, taken)
    system = ("You are a Creative Director in an indie game studio's ideation room. "
              "Invent genuinely different games, not reskins of one template. Answer with JSON only.")
    others = ""
    if taken:
        others = ("Other designers in the room already proposed these — yours must use different core verbs and structures:\n"
                  + "\n".join(f"- {t}" for t in taken) + "\n\n")
    prompt = (
        f"Theme from the CEO: {topic}\nPreferred genre: {genre}\nPlatform: {platform}\nNotes: {notes or '(none)'}\n\n"
        f"{_research_block(research_text)}{others}"
        f"Invent {count} distinct game concepts for this theme. They must differ in core verb, structure and fantasy "
        "(mix real-time, turn-based, puzzle, management, social/bluff, narrative, rhythm, physics, etc. as fits the theme). "
        "Use the market research: build on mechanics that work, answer the player pain points, avoid the saturated ideas. "
        "Each must be buildable as a single-file HTML5 browser game by a small team.\n\n"
        "Return a JSON array. Each item:\n"
        '{"title": "Korean game title", "type": "short genre label", "family": "strategy|action|management (closest)", '
        '"pitch": "one Korean sentence", "loop": ["4-6 Korean core-loop steps"], "mechanics": ["3-5 concrete mechanics"], '
        '"why_fun": "Korean fun hypothesis", "market_fit": "Korean: which trend/pain point this answers", '
        '"scope": "what the first playable must contain"}'
    )
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=5000, temperature=0.9)


def _listing(concepts: list[dict]) -> str:
    return "\n".join(f"{i}. {c['title']} ({c['type']}): {c['pitch']} | loop: {' → '.join(c['loop'])} | mechanics: {', '.join(c['mechanics'])}"
                     + (f" | market fit: {c['market_fit']}" if c.get("market_fit") else "")
                     for i, c in enumerate(concepts))


def critique_prompt(role: str, focus: list[str], criteria: list[dict], concepts: list[dict], research_text: str = "", kind: str = "game") -> ExecuteRequest:
    crit = ", ".join(f"{c['id']} ({c['label']})" for c in criteria)
    app_note = ("These are programs (apps/tools), not games: read `fun` as how useful and pleasant it is to use, and `coreLoop` "
                "as how clear the main user flow is. " if kind == "app" else "")
    system = f"You are the studio's {role}. Score concepts honestly from your discipline's point of view; do not inflate. Answer with JSON only."
    prompt = (
        f"{_research_block(research_text)}Concepts:\n{_listing(concepts)}\n\nScore every concept 0-100 on: {crit}. For cost, schedule, feasibility and risk a HIGH score means "
        f"cheap / fast / easy / safe. {app_note}Judge market and novelty against the research (a reskin of a saturated idea scores low). Your focus: {', '.join(focus)}.\n"
        'Return JSON: {"scores": [{"idx": 0, "fun": 80, ..., "note": "one Korean sentence: the biggest strength or problem"}]}'
    )
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=4000, temperature=0.3)


def _notes(reviews: list[dict]) -> str:
    return "\n".join(f"  - {r['role']} ({r.get('reviewer', '')}, {r['score']}): {r['note']}" for r in reviews) or "  - (no notes)"


def rebuttal_prompt(items: list[tuple[int, dict]]) -> ExecuteRequest:
    blocks = [f"[{i}] {idea['title']} ({idea['type']}): {idea['pitch']}\n  mechanics: {', '.join(idea['concept']['mechanics'])}\n"
              f"  critiques:\n{_notes(idea['reviews'])}" for i, idea in items]
    system = ("You proposed these game concepts and the studio's reviewers critiqued them. Defend what is right, concede what is "
              "wrong, and revise the design concretely. Answer with JSON only.")
    prompt = ("# Rebuttal round\n" + "\n\n".join(blocks) + "\n\nReturn JSON: "
              '[{"idx": 0, "rebuttal": "Korean: your answer to the critiques", "revision": ["concrete design change"]}]')
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=2500, temperature=0.4)


def consensus_prompt(items: list[tuple[int, dict]], research_text: str) -> ExecuteRequest:
    blocks = []
    for i, idea in items:
        c = idea["concept"]
        blocks.append(
            f"[{i}] {idea['title']} ({idea['type']}), score {idea['score']}\n  pitch: {idea['pitch']}\n  mechanics: {', '.join(c['mechanics'])}\n"
            f"  critiques:\n{_notes(idea['reviews'])}\n  author's answer: {c.get('rebuttal') or '(none)'}\n"
            f"  author's revision: {'; '.join(c.get('revision') or []) or '(none)'}"
        )
    system = ("You are the Producer chairing the ideation room. Weigh the critiques against the authors' answers and the market "
              "research, then record the decision the production team will follow. Answer with JSON only.")
    prompt = (
        f"# Consensus round\n{_research_block(research_text)}" + "\n\n".join(blocks) + "\n\nReturn JSON: "
        '[{"idx": 0, "decision": "go|revise|drop", "consensus": "Korean: what the room agreed and why", '
        '"final_mechanics": ["3-5 mechanics production must build"], "risks": ["Korean risk to watch"]}]'
    )
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=3000, temperature=0.3)


def _normalise(raw, kind: str = "game") -> list[dict]:
    items = raw if isinstance(raw, list) else (raw or {}).get("concepts") if isinstance(raw, dict) else None
    out, seen = [], set()
    for item in items or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        key = _key(item["title"])
        if key in seen:  # models sometimes repeat a concept under the same name
            continue
        seen.add(key)
        loop = [str(x) for x in (item.get("loop") or []) if str(x).strip()][:6] or ["관찰", "선택", "결과", "성장"]
        family = str(item.get("family", "")).lower()
        out.append({
            "title": str(item["title"])[:60],
            "type": str(item.get("type") or "Original")[:40],
            "family": APP_FAMILY if kind == "app" else family if family in FAMILIES else "strategy",
            "pitch": str(item.get("pitch") or "")[:300],
            "loop": loop,
            "mechanics": [str(x)[:120] for x in (item.get("mechanics") or [])][:5],
            "why_fun": str(item.get("why_fun") or "")[:300],
            "market_fit": str(item.get("market_fit") or "")[:300],
            "scope": str(item.get("scope") or "")[:300],
        })
    return out


def _by_idx(rows) -> dict[int, dict]:
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("scores") or rows.get("decisions") or []
    return {int(r["idx"]): r for r in rows or [] if isinstance(r, dict) and isinstance(r.get("idx"), (int, float))}


def ideate(factory, conn, user_id: str, *, topic: str, genre: str, platform: str, notes: str, studio: dict, count: int = 10,
           research: dict | None = None, kind: str = "game") -> list[dict] | None:
    """Concepts from several AIs, scores from the reviewer roles, rebuttals and a consensus.
    None when only the simulator is available."""
    policy = factory.user_settings(conn, user_id)["policy"]
    team = factory.employees(conn, user_id)
    online = [e for e, _, _ in team if e.status == "online"]
    if not online:
        return None
    research_text = market.as_text(research)

    def ask(request: ExecuteRequest, kind: str, difficulty: int, used: dict[str, int], *, only: str | None = None,
            exclude=frozenset()) -> tuple[str, str, str] | None:
        """Routes one call, preferring the least-used AIs so the room hears different models,
        with failover and quota accounting."""
        rtask = routing.Task(kind=kind, difficulty=difficulty, critical=True)
        decision = routing.route(rtask, [e for e, _, _ in team], policy=policy)
        rank = {c.employee.id: i for i, c in enumerate(decision.ordered)}
        ordered = sorted(decision.ordered, key=lambda c: (used.get(c.employee.id, 0), rank[c.employee.id]))
        ordered = [c for c in ordered if c.employee.id not in exclude and (only is None or c.employee.id == only)]
        by_id = {e.id: (row, entry) for e, row, entry in team}
        attempts: list[Attempt] = []
        for c in ordered:
            row, entry = by_id[c.employee.id]
            try:
                adapter = factory._adapter(conn, user_id, row, entry)
            except (AdapterUnavailable, vault.VaultError, ValueError):
                continue
            try:
                result = adapter.execute(request)
            except ProviderError as exc:
                attempts.append(Attempt(c.employee.id, c.employee.name, False, exc.info.kind))
                continue
            attempts.append(Attempt(c.employee.id, c.employee.name, True, None, result.usage.total_tokens, result.latency_ms))
            factory._record_attempts(conn, user_id, None, None, attempts, rtask)
            used[c.employee.id] = used.get(c.employee.id, 0) + 1
            return result.text, c.employee.id, c.employee.name
        if attempts:
            factory._record_attempts(conn, user_id, None, None, attempts, rtask)
        return None

    conn.commit()
    used: dict[str, int] = {}

    # 1. several AIs invent concepts; an AI whose answer cannot be parsed is replaced by another
    target = min(CREATORS, len(online))
    per = math.ceil(count / target) + (1 if target > 1 else 0)
    concepts: list[dict] = []
    creators: dict[str, str] = {}  # creator name → employee id
    tried: set[str] = set()
    while len(creators) < target and len(tried) < len(online):
        taken = [f"{c['title']} ({c['type']}): {c['pitch']}" for c in concepts]
        got = ask(concept_prompt(topic, genre, platform, notes, per, research_text, taken, kind), "planning", 3, used, exclude=tried)
        if got is None:
            break
        text, cid, cname = got
        tried.add(cid)
        have = {_key(c["title"]) for c in concepts}
        found = [c for c in _normalise(_json_block(text), kind) if _key(c["title"]) not in have]
        if len(found) < 2:
            factory.log(conn, user_id, "IDEATION", f"{cname} 발상 결과를 해석하지 못함 → 다른 AI에게 발상 요청")
            continue
        for c in found:
            c["creator"], c["creator_id"] = cname, cid
        concepts += found
        creators[cname] = cid
        factory.log(conn, user_id, "IDEATION", f"{topic} · {cname}가 새 콘셉트 {len(found)}개 발상" + (" (시장 조사 반영)" if research_text else ""))
    if len(concepts) < 3:
        factory.log(conn, user_id, "IDEATION", "쓸 수 있는 AI 발상 결과가 없어 오프라인 아이디어 생성으로 대체")
        return None
    # interleave the authors so the list is not ordered by creator, then cap
    groups = [[c for c in concepts if c["creator_id"] == cid] for cid in creators.values()]
    concepts = [g[i] for i in range(max(map(len, groups))) for g in groups if i < len(g)][:count]

    # 2. reviewers critique and score every concept
    criteria = studio["idea_criteria"]
    sheets: list[tuple[str, str, list[str], dict]] = []  # role, reviewer AI, focus, scores by idx
    for reviewer in studio["idea_reviewers"]:
        got = ask(critique_prompt(reviewer["role"], reviewer["focus"], criteria, concepts, research_text, kind), "planning", 2, used)
        if got is None:
            continue
        text, _, rname = got
        by_idx = {i: r for i, r in _by_idx(_json_block(text)).items() if 0 <= i < len(concepts)}
        if by_idx:
            sheets.append((reviewer["role"], rname, reviewer["focus"], by_idx))
            factory.log(conn, user_id, "CRITIQUE", f"{reviewer['role']} · {rname}가 콘셉트 {len(by_idx)}개 채점")
    if not sheets:
        factory.log(conn, user_id, "CRITIQUE", "채점 가능한 리뷰어 AI가 없어 기본 점수 사용")

    ideas = []
    for i, concept in enumerate(concepts):
        metrics = {}
        for c in criteria:
            vals = [_clamp(sheet[3][i].get(c["id"])) for sheet in sheets if i in sheet[3]]
            metrics[c["id"]] = round(sum(vals) / len(vals)) if vals else 60
        total = 0.0
        for c in criteria:
            total += metrics[c["id"]] * c["weight"]
        reviews = []
        for role, rname, focus, by_idx in sheets:
            row = by_idx.get(i)
            if not row:
                continue
            avg = round(sum(_clamp(row.get(k)) for k in focus) / len(focus))
            reviews.append({"role": role, "reviewer": rname, "score": avg,
                            "verdict": "강력 추천" if avg >= 80 else "조건부 추천" if avg >= 70 else "보류",
                            "note": str(row.get("note") or "")[:200]})
        ideas.append({
            "title": concept["title"], "type": concept["type"], "family": concept["family"], "pitch": concept["pitch"],
            "loop": concept["loop"], "metrics": metrics, "score": round(total * 10) / 10, "reviews": reviews,
            "concept": {"mechanics": concept["mechanics"], "why_fun": concept["why_fun"], "scope": concept["scope"],
                        "market_fit": concept["market_fit"], "creator": concept["creator"], "research": bool(research_text)},
            "_creator_id": concept["creator_id"],
        })
    ideas.sort(key=lambda x: -x["score"])
    top = list(enumerate(ideas[:DEBATE_TOP]))

    # 3. each author answers the critiques of its concepts in the top group
    if sheets:
        for cname, cid in creators.items():
            mine = [(i, idea) for i, idea in top if idea["_creator_id"] == cid]
            if not mine:
                continue
            got = ask(rebuttal_prompt(mine), "planning", 2, used, only=cid)
            if got is None:
                continue
            answers = _by_idx(_json_block(got[0]))
            for i, idea in mine:
                a = answers.get(i)
                if a:
                    idea["concept"]["rebuttal"] = str(a.get("rebuttal") or "")[:400]
                    idea["concept"]["revision"] = [str(x)[:160] for x in (a.get("revision") or [])][:4]
            factory.log(conn, user_id, "DEBATE", f"{cname} · 자기 콘셉트 {len(mine)}개에 대한 비평에 반론·수정안 제출")

    # 4. a moderator (not an author, when another AI is available) records the consensus
    if sheets and top:
        moderator_exclude = set(creators.values()) if len(online) > len(creators) else frozenset()
        got = ask(consensus_prompt(top, research_text), "planning", 3, used, exclude=moderator_exclude)
        if got is not None:
            decisions = _by_idx(_json_block(got[0]))
            for i, idea in top:
                d = decisions.get(i)
                if not d:
                    continue
                decision = str(d.get("decision") or "go").lower()
                decision = decision if decision in ("go", "revise", "drop") else "go"
                final = [str(x)[:120] for x in (d.get("final_mechanics") or [])][:5]
                if final:
                    idea["concept"]["original_mechanics"] = idea["concept"]["mechanics"]
                    idea["concept"]["mechanics"] = final
                idea["concept"].update(decision=decision, consensus=str(d.get("consensus") or "")[:500],
                                       risks=[str(x)[:160] for x in (d.get("risks") or [])][:4], moderator=got[2])
                if decision == "drop":
                    idea["score"] = round(max(0.0, idea["score"] - 15) * 10) / 10
            factory.log(conn, user_id, "CONSENSUS", f"{got[2]} 진행 · 상위 {len(top)}개 합의: " +
                        ", ".join(f"{idea['title']} {idea['concept'].get('decision', 'go').upper()}" for _, idea in top))

    ideas.sort(key=lambda x: -x["score"])
    for rank, idea in enumerate(ideas, start=1):
        idea["rank"] = rank
        idea.pop("_creator_id", None)
    return ideas
