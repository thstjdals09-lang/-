"""Factory HTTP API: projects, ideas, production lines, CEO reviews, logs and builds."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .. import db
from ..auth import User, csrf_guard, current_user
from ..connections import row_to_out
from .leader import DEFAULT_USER_SETTINGS, CapacityError, Factory, IdeaInProduction, LineBusy

router = APIRouter(tags=["factory"], dependencies=[Depends(csrf_guard)])


class ProjectCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=60)
    genre: str = Field(default="자동선택", max_length=40)
    platform: str = Field(default="Windows PC", max_length=40)
    notes: str = Field(default="", max_length=1000)


class SettingsPatch(BaseModel):
    policy: str | None = Field(default=None, pattern="^(cheapest_viable_quality|quality|speed|free)$")
    max_parallel: int | None = Field(default=None, ge=1, le=10)
    auto_shortlist: int | None = Field(default=None, ge=1, le=10)
    workers_per_line: int | None = Field(default=None, ge=1, le=8)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class Toggle(BaseModel):
    on: bool


def factory(request: Request) -> Factory:
    return get_factory(request.app)


def get_factory(app) -> Factory:
    if getattr(app.state, "factory", None) is None:
        s = app.state.settings
        app.state.factory = Factory(s.catalog_dir, s.workspace_dir, simulate=s.simulate_without_providers, transport=getattr(app.state, "http_transport", None),
                                    github=getattr(app.state, "github_sync", None),
                                    verifier=getattr(app.state, "pages_verifier", None))
    f = app.state.factory
    # Overrides set after startup (tests, single-tenant setups) must still apply to the cached factory.
    f.transport = getattr(app.state, "http_transport", None)
    f.github = getattr(app.state, "github_sync", None)
    f.verifier = getattr(app.state, "pages_verifier", None)
    return f


def _owned_line(conn, user_id, line_id):
    row = conn.execute("SELECT * FROM production_lines WHERE id=? AND user_id=?", (line_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="line_not_found")
    return row


def _progress(f: Factory, conn, line) -> int:
    if line["status"] == "complete":
        return 100
    key = f.stages[line["stage_index"]]["id"]
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(t.status='completed') AS done FROM tasks t JOIN stages s ON s.id=t.stage_id WHERE s.line_id=? AND s.stage_key=?",
        (line["id"], key),
    ).fetchone()
    frac = (row["done"] or 0) / row["total"] if row["total"] else 0
    return round((line["stage_index"] + frac) / len(f.stages) * 100)


def _topic(conn, project_id) -> str:
    row = conn.execute("SELECT topic FROM projects WHERE id=?", (project_id,)).fetchone()
    return row["topic"] if row else ""


def line_summary(f: Factory, conn, line) -> dict:
    stage = f.stages[line["stage_index"]]
    return {
        "id": line["id"], "projectId": line["project_id"], "ideaId": line["idea_id"], "topic": _topic(conn, line["project_id"]),
        "title": line["title"], "status": line["status"], "family": line["family"], "gameType": line["game_type"],
        "stageIndex": line["stage_index"], "stage": stage["id"], "stageName": stage["name"], "progress": _progress(f, conn, line),
        "autopilot": bool(line["autopilot"]), "leader": {"state": line["leader_state"], "lastDecision": line["leader_decision"]},
    }


def line_detail(f: Factory, conn, line) -> dict:
    stages = {}
    for srow in conn.execute("SELECT * FROM stages WHERE line_id=?", (line["id"],)).fetchall():
        tasks = []
        for t in conn.execute("SELECT * FROM tasks WHERE stage_id=? ORDER BY rowid", (srow["id"],)).fetchall():
            deps = [r["task_key"] for r in conn.execute("SELECT p.task_key FROM task_dependencies d JOIN tasks p ON p.id=d.depends_on WHERE d.task_id=?", (t["id"],))]
            tasks.append({
                "id": t["task_key"], "name": t["name"], "role": t["role"], "kind": t["kind"], "difficulty": t["difficulty"], "critical": bool(t["critical"]),
                "depends": deps, "artifact": t["artifact"], "status": t["status"], "attempts": t["attempts"],
                "assignee": {"name": t["worker_name"], "connectionId": t["connection_id"]} if t["worker_name"] else None,
                "reviewer": {"name": t["reviewer_name"]} if t["reviewer_name"] else None,
                "branch": t["branch"], "commit": t["commit_sha"], "qa": t["qa_status"], "substituted": t["substituted_from"], "repairOf": t["repair_of"],
            })
        stages[srow["stage_key"]] = {"status": srow["status"], "qa": {"status": srow["qa_status"]}, "startedAt": srow["started_at"], "completedAt": srow["completed_at"], "tasks": tasks}
    commits = [
        {"sha": r["commit_sha"], "branch": r["branch"], "message": f"{r['stage_key']}: {r['name']}", "author": r["worker_name"], "reviewer": r["reviewer_name"], "time": r["finished_at"]}
        for r in conn.execute(
            "SELECT t.*, s.stage_key FROM tasks t JOIN stages s ON s.id=t.stage_id WHERE t.line_id=? AND t.commit_sha IS NOT NULL ORDER BY t.finished_at DESC, t.rowid DESC LIMIT 60",
            (line["id"],),
        )
    ]
    builds = [
        {"id": b["id"], "version": b["version"], "stageId": b["stage_key"], "status": b["status"], "smoke": json.loads(b["smoke"]), "commit": b["commit_sha"],
         "runtime": b["runtime_status"], "screenshot": bool(b["screenshot"]), "createdAt": b["created_at"]}
        for b in conn.execute("SELECT * FROM builds WHERE line_id=? ORDER BY created_at DESC, rowid DESC", (line["id"],))
    ]
    messages = [
        {"type": m["type"], "from": m["sender"], "to": m["recipient"], "taskId": m["task_id"], "text": json.loads(m["payload"]).get("text"), "time": m["created_at"]}
        for m in conn.execute("SELECT * FROM messages WHERE line_id=? ORDER BY id DESC LIMIT 40", (line["id"],))
    ]
    feedback = [dict(r) for r in conn.execute("SELECT id, text, stage_key, status, created_at FROM feedback WHERE line_id=? ORDER BY created_at DESC", (line["id"],))]
    artifacts = [{"name": a["path"], "stageId": a["stage_key"]} for a in conn.execute("SELECT path, stage_key FROM artifacts WHERE line_id=? ORDER BY id", (line["id"],))]
    pubs = conn.execute("SELECT * FROM publications WHERE line_id=? ORDER BY created_at DESC, rowid DESC", (line["id"],)).fetchall()
    as_dict = lambda p: {"kind": p["kind"], "status": p["status"], "version": p["version"], "repositoryUrl": p["repository_url"], "pagesUrl": p["pages_url"],
                         "commit": p["commit_sha"], "detail": p["detail"], "time": p["created_at"]}
    deployments = [as_dict(p) for p in pubs if p["kind"] in ("pages", "release")]
    live = next((d for d in deployments if d["status"] == "live"), None)
    publication = live or (deployments[0] if deployments else (as_dict(pubs[0]) if pubs else None))
    if publication and live and deployments and deployments[0] is not live:
        publication = {**live, "next": deployments[0]}  # newer build still deploying/failed
    return {**line_summary(f, conn, line), "publication": publication, "deployments": deployments[:10], "stages": stages, "commits": commits, "builds": builds, "messages": messages, "feedback": feedback, "artifacts": artifacts}


# ---------------------------------------------------------------- settings / dashboard

@router.get("/settings")
def get_settings(request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        return factory(request).user_settings(conn, user.id)


@router.patch("/settings")
def patch_settings(payload: SettingsPatch, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        current = factory(request).user_settings(conn, user.id)
        current.update({k: v for k, v in payload.model_dump().items() if v is not None})
        if not request.app.state.settings.is_local and user.role != "admin":
            # shared server: keep one member from occupying every worker
            current["max_parallel"] = min(current["max_parallel"], 3)
            current["workers_per_line"] = min(current["workers_per_line"], 3)
        stored = {k: current[k] for k in DEFAULT_USER_SETTINGS}
        conn.execute("UPDATE users SET settings=? WHERE id=?", (json.dumps(stored), user.id))
        return stored


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(current_user)) -> dict:
    f = factory(request)
    with db.transaction() as conn:
        lines = conn.execute("SELECT * FROM production_lines WHERE user_id=? ORDER BY created_at", (user.id,)).fetchall()
        failovers = conn.execute("SELECT COUNT(*) FROM factory_logs WHERE user_id=? AND type='FAILOVER'", (user.id,)).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM reviews r JOIN production_lines l ON l.id=r.line_id WHERE l.user_id=? AND r.status='pending'", (user.id,)).fetchone()[0]
        builds = conn.execute("SELECT COUNT(*), SUM(b.status='playable') FROM builds b JOIN production_lines l ON l.id=b.line_id WHERE l.user_id=?", (user.id,)).fetchone()
        return {
            "lines": [line_summary(f, conn, l) for l in lines],
            "running": sum(1 for l in lines if l["status"] == "running"),
            "failovers": failovers,
            "pendingReviews": pending,
            "builds": {"total": builds[0], "playable": builds[1] or 0},
        }


# ---------------------------------------------------------------- projects / ideas

@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreate, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        project_id = factory(request).create_project(conn, user.id, **payload.model_dump())
        return {"id": project_id}


@router.get("/projects")
def list_projects(user: User = Depends(current_user)) -> list[dict]:
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute("SELECT id, topic, genre, platform, notes, created_at FROM projects WHERE user_id=? ORDER BY created_at DESC", (user.id,))]


@router.get("/projects/{project_id}/ideas")
def list_ideas(project_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=? AND user_id=?", (project_id, user.id)).fetchone():
            raise HTTPException(status_code=404, detail="project_not_found")
        rows = conn.execute("SELECT * FROM ideas WHERE project_id=? ORDER BY rank", (project_id,)).fetchall()
        return [{**dict(r), "loop": json.loads(r["loop"]), "metrics": json.loads(r["metrics"]), "reviews": json.loads(r["reviews"]),
             "concept": json.loads(r["concept"]) if r["concept"] else None} for r in rows]


@router.post("/ideas/{idea_id}/build", status_code=201)
def build_idea(idea_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        try:
            return {"lineId": factory(request).start_idea(conn, user.id, idea_id)}
        except CapacityError as exc:
            raise HTTPException(status_code=409, detail="capacity") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="idea_not_found") from exc


# ---------------------------------------------------------------- lines

@router.get("/lines")
def list_lines(request: Request, user: User = Depends(current_user)) -> list[dict]:
    f = factory(request)
    with db.transaction() as conn:
        return [line_summary(f, conn, l) for l in conn.execute("SELECT * FROM production_lines WHERE user_id=? ORDER BY created_at", (user.id,))]


@router.get("/lines/{line_id}")
def get_line(line_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    f = factory(request)
    with db.transaction() as conn:
        return line_detail(f, conn, _owned_line(conn, user.id, line_id))


@router.post("/lines/{line_id}/tick")
def tick(line_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        _owned_line(conn, user.id, line_id)
        return factory(request).tick_line(conn, user.id, line_id)


@router.post("/lines/{line_id}/run")
def run(line_id: str, request: Request, user: User = Depends(current_user), max_waves: int = Query(default=200, ge=1, le=500)) -> dict:
    with db.transaction() as conn:
        _owned_line(conn, user.id, line_id)
        return factory(request).run_line(conn, user.id, line_id, max_waves=max_waves)


@router.post("/lines/{line_id}/autopilot")
def autopilot(line_id: str, payload: Toggle, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        _owned_line(conn, user.id, line_id)
        conn.execute("UPDATE production_lines SET autopilot=? WHERE id=?", (int(payload.on), line_id))
        return {"autopilot": payload.on}


@router.post("/lines/{line_id}/publish")
def publish(line_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        line = _owned_line(conn, user.id, line_id)
        if line["status"] not in ("awaiting_ceo", "complete"):
            raise HTTPException(status_code=409, detail="release_not_ready")
        return factory(request).publish_release(conn, user.id, line_id)


@router.post("/lines/{line_id}/feedback", status_code=201)
def feedback(line_id: str, payload: TextIn, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        _owned_line(conn, user.id, line_id)
        try:
            return {"id": factory(request).add_feedback(conn, user.id, line_id, payload.text)}
        except LineBusy as exc:
            raise HTTPException(status_code=409, detail="line_busy") from exc


# ---------------------------------------------------------------- reviews / builds / logs

@router.delete("/lines/{line_id}")
def delete_line(line_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        _owned_line(conn, user.id, line_id)
        try:
            return factory(request).delete_line(conn, user.id, line_id)
        except LineBusy as exc:
            raise HTTPException(status_code=409, detail="line_busy") from exc


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        try:
            return factory(request).delete_project(conn, user.id, project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project_not_found") from exc
        except LineBusy as exc:
            raise HTTPException(status_code=409, detail="line_busy") from exc


@router.delete("/ideas/{idea_id}")
def delete_idea(idea_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        try:
            return factory(request).delete_idea(conn, user.id, idea_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="idea_not_found") from exc
        except IdeaInProduction as exc:
            raise HTTPException(status_code=409, detail="idea_in_production") from exc


@router.delete("/logs")
def clear_logs(user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        n = conn.execute("DELETE FROM factory_logs WHERE user_id=?", (user.id,)).rowcount
        return {"deleted": n}


@router.get("/reviews")
def list_reviews(user: User = Depends(current_user)) -> list[dict]:
    with db.transaction() as conn:
        rows = conn.execute(
            """SELECT r.*, l.title, b.version, b.smoke FROM reviews r JOIN production_lines l ON l.id=r.line_id JOIN builds b ON b.id=r.build_id
               WHERE l.user_id=? ORDER BY r.created_at DESC""",
            (user.id,),
        ).fetchall()
        return [{**dict(r), "blocking": bool(r["blocking"]), "smoke": json.loads(r["smoke"])} for r in rows]


@router.post("/reviews/{review_id}/approve")
def approve(review_id: str, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        try:
            factory(request).approve(conn, user.id, review_id)
        except LineBusy as exc:
            raise HTTPException(status_code=409, detail="line_busy") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review_not_found") from exc
    return {"status": "approved"}


@router.post("/reviews/{review_id}/revise")
def revise(review_id: str, payload: TextIn, request: Request, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        try:
            factory(request).request_revision(conn, user.id, review_id, payload.text)
        except LineBusy as exc:
            raise HTTPException(status_code=409, detail="line_busy") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review_not_found") from exc
    return {"status": "revision_requested"}


@router.get("/builds/{build_id}/play", response_class=HTMLResponse)
def play_build(build_id: str, user: User = Depends(current_user)) -> HTMLResponse:
    with db.transaction() as conn:
        row = conn.execute(
            """SELECT a.content FROM builds b JOIN production_lines l ON l.id=b.line_id
               JOIN artifacts a ON a.line_id=b.line_id AND a.path='builds/v' || b.version || '/index.html'
               WHERE b.id=? AND l.user_id=? ORDER BY a.id DESC LIMIT 1""",
            (build_id, user.id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="build_not_found")
    # Generated code runs in an opaque sandboxed origin: no cookies, no same-origin API access.
    headers = {"Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:", "X-Content-Type-Options": "nosniff"}
    return HTMLResponse(row["content"], headers=headers)


@router.get("/builds/{build_id}/screenshot.png")
def build_screenshot(build_id: str, request: Request, user: User = Depends(current_user)) -> Response:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT b.screenshot, b.line_id FROM builds b JOIN production_lines l ON l.id=b.line_id WHERE b.id=? AND l.user_id=?", (build_id, user.id)
        ).fetchone()
    if row is None or not row["screenshot"]:
        raise HTTPException(status_code=404, detail="screenshot_not_found")
    data = factory(request).workspace(user.id, row["line_id"]).read_bytes(row["screenshot"])
    if data is None:
        raise HTTPException(status_code=404, detail="screenshot_not_found")
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.get("/logs")
def logs(user: User = Depends(current_user), limit: int = Query(default=200, ge=1, le=1000), line_id: str | None = None) -> list[dict]:
    with db.transaction() as conn:
        if line_id:
            rows = conn.execute("SELECT * FROM factory_logs WHERE user_id=? AND line_id=? ORDER BY id DESC LIMIT ?", (user.id, line_id, limit))
        else:
            rows = conn.execute("SELECT * FROM factory_logs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user.id, limit))
        return [dict(r) for r in rows]


@router.get("/state")
def state(request: Request, user: User = Depends(current_user)) -> dict:
    """Everything the web console renders, in one round trip."""
    f = factory(request)
    with db.transaction() as conn:
        projects = [dict(r) for r in conn.execute("SELECT id, topic, genre, platform, notes, created_at FROM projects WHERE user_id=? ORDER BY created_at DESC", (user.id,))]
        ideas = [
            {**dict(r), "loop": json.loads(r["loop"]), "metrics": json.loads(r["metrics"]), "reviews": json.loads(r["reviews"]),
             "concept": json.loads(r["concept"]) if r["concept"] else None}
            for r in conn.execute("SELECT i.* FROM ideas i JOIN projects p ON p.id=i.project_id WHERE p.user_id=? ORDER BY p.created_at DESC, i.rank", (user.id,))
        ]
        lines = [line_detail(f, conn, l) for l in conn.execute("SELECT * FROM production_lines WHERE user_id=? ORDER BY created_at", (user.id,))]
        reviews = [
            {**dict(r), "blocking": bool(r["blocking"]), "smoke": json.loads(r["smoke"])}
            for r in conn.execute(
                """SELECT r.*, l.title, b.version, b.stage_key, b.smoke FROM reviews r JOIN production_lines l ON l.id=r.line_id JOIN builds b ON b.id=r.build_id
                   WHERE l.user_id=? ORDER BY r.created_at DESC""",
                (user.id,),
            )
        ]
        logs = [dict(r) for r in conn.execute("SELECT * FROM factory_logs WHERE user_id=? ORDER BY id DESC LIMIT 300", (user.id,))]
        counters = {row["type"]: row["n"] for row in conn.execute("SELECT type, COUNT(*) AS n FROM factory_logs WHERE user_id=? GROUP BY type", (user.id,))}
        connections = [row_to_out(conn, r).model_dump() for r in conn.execute("SELECT * FROM provider_connections WHERE user_id=? ORDER BY created_at", (user.id,))]
        return {
            "settings": f.user_settings(conn, user.id),
            "projects": projects, "ideas": ideas, "lines": lines, "reviews": reviews, "logs": logs, "connections": connections,
            "counters": {"failovers": counters.get("FAILOVER", 0), "quotaWarnings": counters.get("QUOTA WARNING", 0), "tasksDone": counters.get("COMMIT", 0)},
        }
