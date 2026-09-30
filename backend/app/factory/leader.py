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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import catalog, routing, vault
from ..connections import next_reset
from ..providers import AdapterUnavailable, build_adapter
from . import games
from .executor import SIM_ID, SIM_NAME, AllProvidersFailed, TaskContext, build_prompt, qa_verdict, run_with_failover, simulate, to_file_content
from .ideation import generate_ideas, slugify
from .workspace import LineWorkspace

FALLBACK_KIND = {"vision": "qa", "image": "design", "audio": "design"}
COOLDOWN = {"rate_limited": 45, "transient": 10, "unknown": 5}
DEFAULT_USER_SETTINGS = {"policy": "cheapest_viable_quality", "max_parallel": 3, "auto_shortlist": 3, "workers_per_line": 3}


def workspace_root(base: Path, user_id: str, line_id: str) -> Path:
    """Compact layout: Git for Windows caps paths at 260 characters."""
    return Path(base) / hashlib.sha1(user_id.encode()).hexdigest()[:8] / hashlib.sha1(line_id.encode()).hexdigest()[:10]


class CapacityError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%d %H:%M:%S")


def _parse(ts: str | None) -> datetime | None:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if ts else None


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(8)}"


class Factory:
    def __init__(self, catalog_dir: Path, workspace_dir: Path, *, simulate: bool = True, transport=None):
        self.catalog_dir = catalog_dir
        self.workspace_dir = Path(workspace_dir)
        self.simulate = simulate
        self.transport = transport
        self.studio = catalog.studio(catalog_dir)
        self.stages = self.studio["stages"]

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

    def create_project(self, conn, user_id, *, topic, genre="자동선택", platform="Windows PC", notes="") -> str:
        s = self.user_settings(conn, user_id)
        project_id = _id("prj")
        conn.execute("INSERT INTO projects(id, user_id, topic, genre, platform, notes) VALUES (?,?,?,?,?,?)", (project_id, user_id, topic, genre, platform, notes))
        ideas = generate_ideas(topic, genre, platform, self.studio)
        running = conn.execute("SELECT COUNT(*) FROM production_lines WHERE user_id=? AND status='running'", (user_id,)).fetchone()[0]
        n = min(s["auto_shortlist"], max(0, s["max_parallel"] - running), len(ideas))
        for idea in ideas:
            idea_id = _id("idea")
            status = "shortlisted" if idea["rank"] <= n else "backlog"
            conn.execute(
                "INSERT INTO ideas(id, project_id, rank, title, type, family, pitch, loop, metrics, reviews, score, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (idea_id, project_id, idea["rank"], idea["title"], idea["type"], idea["family"], idea["pitch"], json.dumps(idea["loop"], ensure_ascii=False),
                 json.dumps(idea["metrics"]), json.dumps(idea["reviews"], ensure_ascii=False), idea["score"], status),
            )
            if status == "shortlisted":
                self.create_line(conn, user_id, idea_id, automatic=True)
        self.log(conn, user_id, "IDEATION", f"{topic} · 아이디어 {len(ideas)}개 · 상위 {n}개 자동 shortlist · {len(ideas) - n}개 Backlog")
        return project_id

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
            if entry is None:
                continue
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
                if a.error_kind == "auth_error":
                    conn.execute("UPDATE provider_connections SET status='auth_required', last_error='auth_error' WHERE id=?", (a.connection_id,))
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
            self.message(conn, line_id, "handoff", failed[-1].name, attempts[-1].name, f"{failed[-1].error_kind} 발생으로 작업 인계", task_id)

    def execute(self, conn, user_id, line_id, task: dict, ctx: TaskContext, policy: str) -> tuple[str, str, str]:
        """Returns (text, connection_id, worker_name). Raises AllProvidersFailed when stuck."""
        team = self.employees(conn, user_id)
        rtask = routing.Task(kind=task["kind"], difficulty=task["difficulty"], critical=bool(task["critical"]))
        decision = routing.route(rtask, [e for e, _, _ in team], policy=policy)
        if not decision.ordered and task["kind"] in FALLBACK_KIND and team:
            capable_cooling = any(e.cooldown_until > _now().timestamp() and e.skills.get(task["kind"], 0) > 0 for e, _, _ in team)
            if not capable_cooling:
                sub = FALLBACK_KIND[task["kind"]]
                conn.execute("UPDATE tasks SET kind=?, substituted_from=? WHERE id=?", (sub, task["kind"], task["id"]))
                self.log(conn, user_id, "SUBSTITUTE", f"{task['name']} · {task['kind']} AI 없음 → {sub} 방식 대체", line_id)
                task = {**task, "kind": sub}
                ctx.kind = sub
                rtask.kind = sub
                decision = routing.route(rtask, [e for e, _, _ in team], policy=policy)
        by_id = {e.id: (row, entry) for e, row, entry in team}
        candidates = []
        for c in decision.ordered:
            row, entry = by_id[c.employee.id]
            try:
                candidates.append((c.employee.id, c.employee.name, self._adapter(conn, user_id, row, entry)))
            except (AdapterUnavailable, vault.VaultError, ValueError):
                continue
        request = build_prompt(ctx)
        if candidates:
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
        idea = conn.execute("SELECT i.*, p.platform FROM ideas i JOIN projects p ON p.id=i.project_id WHERE i.id=?", (line["idea_id"],)).fetchone()
        deps = conn.execute(
            "SELECT a.path, a.content FROM task_dependencies d JOIN artifacts a ON a.task_id=d.depends_on WHERE d.task_id=?", (task["id"],)
        ).fetchall()
        feedback = [r["text"] for r in conn.execute("SELECT text FROM feedback WHERE line_id=? ORDER BY created_at", (line["id"],)).fetchall()]
        return TaskContext(
            line_title=line["title"], topic=line["project_slug"], game_type=line["game_type"], family=line["family"], pitch=idea["pitch"],
            loop=json.loads(idea["loop"]), platform=idea["platform"] or "Web", stage_name=stage_def["name"], stage_summary=stage_def.get("summary", ""),
            task_name=task["name"], role=task["role"], kind=task["kind"], artifact=task["artifact"] or "notes.md",
            dependencies={r["path"]: r["content"] or "" for r in deps}, feedback=feedback,
        )

    def _spawn_repair(self, conn, stage_row, task):
        n = conn.execute("SELECT COUNT(*) FROM tasks WHERE stage_id=? AND repair_of=?", (stage_row["id"], task["id"])).fetchone()[0] // 2 + 1
        fix_id, retest_id = _id("tsk"), _id("tsk")
        conn.execute(
            "INSERT INTO tasks(id, line_id, stage_id, task_key, name, role, kind, difficulty, critical, artifact, status, repair_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fix_id, task["line_id"], stage_row["id"], f"{task['task_key']}-fix{n}", f"자동 수정: {task['name']}", "Gameplay Programmer", "debugging", 2, 0, f"fix-{task['task_key']}.patch", "ready", task["id"]),
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

    def _run_task(self, conn, user_id, line, stage_def, stage_row, task, policy):
        ctx = self._context(conn, line, stage_def, task)
        conn.execute("UPDATE tasks SET status='in_progress', attempts=attempts+1, started_at=? WHERE id=?", (_iso(), task["id"]))
        try:
            text, connection_id, worker = self.execute(conn, user_id, line["id"], dict(task), ctx, policy)
        except AllProvidersFailed:
            conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (task["id"],))
            self.log(conn, user_id, "BLOCKED", f"{line['title']} · {task['name']} 배정 가능한 AI 없음", line["id"])
            return
        path, body = to_file_content(task["artifact"] or "notes.md", text)
        files = {path: body}
        if task["artifact"] == "release/index.html":
            # P4 will replace this with model-written game code; the template keeps main playable.
            files[path] = games.render(self.catalog_dir, title=line["title"], topic=line["project_slug"], game_type=line["game_type"], family=line["family"])
            files["release/NOTES.md"] = text
        reviewer, reviewer_conn = None, None
        if task["kind"] == "coding":
            review_ctx = TaskContext(**{**ctx.__dict__, "task_name": f"diff 리뷰: {task['name']}", "role": "Technical Director", "kind": "qa",
                                         "artifact": "review.md", "dependencies": {path: files[path]}})
            review_task = {**dict(task), "kind": "debugging", "difficulty": 2, "critical": 0}
            _, reviewer_conn, reviewer = self.execute(conn, user_id, line["id"], review_task, review_ctx, policy)
            self.message(conn, line["id"], "review_request", worker, reviewer, "diff 검토", task["id"])
        ws = self.workspace(user_id, line["id"])
        ws.ensure(line["title"])
        branch = ws.branch_name(line["project_slug"], line["slug"], worker, stage_def["id"], task["task_key"])
        commit = ws.commit_task(branch=branch, files=files, message=f"{stage_def['id']}: {task['name']}", author=worker)
        verdict = qa_verdict(text) if task["kind"] in ("qa", "vision") and not task["repair_of"] else ("passed" if task["kind"] in ("qa", "vision") else ("tests_passed" if task["kind"] == "coding" else None))
        conn.execute(
            """UPDATE tasks SET status='completed', connection_id=?, worker_name=?, reviewer_connection_id=?, reviewer_name=?,
               branch=?, commit_sha=?, qa_status=?, finished_at=? WHERE id=?""",
            (None if connection_id == SIM_ID else connection_id, worker, None if reviewer_conn in (None, SIM_ID) else reviewer_conn, reviewer,
             branch, commit.sha, verdict, _iso(), task["id"]),
        )
        conn.execute("INSERT INTO artifacts(line_id, task_id, stage_key, path, content) VALUES (?,?,?,?,?)", (line["id"], task["id"], stage_def["id"], path, files[path][:200_000]))
        self.log(conn, user_id, "COMMIT", f"{line['title']} · {commit.sha[:7]} {branch} → main" + (f" (reviewed by {reviewer})" if reviewer else ""), line["id"])
        self.message(conn, line["id"], "result", worker, "Leader", f"{task['name']} 완료 · {path}", task["id"])
        if verdict == "failed":
            self.log(conn, user_id, "QA FAIL", f"{line['title']} · {task['name']} 실패 → 자동 수정 루프", line["id"])
            self._spawn_repair(conn, stage_row, task)

    def _complete_stage(self, conn, user_id, line, stage_def, stage_row):
        conn.execute("UPDATE stages SET status='completed', qa_status='passed', completed_at=? WHERE id=?", (_iso(), stage_row["id"]))
        self.log(conn, user_id, "STAGE COMPLETE", f"{line['title']} · {stage_def['name']} 통과", line["id"])
        if stage_def.get("build"):
            html = games.render(self.catalog_dir, title=line["title"], topic=line["project_slug"], game_type=line["game_type"], family=line["family"])
            smoke = games.smoke_test(html)
            ws = self.workspace(user_id, line["id"])
            ws.ensure(line["title"])
            sha = ws.commit_on_main({f"builds/v{stage_def['build']}/index.html": html}, f"build: v{stage_def['build']} ({stage_def['id']})", "Build Engineer")
            build_id = _id("bld")
            conn.execute("INSERT INTO builds(id, line_id, version, stage_key, platform, status, smoke, commit_sha) VALUES (?,?,?,?,?,?,?,?)",
                         (build_id, line["id"], stage_def["build"], stage_def["id"], "web", "playable" if smoke["passed"] else "failed", json.dumps(smoke), sha))
            conn.execute("INSERT INTO artifacts(line_id, stage_key, path, content) VALUES (?,?,?,?)", (line["id"], stage_def["id"], f"builds/v{stage_def['build']}/index.html", html))
            self.log(conn, user_id, "BUILD", f"{line['title']} v{stage_def['build']} · smoke {'통과' if smoke['passed'] else '실패'}", line["id"])
            if stage_def["id"] == "vertical" or stage_def.get("ceo_gate"):
                conn.execute("INSERT INTO reviews(id, line_id, build_id, kind, blocking, status) VALUES (?,?,?,?,?,'pending')",
                             (_id("rev"), line["id"], build_id, "release_candidate" if stage_def.get("ceo_gate") else "milestone", int(bool(stage_def.get("ceo_gate")))))
        if stage_def.get("ceo_gate"):
            conn.execute("UPDATE production_lines SET status='awaiting_ceo', leader_state='gate', leader_decision='릴리즈 빌드 CEO 승인 대기' WHERE id=?", (line["id"],))
            return
        self._advance(conn, user_id, line)

    def _advance(self, conn, user_id, line):
        if line["stage_index"] >= len(self.stages) - 1:
            conn.execute("UPDATE production_lines SET status='complete', leader_state='idle', leader_decision='전 공정 완료' WHERE id=?", (line["id"],))
            self.log(conn, user_id, "LINE COMPLETE", f"{line['title']} · 전 공정 완료", line["id"])
        else:
            conn.execute("UPDATE production_lines SET stage_index=stage_index+1 WHERE id=?", (line["id"],))

    def tick_line(self, conn, user_id, line_id) -> dict:
        """One Leader wave: execute up to workers_per_line ready tasks, then evaluate the gate."""
        line = conn.execute("SELECT * FROM production_lines WHERE id=? AND user_id=?", (line_id, user_id)).fetchone()
        if line is None:
            raise KeyError("line not found")
        if line["status"] != "running":
            return {"status": line["status"], "executed": 0}
        s = self.user_settings(conn, user_id)
        stage_def = self.stages[line["stage_index"]]
        stage_row = self._stage_row(conn, line_id, stage_def["id"])
        if stage_row is None:
            stage_row = self._instantiate(conn, line, stage_def)
        self._refresh(conn, stage_row["id"])
        ready = conn.execute("SELECT * FROM tasks WHERE stage_id=? AND status IN ('ready','blocked') ORDER BY rowid LIMIT ?", (stage_row["id"], s["workers_per_line"])).fetchall()
        for task in ready:
            conn.execute("UPDATE production_lines SET leader_state='dispatching', leader_decision=? WHERE id=?", (f"{stage_def['name']} · {task['name']} 배정", line_id))
            self._run_task(conn, user_id, line, stage_def, stage_row, task, s["policy"])
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
            if wave["status"] != "running":
                break
            stalled = stalled + 1 if wave["executed"] == 0 or wave.get("blocked") == wave["executed"] else 0
            if stalled >= 3:
                break
        return result

    # ------------------------------------------------------------------ CEO actions

    def add_feedback(self, conn, user_id, line_id, text) -> str:
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

    def approve(self, conn, user_id, review_id):
        review = conn.execute("SELECT r.*, l.user_id, l.status AS line_status FROM reviews r JOIN production_lines l ON l.id=r.line_id WHERE r.id=?", (review_id,)).fetchone()
        if review is None or review["user_id"] != user_id:
            raise KeyError("review not found")
        conn.execute("UPDATE reviews SET status='approved', reviewed_at=? WHERE id=?", (_iso(), review_id))
        self.log(conn, user_id, "CEO APPROVED", "출시 빌드 승인", review["line_id"])
        if review["blocking"] and review["line_status"] == "awaiting_ceo":
            conn.execute("UPDATE production_lines SET status='running' WHERE id=?", (review["line_id"],))
            line = conn.execute("SELECT * FROM production_lines WHERE id=?", (review["line_id"],)).fetchone()
            self._advance(conn, user_id, line)

    def request_revision(self, conn, user_id, review_id, note):
        review = conn.execute("SELECT r.*, l.user_id FROM reviews r JOIN production_lines l ON l.id=r.line_id WHERE r.id=?", (review_id,)).fetchone()
        if review is None or review["user_id"] != user_id:
            raise KeyError("review not found")
        conn.execute("UPDATE reviews SET status='revision_requested', note=?, reviewed_at=? WHERE id=?", (note, _iso(), review_id))
        self.add_feedback(conn, user_id, review["line_id"], note)
