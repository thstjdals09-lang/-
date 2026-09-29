from __future__ import annotations

import base64

from app.github_publisher import (
    GitHubAPIError,
    GitHubPublishError,
    GitHubPublisher,
    slugify_repository_name,
    validate_publish_files,
)


class FakeGitHubClient:
    def __init__(self, *, existing: bool = False):
        self.existing = existing
        self.calls: list[tuple[str, str, dict | None]] = []
        self.blob_number = 0

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        self.calls.append((method, path, payload))
        if method == "GET" and path == "/user":
            return {"login": "factory-owner"}
        if method == "POST" and path == "/user/repos":
            if self.existing:
                raise GitHubAPIError(422, "name already exists")
            return {"html_url": "https://github.com/factory-owner/좀비-타이핑"}
        if method == "GET" and path.startswith("/repos/factory-owner/") and "/git/ref/" not in path and not path.endswith("/pages"):
            return {"html_url": "https://github.com/factory-owner/좀비-타이핑"}
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            if not self.existing:
                raise GitHubAPIError(404, "not found")
            return {"object": {"sha": "parent-sha"}}
        if method == "POST" and path.endswith("/git/blobs"):
            self.blob_number += 1
            return {"sha": f"blob-{self.blob_number}"}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": "tree-sha"}
        if method == "POST" and path.endswith("/git/commits"):
            return {"sha": "commit-sha"}
        if method in {"POST", "PATCH"} and (path.endswith("/git/refs") or path.endswith("/git/refs/heads/main")):
            return {}
        if method == "POST" and path.endswith("/pages"):
            if self.existing:
                raise GitHubAPIError(409, "already configured")
            return {"html_url": "https://factory-owner.github.io/좀비-타이핑/"}
        if method == "GET" and path.endswith("/pages"):
            return {"html_url": "https://factory-owner.github.io/좀비-타이핑/"}
        raise AssertionError(f"Unexpected request: {method} {path}")


def test_slugify_repository_name_keeps_game_name_and_normalizes_spacing():
    assert slugify_repository_name("  좀비 타이핑: Final!  ") == "좀비-타이핑-final"


def test_release_validation_blocks_credentials_and_requires_pages_entrypoint():
    try:
        validate_publish_files({"index.html": "ok", ".env": "SECRET=value"})
    except GitHubPublishError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("Expected credential-like file to be blocked")

    try:
        validate_publish_files({"README.md": "missing game"})
    except GitHubPublishError as exc:
        assert "index.html" in str(exc)
    else:
        raise AssertionError("Expected index.html to be required")


def test_publish_creates_commit_main_ref_and_pages_site():
    client = FakeGitHubClient()
    result = GitHubPublisher(client).publish(
        game_name="좀비 타이핑",
        files={"index.html": "<h1>Play</h1>", "assets/game.js": "console.log('ready')"},
    )

    assert result.repository == "좀비-타이핑"
    assert result.commit_sha == "commit-sha"
    assert result.pages_url == "https://factory-owner.github.io/좀비-타이핑/"

    calls = {(method, path) for method, path, _ in client.calls}
    assert ("POST", "/user/repos") in calls
    assert any(method == "POST" and path.endswith("/git/commits") for method, path in calls)
    assert any(method == "POST" and path.endswith("/git/refs") for method, path in calls)
    assert any(method == "POST" and path.endswith("/pages") for method, path in calls)

    blob_payloads = [payload for method, path, payload in client.calls if method == "POST" and path.endswith("/git/blobs")]
    decoded = {base64.b64decode(payload["content"]).decode("utf-8") for payload in blob_payloads}
    assert decoded == {"<h1>Play</h1>", "console.log('ready')"}


def test_publish_updates_existing_repository_with_non_force_push():
    client = FakeGitHubClient(existing=True)
    result = GitHubPublisher(client).publish(
        game_name="좀비 타이핑",
        files={"index.html": "<h1>Version 2</h1>"},
    )

    commit_payload = next(
        payload
        for method, path, payload in client.calls
        if method == "POST" and path.endswith("/git/commits")
    )
    ref_payload = next(
        payload
        for method, path, payload in client.calls
        if method == "PATCH" and path.endswith("/git/refs/heads/main")
    )
    assert commit_payload["parents"] == ["parent-sha"]
    assert ref_payload == {"sha": "commit-sha", "force": False}
    assert result.status == "published"
