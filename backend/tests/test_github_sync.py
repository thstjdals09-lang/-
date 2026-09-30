import subprocess

import pytest

from app.factory.github_sync import GitHubSync, repo_name
from app.github_publisher import GitHubAPIError

from .conftest import CSRF

TOKEN = "ghp_supersecrettoken1234567890"


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.repos = set()

    def request(self, method, path, payload=None):
        self.calls.append((method, path))
        if path == "/user":
            return {"login": "ceo"}
        if method == "GET" and path.endswith("/pages/builds/latest"):
            return {"status": "built", "commit": None}
        if method == "POST" and path == "/user/repos":
            if payload["name"] in self.repos:
                raise GitHubAPIError(422, "exists")
            self.repos.add(payload["name"])
            return {"html_url": f"https://github.com/ceo/{payload['name']}"}
        if method == "GET" and path.startswith("/repos/") and not path.endswith("/pages"):
            return {"html_url": "https://github.com/" + path.removeprefix("/repos/")}
        if method == "POST" and path.endswith("/pages"):
            return {"html_url": "https://ceo.github.io/" + path.split("/")[3] + "/"}
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    return bare


def verifier_for(sync, status_code=200):
    from app.factory.pages_verifier import PagesVerifier

    return PagesVerifier(sync, interval=0, timeout=0.2, background=False, probe=lambda url: status_code, sleep=lambda s: None)


@pytest.fixture
def github(client, remote):
    sync = GitHubSync(FakeGitHub(), TOKEN, remote_template=str(remote))
    client.app.state.github_sync = sync
    client.app.state.pages_verifier = verifier_for(sync)
    return sync


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def test_repo_name_is_ascii_and_stable():
    assert repo_name("홀덤", "puzzle-strategy", "line_Ab12Cd34") == "aif-puzzle-strategy-12cd34"
    name = repo_name("zombie 타이핑", "arcade-score", "line_xyz987")
    assert name.isascii() and name.startswith("aif-zombie-arcade-score-")


def test_existing_repository_is_never_reused():
    from app.factory.github_sync import GitHubSyncError

    fake = FakeGitHub()
    fake.repos.add("steal-empire")
    with pytest.raises(GitHubSyncError, match="refusing"):
        GitHubSync(fake, TOKEN).ensure_repo("steal-empire", "x")
    assert not any(method == "POST" and "/git/" in path for method, path in fake.calls)


def _to_release(client, http):
    from .test_collaboration import _setup

    _setup(client, http)
    client.post("/projects", json={"topic": "zombie"}, headers=CSRF)
    line_id = client.get("/lines").json()[0]["id"]
    assert client.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "awaiting_ceo"
    return line_id


def _approve(client, line_id):
    review = next(r for r in client.get("/reviews").json() if r["line_id"] == line_id and r["blocking"] and r["status"] == "pending")
    assert client.post(f"/reviews/{review['id']}/approve", headers=CSRF).status_code == 200


def test_nothing_is_pushed_until_the_finished_game_is_approved(github, signed_in, remote, http):
    line_id = _to_release(signed_in, http)
    # a whole production run: no repository, no push, no Pages while the game is being made
    assert not any(m == "POST" for m, _ in github._client.calls)
    assert _git(remote, "for-each-ref") == ""
    detail = signed_in.get(f"/lines/{line_id}").json()
    assert detail["deployments"] == [] and detail["publication"] is None
    assert len(detail["builds"]) >= 5  # intermediate builds stay playable from the console

    _approve(signed_in, line_id)
    pub = signed_in.get(f"/lines/{line_id}").json()["publication"]
    assert pub["status"] == "live" and pub["kind"] == "release" and pub["version"] == "1.0.0"
    assert pub["pagesUrl"].startswith("https://ceo.github.io/aif-zombie-")
    assert "FROM-SCRATCH" in _git(remote, "show", "main:index.html") or "IMPROVED" in _git(remote, "show", "main:index.html")
    # one clean commit: the finished game, not the task history
    assert _git(remote, "log", "--format=%s", "main").splitlines() == [f"release: v1.0.0 {signed_in.get(f'/lines/{line_id}').json()['title']}"]
    files = set(_git(remote, "ls-tree", "--name-only", "main").split())
    assert {"index.html", "README.md"} <= files and not any(f.startswith(("builds", "src", "wt")) for f in files)
    assert "data-ai-factory-game" in _git(remote, "show", "main:index.html")
    assert TOKEN not in str(signed_in.get("/logs").json())


