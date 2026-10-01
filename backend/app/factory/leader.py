"""Server-side Leader Agent.

For each production line the Leader instantiates the current stage's task graph, routes ready
tasks through the CHEAPEST_VIABLE_QUALITY router, executes them on real providers (with
failover), commits every result through an isolated git worktree, runs review/QA gates, repairs
QA failures, produces builds, and stops at the CEO release gate. Mirrors docs/js/engine.js.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import catalog, db, routing, vault
from ..connections import next_reset
from ..providers import NON_CHAT, AdapterUnavailable, build_adapter, choose_model
from . import ai_ideation, games, runtime_qa
from . import research as market
from .executor import (SIM_ID, SIM_NAME, AllProvidersFailed, TaskContext, build_prompt, code_review_prompt, extract_game, plan_prompt, qa_verdict,
                       run_with_failover, simulate, to_file_content)
from .ideation import generate_ideas, slugify
from .github_sync import GitHubSync, GitHubSyncError, RepoRef, repo_name
from .pages_verifier import PagesVerifier
from .workspace import LineWorkspace, WorkspaceError
from ..account import remove_tree
from ..github_publisher import GitHubAPIError, GitHubClient

FALLBACK_KIND = {"vision": "qa", "image": "design", "audio": "design"}
GAME_PATH = "game/index.html"  # the canonical, always-playable game on main
MAX_RUNTIME_FIXES = 2
MAX_REWRITES = 2  # from-scratch rewrites by another, stronger AI once fixes are spent
MAX_WAVE = 6  # parallel tasks per line when enough AIs are connected
RECENT_MINUTES = 30  # load-balancing window
COOLDOWN = {"rate_limited": 45, "transient": 10, "unknown": 5}
DEFAULT_USER_SETTINGS = {"policy": "cheapest_viable_quality", "max_parallel": 3, "auto_shortlist": 3, "workers_per_line": 3}


def windows_package(html: str, title: str) -> dict[str, str]:
    """Windows release folder: the offline game plus a double-click launcher (default browser).
    A native wrapper (Tauri/Electron) is a later packaging step."""
    return {
        "release/windows/index.html": html,
        "release/windows/Play.cmd": '@echo off\r\nstart "" "%~dp0index.html"\r\n',
        "release/windows/README.txt": f"{title}\r\n\r\nDouble-click Play.cmd to start. Runs offline; no install needed.\r\n",
    }


def workspace_root(base: Path, user_id: str, line_id: str) -> Path:
    """Compact layout: Git for Windows caps paths at 260 characters."""
    return Path(base) / hashlib.sha1(user_id.encode()).hexdigest()[:8] / hashlib.sha1(line_id.encode()).hexdigest()[:10]


class CapacityError(RuntimeError):
    pass


class IdeaInProduction(RuntimeError):
    """The idea has a production line; delete the line first."""


class LineBusy(RuntimeError):
    """The Leader is mid-wave on this line; the CEO action should be retried."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%d %H:%M:%S")


def _parse(ts: str | None) -> datetime | None:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if ts else None


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(8)}"


