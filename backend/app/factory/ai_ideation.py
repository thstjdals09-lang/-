"""AI ideation room: one AI invents concepts for the topic, several other AIs score and critique them.

Returns None when no real provider can take the work, so the caller falls back to the offline
pattern generator (ideation.generate_ideas). Nothing here is templated per genre: titles, loops,
mechanics and the fun hypothesis come from the models.
"""

from __future__ import annotations

import json
import re

from .. import routing, vault
from ..providers import AdapterUnavailable, ExecuteRequest, ProviderError
from .executor import Attempt

FAMILIES = ("strategy", "action", "management")


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


def concept_prompt(topic: str, genre: str, platform: str, notes: str, count: int) -> ExecuteRequest:
    system = ("You are the Creative Director of an indie game studio running an ideation room. "
              "Invent genuinely different games, not reskins of one template. Answer with JSON only.")
    prompt = (
        f"Theme from the CEO: {topic}\nPreferred genre: {genre}\nPlatform: {platform}\nNotes: {notes or '(none)'}\n\n"
        f"Invent {count} distinct game concepts for this theme. They must differ in core verb, structure and fantasy "
        "(mix real-time, turn-based, puzzle, management, social/bluff, narrative, rhythm, physics, etc. as fits the theme). "
        "Each must be buildable as a single-file HTML5 browser game by a small team.\n\n"
        "Return a JSON array. Each item:\n"
        '{"title": "Korean game title", "type": "short genre label", "family": "strategy|action|management (closest)", '
        '"pitch": "one Korean sentence", "loop": ["4-6 Korean core-loop steps"], "mechanics": ["3-5 concrete mechanics"], '
        '"why_fun": "Korean fun hypothesis", "scope": "what the first playable must contain"}'
    )
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=5000, temperature=0.9)


def critique_prompt(role: str, focus: list[str], criteria: list[dict], concepts: list[dict]) -> ExecuteRequest:
    listing = "\n".join(f"{i}. {c['title']} ({c['type']}): {c['pitch']} | loop: {' → '.join(c['loop'])} | mechanics: {', '.join(c['mechanics'])}"
                        for i, c in enumerate(concepts))
    crit = ", ".join(f"{c['id']} ({c['label']})" for c in criteria)
    system = f"You are the studio's {role}. Score concepts honestly from your discipline's point of view; do not inflate. Answer with JSON only."
    prompt = (
        f"Concepts:\n{listing}\n\nScore every concept 0-100 on: {crit}. For cost, schedule, feasibility and risk a HIGH score means "
        f"cheap / fast / easy / safe. Your focus: {', '.join(focus)}.\n"
        'Return JSON: {"scores": [{"idx": 0, "fun": 80, ..., "note": "one Korean sentence: the biggest strength or problem"}]}'
    )
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=4000, temperature=0.3)


def _normalise(raw) -> list[dict]:
    items = raw if isinstance(raw, list) else (raw or {}).get("concepts") if isinstance(raw, dict) else None
    out = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        loop = [str(x) for x in (item.get("loop") or []) if str(x).strip()][:6] or ["관찰", "선택", "결과", "성장"]
        family = str(item.get("family", "")).lower()
        out.append({
            "title": str(item["title"])[:60],
            "type": str(item.get("type") or "Original")[:40],
            "family": family if family in FAMILIES else "strategy",
            "pitch": str(item.get("pitch") or "")[:300],
            "loop": loop,
            "mechanics": [str(x)[:120] for x in (item.get("mechanics") or [])][:5],
            "why_fun": str(item.get("why_fun") or "")[:300],
            "scope": str(item.get("scope") or "")[:300],
        })
    return out


def ideate(factory, conn, user_id: str, *, topic: str, genre: str, platform: str, notes: str, studio: dict, count: int = 10) -> list[dict] | None:
    """Concepts from one AI, scores from the reviewer roles. None when only the simulator is available."""
    policy = factory.user_settings(conn, user_id)["policy"]
    team = factory.employees(conn, user_id)
    if not any(e.status == "online" for e, _, _ in team):
        return None

    def ask(request: ExecuteRequest, kind: str, difficulty: int, used: dict[str, int]) -> tuple[str, str, str] | None:
        """Routes one call, preferring the least-used AIs so critiques come from different models,
        with failover and quota accounting."""
        rtask = routing.Task(kind=kind, difficulty=difficulty, critical=True)
        decision = routing.route(rtask, [e for e, _, _ in team], policy=policy)
        rank = {c.employee.id: i for i, c in enumerate(decision.ordered)}
        ordered = sorted(decision.ordered, key=lambda c: (used.get(c.employee.id, 0), rank[c.employee.id]))
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
            return result.text, c.employee.id, c.employee.name
        if attempts:
            factory._record_attempts(conn, user_id, None, None, attempts, rtask)
        return None

    conn.commit()
    used: dict[str, int] = {}
    got = ask(concept_prompt(topic, genre, platform, notes, count), "planning", 3, used)
    if got is None:
        return None
    text, creator_id, creator = got
    used[creator_id] = 1
    concepts = _normalise(_json_block(text))
    if len(concepts) < 3:
        factory.log(conn, user_id, "IDEATION", f"{creator} 발상 결과를 해석하지 못함 → 오프라인 아이디어 생성으로 대체")
        return None
    factory.log(conn, user_id, "IDEATION", f"{topic} · {creator}가 새 콘셉트 {len(concepts)}개 발상")

    criteria = studio["idea_criteria"]
    sheets: list[tuple[str, str, list[str], dict]] = []  # role, reviewer AI, focus, scores by idx
    for reviewer in studio["idea_reviewers"]:
        got = ask(critique_prompt(reviewer["role"], reviewer["focus"], criteria, concepts), "planning", 2, used)
        if got is None:
            continue
        text, rid, rname = got
        used[rid] = used.get(rid, 0) + 1
        parsed = _json_block(text)
        rows = parsed.get("scores") if isinstance(parsed, dict) else parsed
        by_idx = {}
        for row in rows or []:
            if isinstance(row, dict) and isinstance(row.get("idx"), (int, float)) and 0 <= int(row["idx"]) < len(concepts):
                by_idx[int(row["idx"])] = row
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
            "concept": {"mechanics": concept["mechanics"], "why_fun": concept["why_fun"], "scope": concept["scope"], "creator": creator},
        })
    ideas.sort(key=lambda x: -x["score"])
    for rank, idea in enumerate(ideas, start=1):
        idea["rank"] = rank
    return ideas
