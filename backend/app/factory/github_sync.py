"""Publishes finished (CEO-approved) games to GitHub: one repository per line, one clean commit
per release, GitHub Pages for the play link. Work-in-progress task history stays on the server.

The server token (AI_FACTORY_GITHUB_TOKEN) reaches git only through GIT_CONFIG_* environment
variables as an HTTP header, so it never appears in process arguments, remote URLs or logs.
"""

from __future__ import annotations

import base64
import os
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote

from ..github_publisher import GitHubAPI, GitHubAPIError, GitHubClient
from ..vault import redact
from .workspace import LineWorkspace, WorkspaceError


class GitHubSyncError(RuntimeError):
    pass


@dataclass
class RepoRef:
    owner: str
    repo: str
    html_url: str


def repo_name(topic: str, line_slug: str, line_id: str) -> str:
    """ASCII-only repository name (GitHub rewrites other characters); stable per line. The `aif-`
    prefix keeps factory repositories apart from the owner's own projects."""
    def ascii_slug(value: str) -> str:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    suffix = re.sub(r"[^a-z0-9]", "", line_id.lower())[-6:] or "line"
    parts = [p for p in (ascii_slug(topic), ascii_slug(line_slug)) if p]
    return ("aif-" + "-".join(parts + [suffix]))[:90]


class GitHubSync:
    def __init__(self, client: GitHubAPI, token: str, owner: str | None = None, remote_template: str = "https://github.com/{owner}/{repo}.git"):
        self._client = client
        self._token = token
        self._owner = owner
        self._remote_template = remote_template

    @classmethod
    def from_environment(cls) -> "GitHubSync | None":
        token = os.environ.get("AI_FACTORY_GITHUB_TOKEN", "").strip()
        if not token:
            return None
        return cls(GitHubClient(token), token, os.environ.get("AI_FACTORY_GITHUB_OWNER") or None)

    def ensure_repo(self, name: str, description: str) -> RepoRef:
        """Creates a new repository. An existing repository with the same name is never reused:
        the factory only pushes to repositories it created itself."""
        login = str(self._client.request("GET", "/user")["login"])
        owner = self._owner or login
        create = "/user/repos" if owner.lower() == login.lower() else f"/orgs/{quote(owner)}/repos"
        try:
            payload = self._client.request("POST", create, {"name": name, "description": description[:350], "private": False, "auto_init": False})
        except GitHubAPIError as exc:
            if exc.status == 422:
                raise GitHubSyncError(f"repository {owner}/{name} already exists; refusing to push into a repository the factory did not create") from exc
            raise GitHubSyncError(f"repository create failed: {exc}") from exc
        return RepoRef(owner=owner, repo=name, html_url=str(payload.get("html_url") or f"https://github.com/{owner}/{name}"))

    def _remote(self, ref: RepoRef) -> tuple[str, str, dict]:
        url = self._remote_template.format(owner=ref.owner, repo=ref.repo)
        basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"}
        return url, basic, env

    def remote_head(self, ws: LineWorkspace, ref: RepoRef) -> str | None:
        """Tip of the published main branch (None for an empty repository), so the next release
        commit builds on it and the push stays a fast-forward."""
        url, basic, env = self._remote(ref)
        try:
            ws.git_env(env, "fetch", "--quiet", "--no-tags", url, "+refs/heads/main:refs/published/main")
        except WorkspaceError as exc:
            if "find remote ref" in str(exc).lower():
                return None
            raise GitHubSyncError(redact(str(exc), self._token, basic)) from exc
        return ws.rev("refs/published/main")

    def push(self, ws: LineWorkspace, ref: RepoRef, source: str = "main") -> str:
        url, basic, env = self._remote(ref)
        try:
            ws.git_env(env, "push", "--quiet", url, f"{source}:refs/heads/main")
        except WorkspaceError as exc:
            raise GitHubSyncError(redact(str(exc), self._token, basic)) from exc
        return ws.rev(source) or ws.head()

    def enable_pages(self, ref: RepoRef) -> str:
        base = f"/repos/{quote(ref.owner)}/{quote(ref.repo)}"
        try:
            pages = self._client.request("POST", f"{base}/pages", {"source": {"branch": "main", "path": "/"}, "build_type": "legacy"})
        except GitHubAPIError as exc:
            if exc.status != 409:
                raise GitHubSyncError(f"pages enable failed: {exc}") from exc
            pages = self._client.request("GET", f"{base}/pages")
        return str(pages.get("html_url") or f"https://{ref.owner}.github.io/{ref.repo}/")

    def pages_status(self, ref: RepoRef) -> dict:
        """Latest Pages build: {'status': built|building|queued|errored, 'commit': sha}."""
        base = f"/repos/{quote(ref.owner)}/{quote(ref.repo)}"
        try:
            build = self._client.request("GET", f"{base}/pages/builds/latest")
        except GitHubAPIError as exc:
            if exc.status == 404:
                return {"status": "queued"}
            raise GitHubSyncError(f"pages status failed: {exc}") from exc
        error = (build.get("error") or {}).get("message")
        return {"status": build.get("status"), "commit": build.get("commit"), "error": error}
