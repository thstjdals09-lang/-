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


@pytest.fixture
def github(client, remote):
    sync = GitHubSync(FakeGitHub(), TOKEN, remote_template=str(remote))
    client.app.state.github_sync = sync
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


def test_line_history_is_mirrored_and_release_published(github, signed_in, remote):
    signed_in.post("/projects", json={"topic": "zombie"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    assert signed_in.post(f"/lines/{line_id}/run", headers=CSRF).json()["status"] == "awaiting_ceo"

    log = _git(remote, "log", "--oneline", "main")
    assert len(log.splitlines()) > 50 and "merge ai-factory/" in log
    detail = signed_in.get(f"/lines/{line_id}").json()
    assert detail["publication"]["status"] == "synced"

    review = next(r for r in signed_in.get("/reviews").json() if r["line_id"] == line_id and r["blocking"])
    signed_in.post(f"/reviews/{review['id']}/approve", headers=CSRF)
    pub = signed_in.get(f"/lines/{line_id}").json()["publication"]
    assert pub["status"] == "published" and pub["pagesUrl"].startswith("https://ceo.github.io/")
    assert "data-ai-factory-game" in _git(remote, "show", "main:index.html")
    assert "release: publish" in _git(remote, "log", "-1", "--format=%s", "main")
    assert TOKEN not in str(signed_in.get("/logs").json())


def test_sync_failure_is_logged_without_the_token(client, signed_in, tmp_path):
    client.app.state.github_sync = GitHubSync(FakeGitHub(), TOKEN, remote_template=str(tmp_path / "missing.git"))
    signed_in.post("/projects", json={"topic": "zombie"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    signed_in.post(f"/lines/{line_id}/run", headers=CSRF, params={"max_waves": 3})
    logs = signed_in.get("/logs").json()
    assert any(l["type"] == "GITHUB SYNC FAIL" for l in logs)
    assert TOKEN not in str(logs) and signed_in.get(f"/lines/{line_id}").json()["status"] == "running"


def test_publish_without_token_commits_release_locally(signed_in):
    signed_in.post("/projects", json={"topic": "zombie"}, headers=CSRF)
    line_id = signed_in.get("/lines").json()[0]["id"]
    assert signed_in.post(f"/lines/{line_id}/publish", headers=CSRF).status_code == 409
    signed_in.post(f"/lines/{line_id}/run", headers=CSRF)
    res = signed_in.post(f"/lines/{line_id}/publish", headers=CSRF).json()
    assert res["status"] == "not_configured"
    assert signed_in.get(f"/lines/{line_id}").json()["publication"]["status"] == "not_configured"
