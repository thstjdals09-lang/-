from app import db
from app.factory.api import get_factory

from .conftest import CSRF


def _setup(client):
    project = client.post("/projects", json={"topic": "좀비"}, headers=CSRF).json()["id"]
    line_id = client.get("/lines").json()[0]["id"]
    client.post(f"/lines/{line_id}/run", headers=CSRF, params={"max_waves": 6})
    return project, line_id


def _count(table, where="1=1", args=()):
    with db.transaction() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]


def test_delete_line_removes_its_work_and_returns_the_idea_to_backlog(signed_in):
    project, line_id = _setup(signed_in)
    detail = signed_in.get(f"/lines/{line_id}").json()
    idea_id = detail["ideaId"]
    ws = get_factory(signed_in.app).workspace(signed_in.get("/auth/me").json()["id"], line_id).root
    assert ws.exists() and _count("tasks", "line_id=?", (line_id,)) > 0

    res = signed_in.delete(f"/lines/{line_id}", headers=CSRF)
    assert res.status_code == 200
    assert signed_in.get(f"/lines/{line_id}").status_code == 404
    for table in ("tasks", "stages", "artifacts", "builds", "messages", "publications", "factory_logs"):
        assert _count(table, "line_id=?", (line_id,)) == 0, table
    assert not ws.exists()
    idea = next(i for i in signed_in.get(f"/projects/{project}/ideas").json() if i["id"] == idea_id)
    assert idea["status"] == "backlog"
    # the idea can be produced again later
    assert signed_in.post(f"/ideas/{idea_id}/build", headers=CSRF).status_code == 201


def test_delete_project_removes_ideas_and_all_lines(signed_in):
    project, _ = _setup(signed_in)
    other = signed_in.post("/projects", json={"topic": "홀덤"}, headers=CSRF)  # capacity: stays as backlog-only project
    assert signed_in.delete(f"/projects/{project}", headers=CSRF).json()["lines"] == 3
    assert _count("ideas", "project_id=?", (project,)) == 0
    assert all(l["projectId"] != project for l in signed_in.get("/lines").json())
    assert [p["id"] for p in signed_in.get("/projects").json()] == [other.json()["id"]]


def test_delete_idea_only_when_not_in_production(signed_in):
    project, _ = _setup(signed_in)
    ideas = signed_in.get(f"/projects/{project}/ideas").json()
    in_production = next(i for i in ideas if i["status"] == "in_production")
    backlog = next(i for i in ideas if i["status"] == "backlog")
    assert signed_in.delete(f"/ideas/{in_production['id']}", headers=CSRF).status_code == 409
    assert signed_in.delete(f"/ideas/{backlog['id']}", headers=CSRF).status_code == 200
    assert len(signed_in.get(f"/projects/{project}/ideas").json()) == len(ideas) - 1


def test_clear_logs_and_ownership(signed_in):
    project, line_id = _setup(signed_in)
    assert signed_in.delete("/logs", headers=CSRF).json()["deleted"] > 0
    assert signed_in.get("/logs").json() == []
    signed_in.post("/auth/logout", headers=CSRF)
    signed_in.post("/auth/dev-login", json={"email": "other@example.com"}, headers=CSRF)
    assert signed_in.delete(f"/lines/{line_id}", headers=CSRF).status_code == 404
    assert signed_in.delete(f"/projects/{project}", headers=CSRF).status_code == 404
    assert _count("production_lines", "id=?", (line_id,)) == 1
