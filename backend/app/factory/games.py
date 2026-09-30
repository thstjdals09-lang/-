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
