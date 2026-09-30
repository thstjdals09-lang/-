"""Idea generation and scoring. Bit-for-bit compatible with generateIdeas in docs/js/engine.js
(same FNV-1a seed, same mulberry32 stream), so a topic yields the same portfolio in the browser
preview and on the server."""

from __future__ import annotations

import math
import re

M32 = 0xFFFFFFFF


def fnv1a(value: str) -> int:
    h = 2166136261
    for ch in str(value):
        h = ((h ^ ord(ch)) * 16777619) & M32
    return h


def mulberry32(seed: int):
    a = seed & M32

    def rng() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & M32
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & M32
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & M32)) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return rng


def js_round(x: float) -> int:
    return math.floor(x + 0.5)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", str(value or "").lower()).strip("-")[:40]
    return slug or "item"


def game_family(game_type: str) -> str:
    if re.search(r"Tycoon|Management", game_type):
        return "management"
    if re.search(r"Roguelike|Survivor|Extraction|Arcade", game_type):
        return "action"
    return "strategy"


def generate_ideas(topic: str, genre: str, platform: str, studio: dict) -> list[dict]:
    rng = mulberry32(fnv1a(f"{topic}|{genre}|{platform}"))
    criteria = studio["idea_criteria"]
    ideas = []
    for pattern in studio["idea_patterns"]:
        metrics = {}
        for c in criteria:
            base = 62 + math.floor(rng() * 30)
            metrics[c["id"]] = max(35, min(99, base + pattern["bias"].get(c["id"], 0)))
        if genre and genre != "자동선택" and genre.lower() in pattern["type"].lower():
            metrics["fun"] = min(99, metrics["fun"] + 6)
            metrics["market"] = min(99, metrics["market"] + 4)
        # Plain left-to-right addition like JS reduce (Python 3.12's sum() compensates rounding).
        total = 0.0
        for c in criteria:
            total += metrics[c["id"]] * c["weight"]
        score = js_round(total * 10) / 10
        reviews = []
        for r in studio["idea_reviewers"]:
            avg = js_round(sum(int(metrics[k]) for k in r["focus"]) / len(r["focus"]))
            weakest = sorted(r["focus"], key=lambda k: metrics[k])[0]
            label = next(c["label"] for c in criteria if c["id"] == weakest)
            reviews.append({
                "role": r["role"],
                "score": avg,
                "verdict": "강력 추천" if avg >= 80 else "조건부 추천" if avg >= 70 else "보류",
                "note": f"{label}까지 안정적입니다." if avg >= 80 else f"{label} 보완이 필요합니다.",
            })
        ideas.append({
            "title": f"{topic} · {pattern['type']}",
            "type": pattern["type"],
            "family": pattern.get("family") or game_family(pattern["type"]),
            "pitch": f"{topic}를 {pattern['pitch']}",
            "loop": list(pattern["loop"]),
            "metrics": metrics,
            "score": score,
            "reviews": reviews,
        })
    ideas.sort(key=lambda i: -i["score"])
    for rank, idea in enumerate(ideas, start=1):
        idea["rank"] = rank
    return ideas