def test_a_revised_release_is_a_second_commit_on_the_same_repository(github, signed_in, remote, http):
    line_id = _to_release(signed_in, http)
    _approve(signed_in, line_id)
    assert signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "complete"
    assert signed_in.post(f"/lines/{line_id}/feedback", json={"text": "적 속도를 조금 낮춰줘"}, headers=CSRF).status_code == 201
    assert signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "awaiting_ceo"
    _approve(signed_in, line_id)
    log = _git(remote, "log", "--format=%s", "main").splitlines()
    assert len(log) == 2 and all(m.startswith("release: v1.0.0") for m in log)
    assert sum(1 for m, p in github._client.calls if m == "POST" and p == "/user/repos") == 1


def test_repository_from_the_old_flow_is_fast_forwarded(github, signed_in, remote, tmp_path, http):
    from app import db

    line_id = _to_release(signed_in, http)
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "old.txt").write_text("task history pushed by an earlier version", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "-m", "old history")
    _git(seed, "push", "-q", str(remote), "main:main")
    old = _git(remote, "rev-parse", "main").strip()
    with db.transaction() as conn:
        conn.execute("INSERT INTO publications(id, line_id, kind, status, repository, repository_url) VALUES ('pub_old', ?, 'repository', 'synced', 'ceo/aif-old', 'https://github.com/ceo/aif-old')", (line_id,))

    _approve(signed_in, line_id)
    assert signed_in.get(f"/lines/{line_id}").json()["publication"]["status"] == "live"
    assert _git(remote, "rev-parse", "main~1").strip() == old  # no force push: the old history is kept
    assert ("POST", "/user/repos") not in github._client.calls


def test_publish_failure_is_logged_without_the_token(client, signed_in, tmp_path, http):
    client.app.state.github_sync = GitHubSync(FakeGitHub(), TOKEN, remote_template=str(tmp_path / "missing.git"))
    line_id = _to_release(signed_in, http)
    _approve(signed_in, line_id)
    logs = signed_in.get("/logs").json()
    assert any(l["type"] == "PUBLISH FAIL" for l in logs)
    assert TOKEN not in str(logs)
    detail = signed_in.get(f"/lines/{line_id}").json()
    assert detail["publication"]["status"] == "failed" and detail["status"] == "running"


def test_publish_without_token_keeps_the_release_on_the_server(signed_in, http):
    from .test_collaboration import _setup

    _setup(signed_in, http)
    signed_in.post("/projects", json={"topic": "zombie"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    assert signed_in.post(f"/lines/{line_id}/publish", headers=CSRF).status_code == 409
    signed_in.post(f"/lines/{line_id}/run", headers=CSRF)
    res = signed_in.post(f"/lines/{line_id}/publish", headers=CSRF).json()
    assert res["status"] == "not_configured"
    assert signed_in.get(f"/lines/{line_id}").json()["publication"]["status"] == "not_configured"


def test_unreachable_pages_url_is_never_marked_live(client, signed_in, remote, http):
    sync = GitHubSync(FakeGitHub(), TOKEN, remote_template=str(remote))
    client.app.state.github_sync = sync
    client.app.state.pages_verifier = verifier_for(sync, status_code=404)
    line_id = _to_release(signed_in, http)
    _approve(signed_in, line_id)
    detail = signed_in.get(f"/lines/{line_id}").json()
    assert detail["deployments"][0]["status"] == "failed"
    assert "HTTP 404" in detail["deployments"][0]["detail"]
    assert any(l["type"] == "PUBLISH FAIL" for l in signed_in.get("/logs").json())
    # the release can be retried from the console after the approval
    assert signed_in.post(f"/lines/{line_id}/publish", headers=CSRF).status_code == 200


def test_the_emergency_template_is_never_published(github, signed_in, remote):
    # no AI connected: the simulated line ships the template game, which must not reach GitHub
    signed_in.post("/projects", json={"topic": "zombie"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    assert signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "awaiting_ceo"
    assert signed_in.post(f"/lines/{line_id}/publish", headers=CSRF).json()["status"] == "no_game"
    assert _git(remote, "for-each-ref") == ""
    assert any(l["type"] == "PUBLISH BLOCKED" for l in signed_in.get("/logs").json())
