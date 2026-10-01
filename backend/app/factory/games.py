"""Renders the shared HTML5 game templates (docs/catalog/games) exactly like docs/js/games.js."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
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


_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.S | re.I)


def static_issues(html: str | None) -> list[str]:
    """Defects that can be proven without running the file: a cut-off document, missing factory
    requirements and JavaScript that does not parse (node --check, skipped when Node is absent)."""
    if not html:
        return ["no complete HTML file in the answer (it must be one ```html block starting with <!doctype html>)"]
    issues = [f"smoke check failed: {c['id']}" for c in smoke_test(html)["checks"] if not c["ok"]]
    if not re.search(r"</html>\s*$", html, re.I):
        issues.append("the file is cut off: it does not end with </html> (write a shorter, complete file)")
    if len(re.findall(r"<script\b", html, re.I)) != len(re.findall(r"</script>", html, re.I)):
        issues.append("a <script> element is never closed")
    node = shutil.which("node")
    if node:
        for attrs, body in _INLINE_SCRIPT.findall(html):
            if not body.strip() or re.search(r"type\s*=\s*[\"']?(application/(ld\+)?json|text/template)", attrs, re.I):
                continue
            suffix = ".mjs" if re.search(r"type\s*=\s*[\"']?module", attrs, re.I) else ".cjs"
            fd, name = tempfile.mkstemp(suffix=suffix, prefix="aif-syntax-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(body)
                res = subprocess.run([node, "--check", name], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
                if res.returncode != 0:
                    lines = [l for l in res.stderr.splitlines() if l.strip()]
                    where = next((l for l in lines if re.match(r".*:\d+$", l.strip())), "")
                    line_no = where.rsplit(":", 1)[-1] if where else "?"
                    error = next((l.strip() for l in lines if "Error" in l), "syntax error")
                    snippet = next((l.strip()[:120] for l in lines[1:2]), "")
                    issues.append(f"JavaScript does not parse: {error} (script line {line_no}: {snippet})")
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                try:
                    os.unlink(name)
                except OSError:
                    pass
    return issues


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
    for family in ("strategy", "action", "management", "app"):
        path = catalog_dir / "games" / f"{family}.html"
        if path.exists():
            tpl = {l.strip() for l in path.read_text(encoding="utf-8").splitlines() if len(l.strip()) > 20}
            best = max(best, len(lines & tpl) / len(lines))
    return best


_DIFF_FENCE = re.compile(r"```(?:diff|patch|html)?[^\n]*\n(.*?)```", re.S)


def apply_patch(source: str, text: str) -> str | None:
    """Applies the unified diff in `text` to `source`. Hunks are located by their content, not their
    line numbers (models get those wrong), with a whitespace-tolerant fallback. None if any hunk
    cannot be placed, so a half-applied game never reaches main."""
    body = next((b for b in _DIFF_FENCE.findall(text or "") if "@@" in b), None)
    if body is None:
        body = text if "@@" in (text or "") else None
    if not body:
        return None
    chunks = re.split(r"^@@[^\n]*$", body, flags=re.M)[1:]
    out, applied = source, 0
    for chunk in chunks:
        before, after = [], []
        for line in chunk.strip("\n").split("\n"):
            if line.startswith("\\") or line.startswith(("--- ", "+++ ", "diff --git", "index ")):
                continue
            tag, rest = line[:1], line[1:]
            if tag == "-":
                before.append(rest)
            elif tag == "+":
                after.append(rest)
            else:  # context (models often drop the leading space)
                ctx = rest if tag == " " else line
                before.append(ctx)
                after.append(ctx)
        while before and after and not before[-1].strip() and not after[-1].strip():
            before.pop()
            after.pop()
        if not "".join(before).strip():
            continue  # pure insertion without an anchor: cannot be placed safely
        old, new = "\n".join(before), "\n".join(after)
        if old in out:
            out = out.replace(old, new, 1)
            applied += 1
            continue
        lines, want = out.split("\n"), [l.strip() for l in before]
        for i in range(len(lines) - len(want) + 1):
            if [l.strip() for l in lines[i:i + len(want)]] == want:
                lines[i:i + len(want)] = after
                out = "\n".join(lines)
                applied += 1
                break
        else:
            return None
    return out if applied else None
