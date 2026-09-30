"""Renders the shared HTML5 game templates (docs/catalog/games) exactly like docs/js/games.js."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .ideation import game_family


def _json_for_script(value: str) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False).replace("<", "\\u003c")


def render(catalog_dir: Path, *, title: str, topic: str, game_type: str, family: str | None = None) -> str:
    family = family or game_family(game_type)
    path = catalog_dir / "games" / f"{family}.html"
    if not path.exists():
        path = catalog_dir / "games" / "strategy.html"
    html = path.read_text(encoding="utf-8")
    for token, value in (("{{TITLE_JSON}}", title), ("{{TOPIC_JSON}}", topic), ("{{TYPE_JSON}}", game_type or family)):
        html = html.replace(token, _json_for_script(value), 1)
    return html


def smoke_test(html: str) -> dict:
    checks = [
        ("doctype", bool(re.search(r"<!doctype html>", html, re.I))),
        ("entry_point", "startGame" in html),
        ("factory_marker", 'data-ai-factory-game="v2"' in html),
        ("no_external_scripts", not re.search(r"<script[^>]+src=", html, re.I)),
        ("tokens_resolved", "{{" not in html),
    ]
    return {"passed": all(ok for _, ok in checks), "checks": [{"id": cid, "ok": ok} for cid, ok in checks]}


FALLBACK_MARKER = "<!-- ai-factory:template-fallback -->"


def mark_fallback(html: str) -> str:
    """Emergency template placed on main; never used as the base for AI game work."""
    return html if FALLBACK_MARKER in html else html.replace("<!doctype html>", "<!doctype html>" + FALLBACK_MARKER, 1)


def is_fallback(html: str | None) -> bool:
    return bool(html) and FALLBACK_MARKER in html


def normalize(html: str) -> str:
    """Adds what only the factory needs (doctype, body marker) to an otherwise complete model-written game."""
    out = html.strip()
    if not out.lower().startswith("<!doctype html"):
        out = "<!doctype html>\n" + out
    if 'data-ai-factory-game="v2"' not in out:
        out = re.sub(r"<body(\s|>)", lambda m: '<body data-ai-factory-game="v2"' + m.group(1), out, count=1, flags=re.I)
    return out + "\n"


def template_similarity(html: str, catalog_dir: Path) -> float:
    """Share of the game's code lines that also appear in a family template (1.0 = echo).
    Line overlap only flags real copies; unrelated games of similar size score near 0."""
    lines = {l.strip() for l in html.splitlines() if len(l.strip()) > 20}
    if not lines:
        return 0.0
    best = 0.0
    for family in ("strategy", "action", "management"):
        path = catalog_dir / "games" / f"{family}.html"
        if path.exists():
            tpl = {l.strip() for l in path.read_text(encoding="utf-8").splitlines() if len(l.strip()) > 20}
            best = max(best, len(lines & tpl) / len(lines))
    return best