class Factory:
    def __init__(self, catalog_dir: Path, workspace_dir: Path, *, simulate: bool = True, transport=None, github: GitHubSync | None = None,
                 verifier: "PagesVerifier | None" = None):
        self.catalog_dir = catalog_dir
        self.workspace_dir = Path(workspace_dir)
        self.simulate = simulate
        self.transport = transport
        self.github = github  # test/single-tenant override; normally each account uses its own GitHub
        self.verifier = verifier
        self.studio = catalog.studio(catalog_dir)
        self.stages = self.studio["stages"]
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._inflight: dict[str, int] = {}  # connection id → tasks running on it right now
        self._inflight_guard = threading.Lock()
        self.background_ideation = False  # the server runs the ideation room off the request thread

    def line_lock(self, line_id: str) -> threading.Lock:
        """One Leader at a time per line (API requests and the autopilot thread share lines)."""
        with self._locks_guard:
            return self._locks.setdefault(line_id, threading.Lock())

    # ------------------------------------------------------------------ logs / messages

    def log(self, conn, user_id, type_, text, line_id=None):
        conn.execute("INSERT INTO factory_logs(user_id, line_id, type, text) VALUES (?,?,?,?)", (user_id, line_id, type_, vault.redact(text)))

    def message(self, conn, line_id, type_, sender, recipient, text, task_id=None):
        conn.execute(
            "INSERT INTO messages(line_id, task_id, type, sender, recipient, payload) VALUES (?,?,?,?,?,?)",
            (line_id, task_id, type_, sender, recipient, json.dumps({"text": text}, ensure_ascii=False)),
        )

    def user_settings(self, conn, user_id) -> dict:
        row = conn.execute("SELECT settings FROM users WHERE id=?", (user_id,)).fetchone()
        return {**DEFAULT_USER_SETTINGS, **json.loads(row["settings"] if row else "{}")}

    # ------------------------------------------------------------------ portfolio

    def create_project(self, conn, user_id, *, topic, genre="자동선택", platform="Windows PC", notes="", kind="game") -> str:
        project_id = _id("prj")
        conn.execute("INSERT INTO projects(id, user_id, topic, genre, platform, notes, kind, status) VALUES (?,?,?,?,?,?,?,'ideating')",
                     (project_id, user_id, topic, genre, platform, notes, kind))
        if self.background_ideation and any(e.status == "online" for e, _, _ in self.employees(conn, user_id)):
            # research + several AI calls take minutes: longer than a browser request or a tunnel allows
            self.log(conn, user_id, "IDEATION", f"{topic} · AI 회의 시작: 시장 조사 → 발상 → 교차 비평 → 반론 → 합의 (몇 분 걸립니다)")
            conn.commit()
            self._start_ideation(user_id, project_id)
        else:
            self._run_ideation(conn, user_id, project_id)
        return project_id

    def _start_ideation(self, user_id, project_id) -> threading.Thread:
        job = threading.Thread(target=self._ideation_job, args=(user_id, project_id), name="ai-factory-ideation", daemon=True)
        job.start()
        return job

    def _ideation_job(self, user_id, project_id):
        conn = db.connect(autocommit=True)  # every write commits at once: no lock is held across AI calls
        try:
            self._run_ideation(conn, user_id, project_id)
        except Exception as exc:  # the project must not stay "ideating" forever
            conn.execute("UPDATE projects SET status='failed' WHERE id=?", (project_id,))
            self.log(conn, user_id, "IDEATION ERROR", f"{type(exc).__name__}: {exc}"[:300])
        finally:
            conn.close()

    def _run_ideation(self, conn, user_id, project_id):
        p = conn.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        if p is None:
            return
        topic, genre, platform, notes = p["topic"], p["genre"] or "자동선택", p["platform"] or "Web", p["notes"] or ""
        kind = p["kind"] or "game"
        research = self._research(conn, user_id, topic, genre, platform, kind)
        conn.execute("UPDATE projects SET research=? WHERE id=?", (market.to_json(research), project_id))
        ideas = ai_ideation.ideate(self, conn, user_id, topic=topic, genre=genre, platform=platform, notes=notes, studio=self.studio, research=research, kind=kind)
        if ideas is None:
            ideas = generate_ideas(topic, genre, platform, self.studio, kind)
            self.log(conn, user_id, "IDEATION", f"{topic} · 연결된 AI가 없어 오프라인 아이디어 패턴으로 생성 (AI 마켓에서 AI를 연결하면 AI가 직접 발상)")
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            return  # deleted while the room was meeting
        s = self.user_settings(conn, user_id)
        running = conn.execute("SELECT COUNT(*) FROM production_lines WHERE user_id=? AND status='running'", (user_id,)).fetchone()[0]
        n = min(s["auto_shortlist"], max(0, s["max_parallel"] - running), len(ideas))
        # consensus "drop" ideas are never produced automatically
        eligible = [i for i in ideas if (i.get("concept") or {}).get("decision") != "drop"][:n]
        chosen = {id(i) for i in eligible}
        for idea in ideas:
            idea_id = _id("idea")
            status = "shortlisted" if id(idea) in chosen else "backlog"
            conn.execute(
                "INSERT INTO ideas(id, project_id, rank, title, type, family, pitch, loop, metrics, reviews, score, status, concept) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (idea_id, project_id, idea["rank"], idea["title"], idea["type"], idea["family"], idea["pitch"], json.dumps(idea["loop"], ensure_ascii=False),
                 json.dumps(idea["metrics"]), json.dumps(idea["reviews"], ensure_ascii=False), idea["score"], status,
                 json.dumps(idea["concept"], ensure_ascii=False) if idea.get("concept") else None),
            )
            if status == "shortlisted":
                self.create_line(conn, user_id, idea_id, automatic=True)
        conn.execute("UPDATE projects SET status='ready' WHERE id=?", (project_id,))
        self.log(conn, user_id, "SHORTLIST", f"{topic} · 아이디어 {len(ideas)}개 · 상위 {len(eligible)}개 자동 생산라인 · {len(ideas) - len(eligible)}개 Backlog")

    def search_tool(self, conn, user_id):
        """The account's first online web-search connection as (row, entry, adapter), or None."""
        for row in conn.execute("SELECT * FROM provider_connections WHERE user_id=? AND status='online' ORDER BY created_at", (user_id,)).fetchall():
            entry = catalog.provider(self.catalog_dir, row["catalog_id"])
            if entry and entry.get("kind") == "search":
                try:
                    return row, entry, self._adapter(conn, user_id, row, entry)
                except (AdapterUnavailable, vault.VaultError, ValueError):
                    continue
        return None

    def _research(self, conn, user_id, topic, genre, platform, kind="game") -> dict | None:
        """Web search → analyst AI → market brief. None without a search connection."""
        tool = self.search_tool(conn, user_id)
        if tool is None:
            self.log(conn, user_id, "RESEARCH", f"{topic} · 검색 API 미연결 → 웹 시장 조사 없이 AI 지식만으로 발상 (AI 마켓 → 검색에서 연결)")
            return None
        row, entry, adapter = tool
        conn.commit()
        qs, hits, errors = market.gather(adapter, topic, genre, kind=kind)
        conn.execute("UPDATE provider_connections SET quota_used=COALESCE(quota_used,0)+?, last_error=? WHERE id=?",
                     (len(qs), errors[0] if errors and not hits else None, row["id"]))
        if not hits:
            self.log(conn, user_id, "RESEARCH", f"{topic} · {entry['name']} 검색 실패/결과 없음 → AI 지식만으로 발상" + (f" ({errors[0][:120]})" if errors else ""))
            return None
        research = {"provider": entry["name"], "queries": qs, "sources": [h.__dict__ for h in hits], "brief": None, "analyst": None, "at": _iso()}
        request = market.analyst_prompt(topic, genre, platform, hits, kind)
        try:
            text, analyst = self._ask(conn, user_id, request, kind="planning", difficulty=2)
            research["brief"] = market.parse_brief(ai_ideation._json_block(text), hits)
            research["analyst"] = analyst if research["brief"] else None
        except AllProvidersFailed:
            pass
        self.log(conn, user_id, "RESEARCH", f"{topic} · {entry['name']} 웹 검색 {len(qs)}회 · 출처 {len(hits)}개" +
                 (f" → {research['analyst']}가 시장 조사 브리프 작성" if research["brief"] else " → 브리프 작성 실패, 검색 요약만 전달"))
        return research

    def _ask(self, conn, user_id, request, *, kind="planning", difficulty=2) -> tuple[str, str]:
        """One routed call outside a line (research analyst), with failover, load balancing and accounting."""
        team = self.employees(conn, user_id)
        rtask = routing.Task(kind=kind, difficulty=difficulty, critical=True)
        decision = routing.route(rtask, [e for e, _, _ in team], policy=self.user_settings(conn, user_id)["policy"])
        by_id = {e.id: (row, entry) for e, row, entry in team}
        candidates = []
        for c in self._order(conn, user_id, decision, quality=False):
            row, entry = by_id[c.employee.id]
            try:
                candidates.append((c.employee.id, c.employee.name, self._adapter(conn, user_id, row, entry)))
            except (AdapterUnavailable, vault.VaultError, ValueError):
                continue
        if not candidates:
            raise AllProvidersFailed([])
        conn.commit()
        try:
            text, attempts = run_with_failover(candidates, request)
        except AllProvidersFailed as exc:
            self._record_attempts(conn, user_id, None, None, exc.attempts, rtask)
            raise
        self._record_attempts(conn, user_id, None, None, attempts, rtask)
        return text, attempts[-1].name

    def create_line(self, conn, user_id, idea_id, *, automatic=False) -> str:
        idea = conn.execute("SELECT i.*, p.topic, p.user_id FROM ideas i JOIN projects p ON p.id=i.project_id WHERE i.id=?", (idea_id,)).fetchone()
        if idea is None or idea["user_id"] != user_id:
            raise KeyError("idea not found")
        existing = conn.execute("SELECT id FROM production_lines WHERE idea_id=?", (idea_id,)).fetchone()
        if existing:
            return existing["id"]
        line_id = _id("line")
        first = next(i for i, s in enumerate(self.stages) if s.get("scope") != "portfolio")
        conn.execute(
            """INSERT INTO production_lines(id, user_id, project_id, idea_id, title, slug, project_slug, family, game_type, stage_index, status, leader_decision)
               VALUES (?,?,?,?,?,?,?,?,?,?,'running',?)""",
            (line_id, user_id, idea["project_id"], idea_id, idea["title"], slugify(idea["type"]), slugify(idea["topic"]), idea["family"], idea["type"], first, "생산라인 개설"),
        )
        for stage in self.stages[:first]:
            conn.execute("INSERT INTO stages(id, line_id, stage_key, status, qa_status, started_at, completed_at) VALUES (?,?,?,?,?,?,?)",
                         (_id("stg"), line_id, stage["id"], "completed", "passed", _iso(), _iso()))
        conn.execute("UPDATE ideas SET status='in_production' WHERE id=?", (idea_id,))
        self.log(conn, user_id, "LINE START", f"{idea['title']} · {'자동 shortlist' if automatic else 'CEO 지시'}로 생산라인 개설", line_id)
        return line_id

    def start_idea(self, conn, user_id, idea_id) -> str:
        s = self.user_settings(conn, user_id)
        running = conn.execute("SELECT COUNT(*) FROM production_lines WHERE user_id=? AND status='running'", (user_id,)).fetchone()[0]
        if running >= s["max_parallel"]:
            raise CapacityError("parallel line limit reached")
        return self.create_line(conn, user_id, idea_id, automatic=False)

    # ------------------------------------------------------------------ workforce

    def employees(self, conn, user_id) -> list[tuple[routing.Employee, sqlite3.Row, dict]]:
        now = _now()
        out = []
        for row in conn.execute("SELECT * FROM provider_connections WHERE user_id=? AND status NOT IN ('pending')", (user_id,)).fetchall():
            entry = catalog.provider(self.catalog_dir, row["catalog_id"])
            if entry is None or entry.get("kind") == "search":
                continue  # search APIs are research tools, never task workers
            reset_at = _parse(row["quota_reset_at"])
            if reset_at and now >= reset_at:
                conn.execute("UPDATE provider_connections SET quota_used=0, quota_reset_at=? WHERE id=?", (_iso(next_reset(row["quota_window"], now)), row["id"]))
                row = conn.execute("SELECT * FROM provider_connections WHERE id=?", (row["id"],)).fetchone()
            cooldown = _parse(row["cooldown_until"])
            e = routing.Employee(
                id=row["id"], name=entry["name"], skills=entry["skills"], cost_tier=entry["cost_tier"], speed=entry["speed"], reliability=entry["reliability"],
                status=row["status"], quota_unit=row["quota_unit"] or entry["quota"]["unit"], quota_limit=row["quota_limit"], quota_used=row["quota_used"] or 0,
                reserve=row["reserve"] or 0, cooldown_until=cooldown.timestamp() if cooldown else 0, context_length=entry["context_length"], modalities=entry["modalities"],
            )
            out.append((e, row, entry))
        return out

    def _order(self, conn, user_id, decision, *, quality: bool, avoid=frozenset()) -> list:
        """Spreads work over every capable AI instead of always the same few: candidates that meet the
        quality bar are ordered by price band, tasks running on them now, and use in the last
        RECENT_MINUTES, so every connected AI shares the load and a newly connected one is picked
        on the very next assignment. Paid AIs stay behind the free ones except for quality-critical
        work (game code, judges); AIs below the bar remain a last-resort tail."""
        since = _iso(_now() - timedelta(minutes=RECENT_MINUTES))
        recent = {r["connection_id"]: r["n"] for r in conn.execute(
            "SELECT connection_id, COUNT(*) AS n FROM usage_logs WHERE user_id=? AND created_at>=? GROUP BY connection_id", (user_id, since))}
        rank = {c.employee.id: i for i, c in enumerate(decision.ordered)}
        with self._inflight_guard:
            busy = dict(self._inflight)

        def band(c):
            return 0 if quality or c.employee.cost_tier <= 1 else c.employee.cost_tier

        viable = sorted((c for c in decision.ordered if c.viable),
                        key=lambda c: (c.employee.id in avoid, band(c), busy.get(c.employee.id, 0), recent.get(c.employee.id, 0), rank[c.employee.id]))
        tail = sorted((c for c in decision.ordered if not c.viable), key=lambda c: (c.employee.id in avoid, rank[c.employee.id]))
        return viable + tail

    def _busy(self, connection_id: str, delta: int) -> None:
        with self._inflight_guard:
            self._inflight[connection_id] = max(0, self._inflight.get(connection_id, 0) + delta)

    def _adapter(self, conn, user_id, row, entry):
        secret = vault.reveal(conn, user_id, row["credential_id"]) if row["credential_id"] else None
        return build_adapter(entry, secret=secret, endpoint=row["endpoint"], model=row["model"], transport=self.transport)

    def _record_attempts(self, conn, user_id, line_id, task_id, attempts, estimated_task):
        now = _now()
        failed = [a for a in attempts if not a.ok]
        for a in attempts:
            conn.execute(
                "INSERT INTO usage_logs(user_id, connection_id, task_id, prompt_tokens, completion_tokens, latency_ms, outcome, error_kind) VALUES (?,?,?,?,?,?,?,?)",
                (user_id, a.connection_id, task_id, a.tokens, 0, a.latency_ms, "ok" if a.ok else "error", a.error_kind),
            )
            if not a.ok:
                if a.error_kind == "model_unavailable":
                    self._switch_model(conn, user_id, a.connection_id, line_id)
                elif a.error_kind == "auth_error":
                    conn.execute("UPDATE provider_connections SET status='auth_required', last_error='auth_error' WHERE id=?", (a.connection_id,))
                elif a.error_kind == "no_credit":
                    # taken off the roster until the owner tops up and re-verifies; retrying only wastes time
                    was_online = conn.execute("SELECT status FROM provider_connections WHERE id=?", (a.connection_id,)).fetchone()
                    conn.execute("UPDATE provider_connections SET status='offline', last_error=? WHERE id=?",
                                 ("결제 잔액(크레딧)이 없어 호출이 거절됨 · 충전 후 '재검증'을 누르면 다시 투입됩니다", a.connection_id))
                    if was_online and was_online["status"] == "online":
                        self.log(conn, user_id, "NO CREDIT", f"{a.name} · 결제 잔액이 없어 배정에서 제외 (충전 후 AI 사원 화면에서 재검증)", line_id)
                elif a.error_kind == "quota_exhausted":
                    conn.execute("UPDATE provider_connections SET quota_used=COALESCE(quota_limit, quota_used) WHERE id=?", (a.connection_id,))
                elif a.error_kind in COOLDOWN:
                    conn.execute("UPDATE provider_connections SET cooldown_until=? WHERE id=?", (_iso(now + timedelta(seconds=COOLDOWN[a.error_kind])), a.connection_id))
            else:
                row = conn.execute("SELECT quota_unit, quota_limit, quota_used, reserve FROM provider_connections WHERE id=?", (a.connection_id,)).fetchone()
                if row and row["quota_limit"]:
                    unit = row["quota_unit"]
                    use = a.tokens if unit == "tokens" and a.tokens else routing.usage_for(routing.Employee(a.connection_id, a.name, {}, quota_unit=unit), estimated_task)
                    was = row["quota_limit"] - row["quota_used"] <= row["quota_limit"] * (row["reserve"] or 0)
                    used = min(row["quota_limit"], row["quota_used"] + use)
                    conn.execute("UPDATE provider_connections SET quota_used=? WHERE id=?", (used, a.connection_id))
                    if not was and row["quota_limit"] - used <= row["quota_limit"] * (row["reserve"] or 0):
                        self.log(conn, user_id, "QUOTA WARNING", f"{a.name} 예약선 도달 · 비핵심 작업 배정 중단", line_id)
        if failed and attempts[-1].ok:
            chain = " → ".join(f"{a.name}({a.error_kind})" for a in failed)
            self.log(conn, user_id, "FAILOVER", f"{chain} → {attempts[-1].name} handoff", line_id)
            if line_id:
                self.message(conn, line_id, "handoff", failed[-1].name, attempts[-1].name, f"{failed[-1].error_kind} 발생으로 작업 인계", task_id)

    def _switch_model(self, conn, user_id, connection_id, line_id=None) -> str | None:
        """The provider retired or refused the model: move this connection to another served model."""
        row = conn.execute("SELECT * FROM provider_connections WHERE id=?", (connection_id,)).fetchone()
        entry = catalog.provider(self.catalog_dir, row["catalog_id"]) if row else None
        if not row or not entry:
            return None
        tried = set(json.loads(row["last_error"] or "[]") if (row["last_error"] or "").startswith("[") else [])
        tried.add(row["model"])
        picked = choose_model(entry, json.loads(row["models"] or "[]"), exclude=tried)
        if picked:
            conn.execute("UPDATE provider_connections SET model=?, last_error=? WHERE id=?", (picked, json.dumps(sorted(tried)), connection_id))
            self.log(conn, user_id, "MODEL SWITCH", f"{entry['name']} · {row['model']} 사용 불가 → {picked}로 자동 변경", line_id)
        else:
            conn.execute("UPDATE provider_connections SET status='offline', last_error=? WHERE id=?", ("no usable model", connection_id))
            self.log(conn, user_id, "MODEL SWITCH", f"{entry['name']} · 사용 가능한 대화 모델이 없어 배정 중단", line_id)
        return picked

    def recover_on_startup(self, conn) -> dict:
        """After a restart nothing is really running: interrupted tasks go back to the queue, and
        connections stuck on a non-chat or unlisted model are moved to a served chat model."""
        tasks = conn.execute("UPDATE tasks SET status='ready' WHERE status='in_progress'").rowcount
        meetings = conn.execute("SELECT id, user_id FROM projects WHERE status='ideating'").fetchall()
        for p in meetings:
            conn.execute("DELETE FROM ideas WHERE project_id=? AND id NOT IN (SELECT idea_id FROM production_lines)", (p["id"],))
            if self.background_ideation:
                self._start_ideation(p["user_id"], p["id"])
            else:
                conn.execute("UPDATE projects SET status='failed' WHERE id=?", (p["id"],))
        fixed = 0
        for row in conn.execute("SELECT * FROM provider_connections").fetchall():
            entry = catalog.provider(self.catalog_dir, row["catalog_id"])
            models = json.loads(row["models"] or "[]")
            allowed_alias = entry and entry.get("default_alias") and row["model"] == entry.get("default_model")
            if entry and models and not allowed_alias and (row["model"] not in models or NON_CHAT.search(row["model"] or "")):
                picked = choose_model(entry, models)
                if picked and picked != row["model"]:
                    conn.execute("UPDATE provider_connections SET model=? WHERE id=?", (picked, row["id"]))
                    fixed += 1
        return {"tasks_requeued": tasks, "models_fixed": fixed}

    def execute(self, conn, user_id, line_id, task: dict, ctx: TaskContext, policy: str, *, request=None, avoid_ids=frozenset()) -> tuple[str, str, str]:
        """Returns (text, connection_id, worker_name). Raises AllProvidersFailed when stuck.
        `request` replaces the default task prompt; `avoid_ids` are AIs to try last (e.g. the author, for a review)."""
        team = self.employees(conn, user_id)
        # Game code and gate decisions need the strongest models: raise the bar so weak AIs only get them as a last resort.
        quality = bool(ctx.game_task or ctx.judge)
        rtask = routing.Task(kind=task["kind"], difficulty=max(task["difficulty"], 3) if quality else task["difficulty"], critical=bool(task["critical"]) or quality)
        decision = routing.route(rtask, [e for e, _, _ in team], policy=policy)
        if not decision.ordered and task["kind"] in FALLBACK_KIND and team:
            capable_cooling = any(e.cooldown_until > _now().timestamp() and e.skills.get(task["kind"], 0) > 0 for e, _, _ in team)
            if not capable_cooling:
                sub = FALLBACK_KIND[task["kind"]]
                conn.execute("UPDATE tasks SET kind=?, substituted_from=? WHERE id=?", (sub, task["kind"], task["id"]))
                self.log(conn, user_id, "SUBSTITUTE", f"{task['name']} · {task['kind']} AI 없음 → {sub} 방식 대체", line_id)
                task = {**task, "kind": sub}
                ctx.kind = sub
                ctx.images = []
                rtask.kind = sub
                decision = routing.route(rtask, [e for e, _, _ in team], policy=policy)
        by_id = {e.id: (row, entry) for e, row, entry in team}
        avoid = set(avoid_ids)
        if task["task_key"].startswith("rewrite"):
            # a rewrite goes to a different AI than the ones whose game kept failing
            avoid |= {r["connection_id"] for r in conn.execute("SELECT connection_id FROM tasks WHERE stage_id=? AND connection_id IS NOT NULL", (task["stage_id"],))}
        candidates = []
        for c in self._order(conn, user_id, decision, quality=quality, avoid=avoid):
            row, entry = by_id[c.employee.id]
            try:
                candidates.append((c.employee.id, c.employee.name, self._adapter(conn, user_id, row, entry)))
            except (AdapterUnavailable, vault.VaultError, ValueError):
                continue
        request = request or build_prompt(ctx)
        if candidates:
            first = candidates[0][0]
            self._busy(first, +1)
            try:
                text, attempts = run_with_failover(candidates, request)
                self._record_attempts(conn, user_id, line_id, task["id"], attempts, rtask)
                if decision.degraded:
                    self.log(conn, user_id, "DEGRADED", f"{task['name']} · 품질 기준 {decision.required:.0f} 미달 AI로 진행", line_id)
                return text, attempts[-1].connection_id, attempts[-1].name
            except AllProvidersFailed as exc:
                self._record_attempts(conn, user_id, line_id, task["id"], exc.attempts, rtask)
                if not self.simulate:
                    raise
            finally:
                self._busy(first, -1)
        elif not self.simulate:
            raise AllProvidersFailed([])
        return simulate(ctx), SIM_ID, SIM_NAME

    # ------------------------------------------------------------------ stage graph

    def workspace(self, user_id, line_id) -> LineWorkspace:
        return LineWorkspace(workspace_root(self.workspace_dir, user_id, line_id))

    def _stage_row(self, conn, line_id, key):
        return conn.execute("SELECT * FROM stages WHERE line_id=? AND stage_key=?", (line_id, key)).fetchone()

    def _instantiate(self, conn, line, stage_def):
        stage_id = _id("stg")
        conn.execute("INSERT INTO stages(id, line_id, stage_key, status, started_at) VALUES (?,?,?,?,?)", (stage_id, line["id"], stage_def["id"], "in_progress", _iso()))
        ids = {}
        for t in stage_def["tasks"]:
            ids[t["id"]] = _id("tsk")
            conn.execute(
                "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ids[t["id"]], line["id"], stage_id, t["id"], t["name"], t["role"], t["kind"], t["difficulty"], int(bool(t.get("critical"))), t["artifact"], "pending" if t["depends"] else "ready"),
            )
        for t in stage_def["tasks"]:
            for d in t["depends"]:
                conn.execute("INSERT INTO task_dependencies(task_id, depends_on) VALUES (?,?)", (ids[t["id"]], ids[d]))
        conn.execute("UPDATE production_lines SET leader_state='planning', leader_decision=? WHERE id=?", (f"{stage_def['name']} 작업 {len(stage_def['tasks'])}개로 분해", line["id"]))
        self.message(conn, line["id"], "plan", "Leader", "workers", f"{stage_def['name']} task graph 생성")
        return self._stage_row(conn, line["id"], stage_def["id"])

    def _refresh(self, conn, stage_id):
        conn.execute(
            """UPDATE tasks SET status='ready' WHERE stage_id=? AND status='pending' AND NOT EXISTS (
                 SELECT 1 FROM task_dependencies d JOIN tasks p ON p.id=d.depends_on WHERE d.task_id=tasks.id AND p.status!='completed')""",
            (stage_id,),
        )

    def _context(self, conn, line, stage_def, task) -> TaskContext:
        idea = conn.execute("SELECT i.*, p.platform, p.research FROM ideas i JOIN projects p ON p.id=i.project_id WHERE i.id=?", (line["idea_id"],)).fetchone()
        deps = conn.execute(
            "SELECT a.path, a.content FROM task_dependencies d JOIN artifacts a ON a.task_id=d.depends_on WHERE d.task_id=?", (task["id"],)
        ).fetchall()
        feedback = [r["text"] for r in conn.execute("SELECT text FROM feedback WHERE line_id=? ORDER BY created_at", (line["id"],)).fetchall()]
        deps = [(r["path"], r["content"]) for r in deps]
        if task["repair_of"]:
            # the failed check's report and any review notes on the original work
            deps += [(r["path"], r["content"]) for r in conn.execute(
                "SELECT path, content FROM artifacts WHERE task_id=? ORDER BY id", (task["repair_of"],)).fetchall()]
        if task["task_key"].startswith("runtime-fix"):
            qa = conn.execute("SELECT path, content FROM artifacts WHERE line_id=? AND path LIKE 'qa/runtime-%' ORDER BY id DESC LIMIT 1", (line["id"],)).fetchone()
            if qa:
                deps.append((qa["path"], qa["content"]))
        return TaskContext(
            line_title=line["title"], topic=line["project_slug"], game_type=line["game_type"], family=line["family"], pitch=idea["pitch"],
            loop=json.loads(idea["loop"]), platform=idea["platform"] or "Web", stage_name=stage_def["name"], stage_summary=stage_def.get("summary", ""),
            task_name=task["name"], role=task["role"], kind=task["kind"], artifact=task["artifact"] or "notes.md",
            dependencies={path: content or "" for path, content in deps}, feedback=feedback,
            judge=self._is_judge(stage_def, task), concept=json.loads(idea["concept"]) if idea["concept"] else None,
            dossier=self._dossier(conn, line, stage_def),
            research=market.as_text(json.loads(idea["research"]) if idea["research"] else None, 2500),
        )

    DOSSIER_PRIORITY = ("GDD.md", "core-loop.md", "economy.md", "architecture.md", "ux-flow.md", "art-bible.md", "production-backlog.json",
                        "greenlight-report.md", "fun-review.md", "prototype-findings.md", "quality-bar.md", "visual-review.md", "code-review.md",
                        "balance-report.md", "rc-review.md")
    DOSSIER_LIMIT = 14000

    def _dossier(self, conn, line, stage_def) -> dict[str, str]:
        """Latest artifact per path from earlier stages, key design documents first, size-capped."""
        rows = conn.execute(
            """SELECT path, content, stage_key FROM artifacts WHERE line_id=? AND stage_key!=? AND content IS NOT NULL
               AND path NOT LIKE 'builds/%' AND path NOT LIKE 'release/%' AND path NOT LIKE 'game/%' AND path NOT LIKE 'qa/runtime-%'
               ORDER BY id DESC""",
            (line["id"], stage_def["id"]),
        ).fetchall()
        latest: dict[str, str] = {}
        for r in rows:
            if r["path"].endswith((".md", ".json")) and r["path"] not in latest:
                latest[r["path"]] = r["content"]
        rank = {name: i for i, name in enumerate(self.DOSSIER_PRIORITY)}
        ordered = sorted(latest, key=lambda p: rank.get(p.rsplit("/", 1)[-1], len(rank)))
        out, used = {}, 0
        for path in ordered:
            budget = 2400 if path.rsplit("/", 1)[-1] in rank else 900
            body = latest[path][:budget]
            if used + len(body) > self.DOSSIER_LIMIT:
                break
            out[path] = body
            used += len(body)
        return out

    def _is_judge(self, stage_def, task) -> bool:
        return not task["repair_of"] and any(t["id"] == task["task_key"] and t.get("judge") for t in stage_def["tasks"])

    def _spawn_repair(self, conn, stage_row, task):
        n = conn.execute("SELECT COUNT(*) FROM tasks WHERE stage_id=? AND repair_of=?", (stage_row["id"], task["id"])).fetchone()[0] // 2 + 1
        fix_id, retest_id = _id("tsk"), _id("tsk")
        stage_index = next(i for i, s in enumerate(self.stages) if s["id"] == stage_row["stage_key"])
        prototype_index = next(i for i, s in enumerate(self.stages) if s["id"] == "prototype")
        if stage_index < prototype_index:
            fix = ("기획 수정", "Game Designer", "planning", f"revisions/{task['task_key']}-{n}.md")
        else:
            fix = ("자동 수정", "Gameplay Programmer", "debugging", f"fix-{task['task_key']}.patch")
        conn.execute(
            "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status, repair_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fix_id, task["line_id"], stage_row["id"], f"{task['task_key']}-fix{n}", f"{fix[0]}: {task['name']}", fix[1], fix[2], 2, 0, fix[3], "ready", task["id"]),
        )
        conn.execute(
            "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status, repair_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (retest_id, task["line_id"], stage_row["id"], f"{task['task_key']}-retest{n}", f"재검증: {task['name']}", task["role"], task["kind"], task["difficulty"], 0, task["artifact"], "pending", task["id"]),
        )
        conn.execute("INSERT INTO task_dependencies(task_id, depends_on) VALUES (?,?)", (retest_id, fix_id))
        conn.execute(
            "INSERT INTO task_dependencies(task_id, depends_on) SELECT task_id, ? FROM task_dependencies WHERE depends_on=? AND task_id NOT IN (?, ?)",
            (retest_id, task["id"], fix_id, retest_id),
        )

    def _template_game(self, line) -> str:
        return games.render(self.catalog_dir, title=line["title"], topic=line["project_slug"], game_type=line["game_type"], family=line["family"])

    def current_game(self, ws: LineWorkspace, line) -> str:
        """The canonical game on main; falls back to the family template until one exists."""
        html = ws.read(GAME_PATH)
        return html if html and games.smoke_test(html)["passed"] else games.mark_fallback(self._template_game(line))

    def _is_game_task(self, stage_def, task) -> bool:
        if task["task_key"].startswith(("ceo-", "runtime-fix", "rewrite")) or (task["repair_of"] and task["kind"] == "debugging"):
            return True
        return any(t["id"] == task["task_key"] and t.get("game") for t in stage_def["tasks"])

    def _execute_phase(self, user_id, line, stage_def, task, policy) -> dict:
        """Worker-thread part of a task: context + provider calls. Uses its own autocommit connection
        so no write lock is held across slow network calls; touches no git state."""
        conn = db.connect(autocommit=True)
        try:
            ctx = self._context(conn, line, stage_def, task)
            game_task = self._is_game_task(stage_def, task)
            ws = self.workspace(user_id, line["id"])
            if game_task:
                ctx.game_task = True
                existing = ws.read(GAME_PATH)
                # The emergency template is never handed to the AI as "the game": it would just edit it.
                usable = (existing and games.smoke_test(existing)["passed"] and not games.is_fallback(existing)
                          and not task["task_key"].startswith("rewrite"))
                ctx.game_source = existing if usable else None
            if task["kind"] == "vision":
                shot = runtime_qa.run(self.current_game(ws, line))
                if shot["screenshot"]:
                    ctx.images = [shot["screenshot"]]
                ctx.dossier["qa/runtime-now.json"] = json.dumps({"status": shot["status"], "checks": shot["checks"], "errors": shot["errors"]}, ensure_ascii=False)
            conn.execute("UPDATE tasks SET status='in_progress', attempts=attempts+1, started_at=? WHERE id=?", (_iso(), task["id"]))
            plan = None
            if game_task and ctx.game_source is None and self._has_real_ai(conn, user_id):
                plan = self._plan(conn, user_id, line, task, ctx, policy)
            try:
                text, connection_id, worker = self.execute(conn, user_id, line["id"], dict(task), ctx, policy)
            except AllProvidersFailed:
                return {"blocked": True}
            reviewer, reviewer_conn = None, None
            if game_task and connection_id != SIM_ID:
                text, review_text, reviewer_conn, reviewer = self._review_and_revise(conn, user_id, line, task, ctx, policy, text, connection_id, worker)
                return {"blocked": False, "ctx": ctx, "game_task": game_task, "text": text, "connection_id": connection_id, "worker": worker,
                        "reviewer": reviewer, "reviewer_conn": reviewer_conn, "review_text": review_text, "plan": plan}
            if task["kind"] == "coding":
                path, body = to_file_content(task["artifact"] or "notes.md", text)
                review_ctx = TaskContext(**{**ctx.__dict__, "task_name": f"코드 리뷰: {task['name']}", "role": "Technical Director", "kind": "qa",
                                             "artifact": "review.md", "dependencies": {path: body}, "game_source": None, "game_task": False,
                                             "judge": False, "images": []})
                review_task = {**dict(task), "kind": "debugging", "difficulty": 2, "critical": 0}
                review_text, reviewer_conn, reviewer = self.execute(conn, user_id, line["id"], review_task, review_ctx, policy)
            return {"blocked": False, "ctx": ctx, "game_task": game_task, "text": text, "connection_id": connection_id,
                    "worker": worker, "reviewer": reviewer, "reviewer_conn": reviewer_conn, "review_text": review_text if task["kind"] == "coding" else None}
        finally:
            conn.close()

    def _plan(self, conn, user_id, line, task, ctx: TaskContext, policy) -> str | None:
        """Decoupling: a Technical Director AI splits the work into small checkable units before the
        programmer writes anything. The plan becomes part of the coding prompt and the review."""
        plan_task = {**dict(task), "kind": "planning", "difficulty": 3, "critical": 1}
        plan_ctx = TaskContext(**{**ctx.__dict__, "role": "Technical Director", "kind": "planning", "game_task": False, "judge": False, "images": []})
        try:
            text, cid, name = self.execute(conn, user_id, line["id"], plan_task, plan_ctx, policy, request=plan_prompt(ctx))
        except AllProvidersFailed:
            return None
        if cid == SIM_ID or len(text.strip()) < 200:
            return None
        ctx.plan = text.strip()
        self.log(conn, user_id, "PLAN", f"{line['title']} · {name}가 {task['name']} 구현 계획 작성 (상태·함수·화면·규칙·검수 항목으로 분해)", line["id"])
        return ctx.plan

    def _review_and_revise(self, conn, user_id, line, task, ctx: TaskContext, policy, text, author_id, author):
        """Dual check of a game/program answer: a syntax check that needs no AI, then a review of the
        real file by another AI. Findings go back to the author once, inside the same task.
        Returns (text, review_text | None, reviewer_connection_id, reviewer_name)."""
        html = extract_game(text)
        if html:
            html = games.normalize(html)
        static = games.static_issues(html)
        review_text, reviewer_conn, reviewer = None, None, None
        review_task = {**dict(task), "kind": "debugging", "difficulty": 3, "critical": 0}
        review_ctx = TaskContext(**{**ctx.__dict__, "role": "Technical Director", "kind": "qa", "game_task": False, "judge": False, "images": []})
        if html:
            try:
                review_text, reviewer_conn, reviewer = self.execute(conn, user_id, line["id"], review_task, review_ctx, policy,
                                                                    request=code_review_prompt(ctx, html, static), avoid_ids={author_id})
            except AllProvidersFailed:
                review_text = None
            if reviewer_conn == SIM_ID:
                review_text, reviewer_conn, reviewer = None, None, None
        rejected = review_text is not None and qa_verdict(review_text) == "failed"
        if static:
            self.log(conn, user_id, "STATIC CHECK", f"{line['title']} · {author} 코드 문법 검사 불합격: {static[0][:140]}", line["id"])
        if not static and not rejected:
            return text, review_text, reviewer_conn, reviewer
        notes = "\n".join(f"- {s}" for s in static)
        if rejected:
            notes += f"\n\nReviewer ({reviewer}):\n{review_text[-2500:]}"
        fix_ctx = TaskContext(**{**ctx.__dict__, "previous_answer": html, "revision_notes": notes.strip()})
        try:
            text2, cid2, _ = self.execute(conn, user_id, line["id"], dict(task), fix_ctx, policy)
        except AllProvidersFailed:
            text2, cid2 = None, None
        html2 = extract_game(text2) if text2 and cid2 != SIM_ID else None
        static2 = games.static_issues(games.normalize(html2)) if html2 else None
        if static2 is not None and len(static2) <= len(static):
            self.log(conn, user_id, "REVISION", f"{line['title']} · {task['name']} 지적 {len(static) + int(rejected)}건을 작업 안에서 바로 수정"
                     + (" (문법 검사 통과)" if not static2 else f" (문법 문제 {len(static2)}건 남음)"), line["id"])
            text, static = text2, static2
            verdict = "RESULT: FAIL" if static else "RESULT: PASS"
            review_text = ((review_text or "") + "\n\n## 작업 내 수정\n지적 사항을 작성자에게 돌려보내 다시 받음. 남은 문법 문제: "
                           + ("; ".join(static) if static else "없음") + f"\n{verdict}")
        elif static:
            review_text = (review_text or "") + "\n\n## 문법 검사\n" + "\n".join(f"- {s}" for s in static) + "\nRESULT: FAIL"
        return text, review_text, reviewer_conn, reviewer

    def _finalize_task(self, conn, user_id, line, stage_def, stage_row, task, res):
        """Leader-thread part: files → worktree commit → merge → task/artifact rows (serialized)."""
        if res["blocked"]:
            conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (task["id"],))
            self.log(conn, user_id, "BLOCKED", f"{line['title']} · {task['name']} 배정 가능한 AI 없음", line["id"])
            return
        ws = self.workspace(user_id, line["id"])
        text, connection_id, worker, reviewer = res["text"], res["connection_id"], res["worker"], res["reviewer"]
        path, body = to_file_content(task["artifact"] or "notes.md", text)
        files = {path: body}
        if res["game_task"]:
            generated = extract_game(text) if connection_id != SIM_ID else None
            patched = False
            if not generated and connection_id != SIM_ID:
                base = ws.read(GAME_PATH)
                if base and not games.is_fallback(base):
                    generated = games.apply_patch(base, text)  # the worker answered with a diff: apply it
                    patched = bool(generated)
            if generated:
                generated = games.normalize(generated)
            similarity = games.template_similarity(generated, self.catalog_dir) if generated else 0.0
            if generated and games.smoke_test(generated)["passed"] and similarity < 0.7:
                files[GAME_PATH] = generated
                self.log(conn, user_id, "GAME UPDATE", f"{line['title']} · {worker}가 게임 코드 {'수정(diff 적용)' if patched else '작성/갱신'} ({len(generated):,} bytes)", line["id"])
            else:
                if generated:
                    reason = "기본 템플릿을 거의 그대로 반환" if similarity >= 0.7 else "필수 요소(startGame 등) 누락"
                    self.log(conn, user_id, "GAME REJECTED", f"{line['title']} · {worker} 결과 거부: {reason} → 이전 게임 유지", line["id"])
                elif connection_id != SIM_ID:
                    self.log(conn, user_id, "GAME REJECTED", f"{line['title']} · {worker} 결과에 완성된 HTML이나 적용 가능한 diff가 없음 → 이전 게임 유지", line["id"])
                current = ws.read(GAME_PATH)
                if current is None:
                    files[GAME_PATH] = games.mark_fallback(self._template_game(line))  # keeps main playable; not an AI base
                    self.log(conn, user_id, "TEMPLATE FALLBACK", f"{line['title']} · AI가 만든 게임이 아직 없어 비상용 템플릿으로 main을 채움 (다음 게임 작업은 다시 백지에서 시작)", line["id"])
        if res.get("plan"):
            files[f"plans/{stage_def['id']}-{task['task_key']}.md"] = res["plan"] + "\n"
        if task["artifact"] == "release/index.html":
            files[path] = self.current_game(ws, line)
            files["release/NOTES.md"] = text
        if task["artifact"] == "release/windows.zip":
            files.pop(path, None)
            path = "release/windows/Play.cmd"
            files.update(windows_package(self.current_game(ws, line), line["title"]))
        if reviewer:
            self.message(conn, line["id"], "review_request", worker, reviewer, "diff 검토", task["id"])
        branch = ws.branch_name(line["project_slug"], line["slug"], worker, stage_def["id"], task["task_key"])
        conn.commit()  # never hold the SQLite write lock across git work
        commit = ws.commit_task(branch=branch, files=files, message=f"{stage_def['id']}: {task['name']}", author=worker)
        judge = self._is_judge(stage_def, task)
        if (task["kind"] in ("qa", "vision") or judge) and not task["repair_of"]:
            verdict = qa_verdict(text)
        elif task["kind"] in ("qa", "vision") or judge:
            verdict = "passed"
        else:
            verdict = "tests_passed" if task["kind"] == "coding" else None
        review_failed = False
        if res.get("review_text") is not None:
            review_failed = qa_verdict(res["review_text"]) == "failed" and not task["repair_of"]
            if review_failed:
                verdict = "changes_requested"
        reviewer_conn = res["reviewer_conn"]
        conn.execute(
            """UPDATE tasks SET status='completed', connection_id=?, worker_name=?, reviewer_connection_id=?, reviewer_name=?,
               branch=?, commit_sha=?, qa_status=?, finished_at=? WHERE id=?""",
            (None if connection_id == SIM_ID else connection_id, worker, None if reviewer_conn in (None, SIM_ID) else reviewer_conn, reviewer,
             branch, commit.sha, verdict, _iso(), task["id"]),
        )
        conn.execute("INSERT INTO artifacts(line_id, task_id, stage_key, path, content) VALUES (?,?,?,?,?)", (line["id"], task["id"], stage_def["id"], path, files[path][:200_000]))
        if res.get("review_text") is not None:
            conn.execute("INSERT INTO artifacts(line_id, task_id, stage_key, path, content) VALUES (?,?,?,?,?)",
                         (line["id"], task["id"], stage_def["id"], f"reviews/{stage_def['id']}-{task['task_key']}.md", res["review_text"][:20_000]))
        self.log(conn, user_id, "COMMIT", f"{line['title']} · {commit.sha[:7]} {branch} → main" + (f" (reviewed by {reviewer})" if reviewer else ""), line["id"])
        self.message(conn, line["id"], "result", worker, "Leader", f"{task['name']} 완료 · {path}", task["id"])
        if verdict == "failed":
            label = "JUDGE FAIL" if judge else "QA FAIL"
            self.log(conn, user_id, label, f"{line['title']} · {task['name']} 불합격 → 지적사항으로 수정 작업 생성", line["id"])
            self._spawn_repair(conn, stage_row, task)
        elif review_failed:
            reviewer = reviewer or "문법 검사"  # the syntax check can reject an answer without any reviewer AI
            self.log(conn, user_id, "REVIEW REJECT", f"{line['title']} · {reviewer}가 {task['name']} 변경 요청 → 리뷰 반영 수정 작업 생성", line["id"])
            self.message(conn, line["id"], "review_request", reviewer, worker, "변경 요청: " + res["review_text"][-200:], task["id"])
            self._spawn_repair(conn, stage_row, task)

    def _complete_stage(self, conn, user_id, line, stage_def, stage_row):
        deployed_version = None
        if stage_def.get("build"):
            ws = self.workspace(user_id, line["id"])
            ws.ensure(line["title"])
            html = self.current_game(ws, line)
            smoke = games.smoke_test(html)
            ai_game = not games.is_fallback(html)
            if not ai_game and self._has_real_ai(conn, user_id):
                # AIs are connected but none of their games made it: the template is never shipped as their work
                runtime = {"status": "failed", "checks": [], "errors": ["AI가 만든 동작하는 게임이 아직 없음"], "screenshot": None}
            else:
                conn.commit()  # runtime QA drives a browser for seconds: release the write lock first
                runtime = runtime_qa.run(html) if smoke["passed"] else {"status": "failed", "checks": [], "errors": ["static smoke failed"], "screenshot": None}
            if runtime["status"] == "failed":
                if ai_game and self._runtime_repair(conn, user_id, line, stage_def, stage_row, runtime):
                    return  # stage stays open until the repair task passes the gate
                restored = self._recover_game(conn, user_id, line, stage_def, stage_row, runtime, ws)
                if restored is None:
                    return  # a rewrite task is open, or the line is paused for the CEO
                html = restored
                smoke = games.smoke_test(html)
                conn.commit()
                runtime = runtime_qa.run(html)
            version = stage_def["build"]
            files = {f"builds/v{version}/index.html": html}
            if runtime["screenshot"]:
                files[f"builds/v{version}/screenshot.png"] = runtime["screenshot"]
            conn.commit()
            sha = ws.commit_on_main(files, f"build: v{version} ({stage_def['id']}) runtime {runtime['status']}", "Build Engineer")
            smoke = {**smoke, "runtime": runtime["status"], "runtime_checks": runtime["checks"], "runtime_errors": runtime["errors"][:5]}
            passed = smoke["passed"] and runtime["status"] != "failed"
            build_id = _id("bld")
            conn.execute(
                "INSERT INTO builds(id, line_id, version, stage_key, platform, status, smoke, commit_sha, runtime_status, screenshot) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (build_id, line["id"], version, stage_def["id"], "web", "playable" if passed else "failed", json.dumps(smoke), sha, runtime["status"],
                 f"builds/v{version}/screenshot.png" if runtime["screenshot"] else None),
            )
            conn.execute("INSERT INTO artifacts(line_id, stage_key, path, content) VALUES (?,?,?,?)", (line["id"], stage_def["id"], f"builds/v{version}/index.html", html))
            self.log(conn, user_id, "BUILD", f"{line['title']} v{version} · smoke {'통과' if smoke['passed'] else '실패'} · runtime {runtime['status']}", line["id"])
            if stage_def["id"] == "vertical" or stage_def.get("ceo_gate"):
                conn.execute("INSERT INTO reviews(id, line_id, build_id, kind, blocking, status) VALUES (?,?,?,?,?,'pending')",
                             (_id("rev"), line["id"], build_id, "release_candidate" if stage_def.get("ceo_gate") else "milestone", int(bool(stage_def.get("ceo_gate")))))
        # Stage state first (atomic with the review row), network publishing afterwards: a pending
        # review must never be visible while the line still reads as running.
        conn.execute("UPDATE stages SET status='completed', qa_status='passed', completed_at=? WHERE id=?", (_iso(), stage_row["id"]))
        self.log(conn, user_id, "STAGE COMPLETE", f"{line['title']} · {stage_def['name']} 통과", line["id"])
        if stage_def.get("ceo_gate"):
            conn.execute("UPDATE production_lines SET status='awaiting_ceo', leader_state='gate', leader_decision='릴리즈 빌드 CEO 승인 대기' WHERE id=?", (line["id"],))
        else:
            self._advance(conn, user_id, line)
        # Nothing goes to GitHub while the game is in production: builds are played from the
        # console, and the repository + Pages link are made once the CEO approves the release.

    def _has_real_ai(self, conn, user_id) -> bool:
        return any(e.status == "online" for e, _, _ in self.employees(conn, user_id))

    def _recover_game(self, conn, user_id, line, stage_def, stage_row, runtime, ws) -> str | None:
        """After the fix budget: go back to the last AI game that passed runtime QA; otherwise have a
        different, stronger AI rewrite it from scratch; otherwise pause the line for the CEO.
        Returns the restored game, or None when the stage stays open / the line is paused."""
        for r in conn.execute(
            """SELECT a.content, b.version FROM builds b JOIN artifacts a ON a.line_id=b.line_id AND a.path='builds/v'||b.version||'/index.html'
               WHERE b.line_id=? AND b.runtime_status='passed' ORDER BY b.created_at DESC, b.rowid DESC, a.id DESC""", (line["id"],)).fetchall():
            if r["content"] and not games.is_fallback(r["content"]):
                ws.commit_on_main({GAME_PATH: r["content"]}, f"revert: restore AI game v{r['version']} after failed runtime QA", "AI Factory Leader")
                self.log(conn, user_id, "RUNTIME ROLLBACK", f"{line['title']} · 수정 실패 → 마지막으로 통과한 AI 게임 v{r['version']}로 되돌림", line["id"])
                return r["content"]
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE stage_id=? AND task_key LIKE 'rewrite%' AND repair_of IS NULL", (stage_row["id"],)).fetchone()[0]
        if done < MAX_REWRITES and self._has_real_ai(conn, user_id):
            report = json.dumps({"checks": runtime["checks"], "errors": runtime["errors"]}, ensure_ascii=False, indent=2)
            conn.execute("INSERT INTO artifacts(line_id, stage_key, path, content) VALUES (?,?,?,?)", (line["id"], stage_def["id"], f"qa/runtime-{stage_def['id']}-rewrite{done + 1}.json", report))
            conn.execute(
                "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (_id("tsk"), line["id"], stage_row["id"], f"rewrite{done + 1}", "게임 처음부터 다시 작성", "Gameplay Programmer", "coding", 3, 1, f"rewrites/rewrite-{done + 1}.md", "ready"),
            )
            conn.execute("UPDATE stages SET status='in_progress', qa_status='failed', completed_at=NULL WHERE id=?", (stage_row["id"],))
            self.log(conn, user_id, "GAME REWRITE", f"{line['title']} · 동작하는 게임이 없음 ({'; '.join(runtime['errors'][:1])}) → 다른 AI에게 처음부터 다시 작성 지시 {done + 1}/{MAX_REWRITES}", line["id"])
            return None
        conn.execute("UPDATE production_lines SET status='paused', leader_state='blocked', leader_decision=? WHERE id=?",
                     ("AI들이 동작하는 게임을 만들지 못함 · 더 강한 AI를 연결하거나 수정 지시 후 재개", line["id"]))
        self.log(conn, user_id, "LINE PAUSED", f"{line['title']} · 자동 수정·재작성 모두 실패 → 라인 일시정지 (더 강한 AI 연결 또는 CEO 수정 지시 필요)", line["id"])
        return None

    def resume_blocked(self, conn, user_id, line_id) -> None:
        """Resuming a line the Leader paused for lack of a working game grants one more rewrite."""
        line = conn.execute("SELECT * FROM production_lines WHERE id=? AND user_id=?", (line_id, user_id)).fetchone()
        if line is None or line["leader_state"] != "blocked":
            return
        stage_def = self.stages[line["stage_index"]]
        stage_row = self._stage_row(conn, line_id, stage_def["id"])
        if stage_row is None:
            return
        conn.execute(
            "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_id("tsk"), line_id, stage_row["id"], f"rewrite-r{secrets.token_hex(2)}", "게임 처음부터 다시 작성 (재개)", "Gameplay Programmer", "coding", 3, 1, "rewrites/rewrite-resume.md", "ready"),
        )
        conn.execute("UPDATE stages SET status='in_progress', completed_at=NULL WHERE id=?", (stage_row["id"],))
        conn.execute("UPDATE production_lines SET leader_state='dispatching', leader_decision='재개 · 게임 재작성' WHERE id=?", (line_id,))

    def _runtime_repair(self, conn, user_id, line, stage_def, stage_row, runtime) -> bool:
        """Opens a runtime-fix game task for a failed build. False once the retry budget is spent."""
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE stage_id=? AND task_key LIKE 'runtime-fix%'", (stage_row["id"],)).fetchone()[0]
        if done >= MAX_RUNTIME_FIXES:
            return False
        report = json.dumps({"checks": runtime["checks"], "errors": runtime["errors"]}, ensure_ascii=False, indent=2)
        conn.execute("INSERT INTO artifacts(line_id, stage_key, path, content) VALUES (?,?,?,?)", (line["id"], stage_def["id"], f"qa/runtime-{stage_def['id']}-{done + 1}.json", report))
        conn.execute(
            "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_id("tsk"), line["id"], stage_row["id"], f"runtime-fix{done + 1}", "런타임 오류 자동 수정", "Gameplay Programmer", "debugging", 2, 1, f"fixes/runtime-{done + 1}.patch", "ready"),
        )
        conn.execute("UPDATE stages SET status='in_progress', qa_status='failed', completed_at=NULL WHERE id=?", (stage_row["id"],))
        errors = "; ".join(runtime["errors"][:2]) or "필수 런타임 검사 실패"
        self.log(conn, user_id, "RUNTIME QA FAIL", f"{line['title']} · {stage_def['name']} 빌드 실행 검사 실패 ({errors}) → 자동 수정 {done + 1}/{MAX_RUNTIME_FIXES}", line["id"])
        self.message(conn, line["id"], "blocked", "Runtime QA", "Leader", errors, None)
        return True

    # ------------------------------------------------------------------ GitHub

    def _publication(self, conn, line_id, **fields) -> str:
        pub_id = _id("pub")
        conn.execute(
            "INSERT INTO publications(id, line_id, kind, status, repository, repository_url, pages_url, commit_sha, detail, version) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pub_id, line_id, fields["kind"], fields["status"], fields.get("repository"), fields.get("repository_url"),
             fields.get("pages_url"), fields.get("commit_sha"), fields.get("detail"), fields.get("version")),
        )
        return pub_id

    def _repo_ref(self, conn, line) -> RepoRef | None:
        row = conn.execute(
            "SELECT repository, repository_url FROM publications WHERE line_id=? AND repository IS NOT NULL AND status IN ('created','synced','deploying','live') ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (line["id"],),
        ).fetchone()
        if not row:
            return None
        owner, repo = row["repository"].split("/", 1)
        return RepoRef(owner, repo, row["repository_url"])

    def github_for(self, conn, user_id) -> GitHubSync | None:
        """The account's own GitHub (token in the vault). The server token is for admin accounts only,
        so one user's games never land in another person's GitHub."""
        if self.github:
            return self.github
        row = conn.execute("SELECT role, github_credential_id FROM users WHERE id=?", (user_id,)).fetchone()
        if row and row["github_credential_id"]:
            token = vault.reveal(conn, user_id, row["github_credential_id"])
            return GitHubSync(GitHubClient(token), token)
        if row and row["role"] == "admin":
            return GitHubSync.from_environment()
        return None

    def _release_files(self, conn, ws, line, version) -> dict:
        idea = conn.execute("SELECT pitch FROM ideas WHERE id=?", (line["idea_id"],)).fetchone()
        files: dict[str, str | bytes] = {"index.html": self.current_game(ws, line)}
        shot = ws.read_bytes(f"builds/v{version}/screenshot.png")
        if shot:
            files["screenshot.png"] = shot
        notes = ws.read("release-notes.md")
        if notes:
            files["RELEASE_NOTES.md"] = notes
        files["README.md"] = (
            f"# {line['title']}\n\n{idea['pitch'] if idea else ''}\n\n"
            + ("![screenshot](screenshot.png)\n\n" if shot else "")
            + f"- Version: v{version}\n- Play: this repository's GitHub Pages link, or open `index.html`\n"
            + "- Produced by AI Factory: planned, written, reviewed and QA-tested by collaborating AI workers, approved by the CEO.\n"
        )
        return files

    def deploy(self, conn, user_id, line, version: str) -> dict:
        """Publishes the finished game once: GitHub repository (created now, not during production)
        → one clean release commit → push → Pages → the link is shown only after it answers 200."""
        ws = self.workspace(user_id, line["id"])
        ws.ensure(line["title"])
        if games.is_fallback(self.current_game(ws, line)):
            self._publication(conn, line["id"], kind="release", status="failed", version=version, detail="no AI-made game: the emergency template is never published")
            self.log(conn, user_id, "PUBLISH BLOCKED", f"{line['title']} · AI가 만든 게임이 없어 배포하지 않음 (비상용 템플릿은 GitHub에 올리지 않습니다)", line["id"])
            return {"status": "no_game"}
        files = self._release_files(conn, ws, line, version)
        message = f"release: v{version} {line['title']}"
        conn.commit()  # no DB write lock is held during git and network I/O
        gh = self.github_for(conn, user_id)
        if not gh:
            sha = ws.snapshot_commit(files, message, "Release Manager")
            self._publication(conn, line["id"], kind="release", status="not_configured", version=version, commit_sha=sha, detail="GitHub not connected for this account")
            self.log(conn, user_id, "PUBLISH WAITING", f"{line['title']} v{version} · 내 계정에 GitHub가 연결되지 않아 서버에만 보관 (내 계정 → GitHub 연결 후 다시 배포)", line["id"])
            return {"status": "not_configured"}
        ref = self._repo_ref(conn, line)
        try:
            parent = gh.remote_head(ws, ref) if ref else None
            if ref is None:
                idea = conn.execute("SELECT pitch FROM ideas WHERE id=?", (line["idea_id"],)).fetchone()
                ref = gh.ensure_repo(repo_name(line["project_slug"], line["slug"], line["id"]), f"AI Factory · {line['title']} · {idea['pitch'] if idea else ''}")
                self._publication(conn, line["id"], kind="repository", status="created", repository=f"{ref.owner}/{ref.repo}", repository_url=ref.html_url)
                self.log(conn, user_id, "GITHUB REPO", f"{line['title']} · 저장소 생성 {ref.owner}/{ref.repo}", line["id"])
                conn.commit()
            sha = ws.snapshot_commit(files, message, "Release Manager", parent=parent)
            gh.push(ws, ref, source="release")
            pages_url = gh.enable_pages(ref)
        except (GitHubSyncError, GitHubAPIError, WorkspaceError) as exc:
            detail = vault.redact(str(exc))[:300]
            repo = {"repository": f"{ref.owner}/{ref.repo}", "repository_url": ref.html_url} if ref else {}
            self._publication(conn, line["id"], kind="release", status="failed", version=version, detail=detail, **repo)
            self.log(conn, user_id, "PUBLISH FAIL", f"{line['title']} · {detail[:200]}", line["id"])
            return {"status": "failed"}
        self.log(conn, user_id, "GITHUB PUSH", f"{line['title']} v{version} · 커밋 {sha[:7]} → {ref.owner}/{ref.repo}", line["id"])
        pub_id = self._publication(conn, line["id"], kind="release", status="deploying", version=version, repository=f"{ref.owner}/{ref.repo}",
                                   repository_url=ref.html_url, pages_url=pages_url, commit_sha=sha)
        self.log(conn, user_id, "DEPLOYING", f"{line['title']} v{version} · Pages 빌드 확인 중 · {pages_url}", line["id"])
        conn.commit()
        (self.verifier or PagesVerifier(gh)).watch(publication_id=pub_id, user_id=user_id, line_id=line["id"], title=f"{line['title']} v{version}", ref=ref, url=pages_url, expect=sha)
        return {"status": "deploying", "repository_url": ref.html_url, "pages_url": pages_url}

    def publish_release(self, conn, user_id, line_id) -> dict:
        """Manual (re)publish of the latest build as the release."""
        line = conn.execute("SELECT * FROM production_lines WHERE id=? AND user_id=?", (line_id, user_id)).fetchone()
        if line is None:
            raise KeyError("line not found")
        build = conn.execute("SELECT version FROM builds WHERE line_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (line_id,)).fetchone()
        return self.deploy(conn, user_id, line, build["version"] if build else "0.0.0")

    def _advance(self, conn, user_id, line):
        if line["stage_index"] >= len(self.stages) - 1:
            conn.execute("UPDATE production_lines SET status='complete', leader_state='idle', leader_decision='전 공정 완료' WHERE id=?", (line["id"],))
            self.log(conn, user_id, "LINE COMPLETE", f"{line['title']} · 전 공정 완료", line["id"])
        else:
            conn.execute("UPDATE production_lines SET stage_index=stage_index+1 WHERE id=?", (line["id"],))

    def tick_line(self, conn, user_id, line_id) -> dict:
        """One Leader wave: execute up to workers_per_line ready tasks, then evaluate the gate."""
        lock = self.line_lock(line_id)
        if not lock.acquire(timeout=120):
            return {"status": "busy", "executed": 0}
        try:
            return self._tick_line(conn, user_id, line_id)
        finally:
            lock.release()

    def _select_wave(self, conn, stage_def, stage_row, limit) -> list:
        """Ready tasks for this wave; at most one game-writing task so edits never race."""
        wave, has_game = [], False
        for task in conn.execute("SELECT * FROM tasks WHERE stage_id=? AND status IN ('ready','blocked') ORDER BY rowid", (stage_row["id"],)):
            if len(wave) >= limit:
                break
            if self._is_game_task(stage_def, task):
                if has_game:
                    continue
                has_game = True
            wave.append(task)
        return wave

    def _tick_line(self, conn, user_id, line_id) -> dict:
        line = conn.execute("SELECT * FROM production_lines WHERE id=? AND user_id=?", (line_id, user_id)).fetchone()
        if line is None:
            return {"status": "deleted", "executed": 0}  # removed while queued for a tick
        if line["status"] != "running":
            return {"status": line["status"], "executed": 0}
        s = self.user_settings(conn, user_id)
        stage_def = self.stages[line["stage_index"]]
        stage_row = self._stage_row(conn, line_id, stage_def["id"])
        if stage_row is None:
            stage_row = self._instantiate(conn, line, stage_def)
        self._refresh(conn, stage_row["id"])
        online = sum(1 for e, _, _ in self.employees(conn, user_id) if e.status == "online")
        ready = self._select_wave(conn, stage_def, stage_row, max(s["workers_per_line"], min(MAX_WAVE, online)))
        if ready:
            names = ", ".join(t["name"] for t in ready)
            conn.execute("UPDATE production_lines SET leader_state='dispatching', leader_decision=? WHERE id=?", (f"{stage_def['name']} · 병렬 {len(ready)}: {names}"[:300], line_id))
            self.workspace(user_id, line_id).ensure(line["title"])
            conn.commit()  # release the write lock before workers start
            if len(ready) > 1:
                with ThreadPoolExecutor(max_workers=len(ready), thread_name_prefix="ai-factory-worker") as pool:
                    results = list(pool.map(lambda t: self._execute_phase(user_id, line, stage_def, t, s["policy"]), ready))
            else:
                results = [self._execute_phase(user_id, line, stage_def, ready[0], s["policy"])]
            for task, res in zip(ready, results):
                self._finalize_task(conn, user_id, line, stage_def, stage_row, task, res)
                conn.commit()
        self._refresh(conn, stage_row["id"])
        open_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE stage_id=? AND status!='completed'", (stage_row["id"],)).fetchone()[0]
        blocked = conn.execute("SELECT COUNT(*) FROM tasks WHERE stage_id=? AND status='blocked'", (stage_row["id"],)).fetchone()[0]
        if open_count == 0:
            self._complete_stage(conn, user_id, line, stage_def, stage_row)
        else:
            conn.execute("UPDATE production_lines SET leader_state=?, leader_decision=? WHERE id=?",
                         ("waiting" if blocked else "dispatching", f"{stage_def['name']} · 남은 작업 {open_count} · 막힘 {blocked}", line_id))
        return {"status": conn.execute("SELECT status FROM production_lines WHERE id=?", (line_id,)).fetchone()[0], "executed": len(ready), "blocked": blocked}

    def run_line(self, conn, user_id, line_id, max_waves: int = 200) -> dict:
        result = {"status": "running", "executed": 0}
        stalled = 0
        for _ in range(max_waves):
            wave = self.tick_line(conn, user_id, line_id)
            result = {"status": wave["status"], "executed": result["executed"] + wave["executed"]}
            if wave["status"] not in ("running", "busy"):
                break
            stalled = stalled + 1 if wave["executed"] == 0 or wave["status"] == "busy" or wave.get("blocked") == wave["executed"] else 0
            if stalled >= 3:
                break
        return result

    # ------------------------------------------------------------------ CEO actions

    def add_feedback(self, conn, user_id, line_id, text) -> str:
        lock = self._locked(line_id)
        try:
            return self._add_feedback(conn, user_id, line_id, text)
        finally:
            lock.release()

    def _add_feedback(self, conn, user_id, line_id, text) -> str:
        line = conn.execute("SELECT * FROM production_lines WHERE id=? AND user_id=?", (line_id, user_id)).fetchone()
        if line is None:
            raise KeyError("line not found")
        if line["status"] in ("complete", "awaiting_ceo"):
            polish = next(i for i, s in enumerate(self.stages) if s["id"] == "polish")
            keys = [s["id"] for s in self.stages[polish:]]
            conn.execute(f"DELETE FROM stages WHERE line_id=? AND stage_key IN ({','.join('?' * len(keys))})", (line_id, *keys))
            conn.execute("UPDATE production_lines SET stage_index=?, status='running', autopilot=1 WHERE id=?", (polish, line_id))
            line = conn.execute("SELECT * FROM production_lines WHERE id=?", (line_id,)).fetchone()
        stage_def = self.stages[line["stage_index"]]
        stage_row = self._stage_row(conn, line_id, stage_def["id"]) or self._instantiate(conn, line, stage_def)
        if stage_row["status"] == "completed":
            conn.execute("UPDATE stages SET status='in_progress' WHERE id=?", (stage_row["id"],))
        n = conn.execute("SELECT COUNT(*) FROM feedback WHERE line_id=?", (line_id,)).fetchone()[0] + 1
        task_id = _id("tsk")
        conn.execute(
            "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, line_id, stage_row["id"], f"ceo-{n}", f"CEO 수정 반영: {text[:40]}", "Gameplay Programmer", "coding", 2, 1, f"ceo-revision-{n}.patch", "ready"),
        )
        fb_id = _id("fb")
        conn.execute("INSERT INTO feedback(id, line_id, user_id, text, stage_key, task_id, status) VALUES (?,?,?,?,?,?,'scheduled')", (fb_id, line_id, user_id, text, stage_def["id"], task_id))
        if line["status"] == "paused":
            conn.execute("UPDATE production_lines SET status='running' WHERE id=?", (line_id,))
        self.log(conn, user_id, "CEO FEEDBACK", f"{line['title']} · {text} → {stage_def['name']} task로 편성", line_id)
        return fb_id

    # ------------------------------------------------------------------ deletion

    def delete_line(self, conn, user_id, line_id, *, idea_back_to_backlog: bool = True) -> dict:
        """Stops and removes a line: tasks, builds, reviews, logs and its local game repository.
        Repositories already pushed to the user's GitHub are left untouched."""
        lock = self._locked(line_id)
        try:
            line = conn.execute("SELECT * FROM production_lines WHERE id=? AND user_id=?", (line_id, user_id)).fetchone()
            if line is None:
                raise KeyError("line not found")
            conn.execute("DELETE FROM production_lines WHERE id=?", (line_id,))  # cascades to the whole line
            conn.execute("DELETE FROM factory_logs WHERE line_id=?", (line_id,))
            if idea_back_to_backlog:
                conn.execute("UPDATE ideas SET status='backlog' WHERE id=?", (line["idea_id"],))
            self.log(conn, user_id, "DELETED", f"{line['title']} 생산라인 삭제 (아이디어는 Backlog로 이동)" if idea_back_to_backlog else f"{line['title']} 생산라인 삭제")
            conn.commit()
            root = self.workspace(user_id, line_id).root
            remove_tree(root)
            if root.parent.exists() and not any(root.parent.iterdir()):
                root.parent.rmdir()
            return {"deleted": line_id, "title": line["title"]}
        finally:
            lock.release()

    def delete_project(self, conn, user_id, project_id) -> dict:
        project = conn.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
        if project is None:
            raise KeyError("project not found")
        lines = [r["id"] for r in conn.execute("SELECT id FROM production_lines WHERE project_id=?", (project_id,))]
        for line_id in lines:
            self.delete_line(conn, user_id, line_id, idea_back_to_backlog=False)
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))  # cascades to ideas
        self.log(conn, user_id, "DELETED", f"주제 '{project['topic']}' 삭제 · 생산라인 {len(lines)}개 포함")
        return {"deleted": project_id, "lines": len(lines)}

    def delete_idea(self, conn, user_id, idea_id) -> dict:
        idea = conn.execute("SELECT i.*, p.user_id FROM ideas i JOIN projects p ON p.id=i.project_id WHERE i.id=?", (idea_id,)).fetchone()
        if idea is None or idea["user_id"] != user_id:
            raise KeyError("idea not found")
        if conn.execute("SELECT 1 FROM production_lines WHERE idea_id=?", (idea_id,)).fetchone():
            raise IdeaInProduction(idea_id)
        conn.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
        self.log(conn, user_id, "DELETED", f"아이디어 '{idea['title']}' 삭제")
        return {"deleted": idea_id}

    def _locked(self, line_id):
        lock = self.line_lock(line_id)
        if not lock.acquire(timeout=30):
            raise LineBusy(line_id)
        return lock

    def approve(self, conn, user_id, review_id):
        row = conn.execute("SELECT line_id FROM reviews WHERE id=?", (review_id,)).fetchone()
        if row is None:
            raise KeyError("review not found")
        lock = self._locked(row["line_id"])
        try:
            self._approve(conn, user_id, review_id)
        finally:
            lock.release()

    def _approve(self, conn, user_id, review_id):
        review = conn.execute("SELECT r.*, l.user_id, l.status AS line_status FROM reviews r JOIN production_lines l ON l.id=r.line_id WHERE r.id=?", (review_id,)).fetchone()
        if review is None or review["user_id"] != user_id:
            raise KeyError("review not found")
        conn.execute("UPDATE reviews SET status='approved', reviewed_at=? WHERE id=?", (_iso(), review_id))
        self.log(conn, user_id, "CEO APPROVED", "출시 빌드 승인", review["line_id"])
        if review["blocking"] and review["line_status"] == "awaiting_ceo":
            conn.execute("UPDATE production_lines SET status='running' WHERE id=?", (review["line_id"],))
            line = conn.execute("SELECT * FROM production_lines WHERE id=?", (review["line_id"],)).fetchone()
            self._advance(conn, user_id, line)
            build = conn.execute("SELECT version FROM builds WHERE id=?", (review["build_id"],)).fetchone()
            self.deploy(conn, user_id, line, build["version"] if build else "1.0.0")

    def request_revision(self, conn, user_id, review_id, note):
        row = conn.execute("SELECT line_id FROM reviews WHERE id=?", (review_id,)).fetchone()
        if row is None:
            raise KeyError("review not found")
        lock = self._locked(row["line_id"])
        try:
            self._request_revision(conn, user_id, review_id, note)
        finally:
            lock.release()

    def _request_revision(self, conn, user_id, review_id, note):
        review = conn.execute("SELECT r.*, l.user_id FROM reviews r JOIN production_lines l ON l.id=r.line_id WHERE r.id=?", (review_id,)).fetchone()
        if review is None or review["user_id"] != user_id:
            raise KeyError("review not found")
        conn.execute("UPDATE reviews SET status='revision_requested', note=?, reviewed_at=? WHERE id=?", (note, _iso(), review_id))
        self._add_feedback(conn, user_id, review["line_id"], note)


def autopilot_pass(factory: "Factory") -> int:
    """Advances every running autopilot line by one wave. Returns how many lines moved."""
    with db.transaction() as conn:
        lines = conn.execute("SELECT id, user_id FROM production_lines WHERE status='running' AND autopilot=1 ORDER BY created_at").fetchall()
    moved = 0
    for line in lines:
        try:
            with db.transaction() as conn:
                if factory.tick_line(conn, line["user_id"], line["id"])["executed"]:
                    moved += 1
        except Exception as exc:  # one broken line must not stop the factory
            with db.transaction() as conn:
                factory.log(conn, line["user_id"], "LEADER ERROR", f"{type(exc).__name__}: {exc}", line["id"])
    return moved
