"""Task execution: prompt construction, provider calls with failover, and the simulated worker
used when the account has no usable provider (keeps the line moving, clearly labelled)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..providers import ExecuteRequest, ProviderAdapter, ProviderError

SIM_ID = "sim-local"
SIM_NAME = "Simulated Local Worker"


@dataclass
class TaskContext:
    line_title: str
    topic: str
    game_type: str
    family: str
    pitch: str
    loop: list[str]
    platform: str
    stage_name: str
    stage_summary: str
    task_name: str
    role: str
    kind: str
    artifact: str
    dependencies: dict[str, str] = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)
    game_source: str | None = None  # set for tasks that must return the updated game


GAME_RULES = (
    "Return the COMPLETE updated game as ONE self-contained HTML file inside a single ```html code block, "
    "after your notes. Hard requirements: starts with <!doctype html>; <body data-ai-factory-game=\"v2\">; "
    "a global function startGame() that (re)starts play; no external scripts, stylesheets, fonts, images or network "
    "requests (inline everything, draw with canvas/CSS); runs offline inside a sandboxed iframe; keyboard and pointer "
    "controls; visible score, win/lose state and restart; Korean UI text; responsive down to 360px wide."
)


def build_prompt(ctx: TaskContext) -> ExecuteRequest:
    system = (
        f"You are the {ctx.role} in an autonomous game studio. You produce production artifacts, not chat. "
        f"Write the complete content of `{ctx.artifact}` and nothing else. Be concrete and specific to this game. "
        "Write prose in Korean; code, identifiers and file formats in English."
    )
    deps = "\n\n".join(f"### {name}\n{body[:1500]}" for name, body in ctx.dependencies.items()) or "(none)"
    feedback = "\n".join(f"- {f}" for f in ctx.feedback) or "(none)"
    qa_rule = ""
    if ctx.kind in ("qa", "vision"):
        qa_rule = "\nEnd with a final line exactly `RESULT: PASS` or `RESULT: FAIL` followed by the blocking issues."
    prompt = (
        f"# Game\n{ctx.line_title} ({ctx.game_type}, family {ctx.family}, platform {ctx.platform})\n"
        f"Pitch: {ctx.pitch}\nCore loop: {' → '.join(ctx.loop)}\n\n"
        f"# Stage\n{ctx.stage_name}: {ctx.stage_summary}\n\n"
        f"# Your task\n{ctx.task_name} → produce `{ctx.artifact}`{qa_rule}\n\n"
        f"# Inputs from completed dependencies\n{deps}\n\n# CEO feedback to honour\n{feedback}\n"
    )
    max_tokens = 3000 if ctx.kind in ("coding", "debugging") else 1600
    if ctx.game_source is not None:
        prompt += f"\n# Game deliverable\n{GAME_RULES}\n\n# Current game source\n```html\n{ctx.game_source[:60000]}\n```\n"
        max_tokens = 12000
    return ExecuteRequest(prompt=prompt, system=system, max_tokens=max_tokens)


_HTML_BLOCK = re.compile(r"```html\s*\n(.*?)```", re.S | re.I)


def extract_game(text: str) -> str | None:
    """Returns the last complete HTML document the model produced, if any."""
    blocks = [b.strip() for b in _HTML_BLOCK.findall(text or "")]
    docs = [b for b in blocks if b.lower().startswith("<!doctype html")]
    return docs[-1] + "\n" if docs else None


def simulate(ctx: TaskContext) -> str:
    """Deterministic artifact used when no real provider is connected."""
    lines = [
        f"# {ctx.task_name}",
        "",
        f"- Game: {ctx.line_title}",
        f"- Stage: {ctx.stage_name}",
        f"- Role: {ctx.role}",
        f"- Worker: {SIM_NAME} (no provider connected — connect one in the AI Marketplace for real output)",
        "",
        "## Brief",
        ctx.pitch,
        "",
        "## Core loop",
        *[f"{i}. {step}" for i, step in enumerate(ctx.loop, start=1)],
        "",
        "## Inputs",
        *([f"- {name}" for name in ctx.dependencies] or ["- (none)"]),
    ]
    if ctx.feedback:
        lines += ["", "## CEO feedback applied", *[f"- {f}" for f in ctx.feedback]]
    if ctx.kind in ("qa", "vision"):
        lines += ["", "RESULT: PASS"]
    return "\n".join(lines) + "\n"


_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.S)


def to_file_content(artifact: str, text: str) -> tuple[str, str]:
    """Maps model output onto the artifact path (directories get a README; code fences are unwrapped)."""
    path = artifact.rstrip("/") + "/README.md" if artifact.endswith("/") else artifact
    body = text.strip() + "\n"
    if re.search(r"\.(js|css|html|json|patch|log)$", path):
        m = _FENCE.search(text)
        if m:
            body = m.group(1).strip() + "\n"
    if path.endswith(".json"):
        try:
            json.loads(body)
        except ValueError:
            body = json.dumps({"content": text.strip()}, ensure_ascii=False, indent=2) + "\n"
    if path.endswith(".zip"):
        path = path[:-4] + ".manifest.md"
    return path, body


def qa_verdict(text: str) -> str:
    m = re.findall(r"RESULT:\s*(PASS|FAIL)", text or "", re.I)
    return "failed" if m and m[-1].upper() == "FAIL" else "passed"


@dataclass
class Attempt:
    connection_id: str
    name: str
    ok: bool
    error_kind: str | None = None
    tokens: int = 0
    latency_ms: int = 0


def run_with_failover(candidates: list[tuple[str, str, ProviderAdapter]], request: ExecuteRequest):
    """Tries candidates in router order. Returns (text, attempts). Raises when all fail."""
    attempts: list[Attempt] = []
    for connection_id, name, adapter in candidates:
        try:
            result = adapter.execute(request)
        except ProviderError as exc:
            attempts.append(Attempt(connection_id, name, False, exc.info.kind))
            continue
        attempts.append(Attempt(connection_id, name, True, None, result.usage.total_tokens, result.latency_ms))
        return result.text, attempts
    raise AllProvidersFailed(attempts)


class AllProvidersFailed(RuntimeError):
    def __init__(self, attempts: list[Attempt]):
        super().__init__("all providers failed: " + ", ".join(f"{a.name}:{a.error_kind}" for a in attempts))
        self.attempts = attempts
