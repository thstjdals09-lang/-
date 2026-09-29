from __future__ import annotations

import base64
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


MAX_FILES = 200
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
BLOCKED_FILE_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "service-account.json",
}
BLOCKED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


class GitHubPublishError(RuntimeError):
    """Safe, user-facing publishing failure without credential details."""


class GitHubAPIError(GitHubPublishError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class GitHubAPI(Protocol):
    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class GitHubClient:
    def __init__(self, token: str, api_url: str = "https://api.github.com"):
        if not token.strip():
            raise GitHubPublishError("AI_FACTORY_GITHUB_TOKEN is not configured")
        self._token = token
        self._api_url = api_url.rstrip("/")

    @classmethod
    def from_environment(cls) -> "GitHubClient":
        return cls(os.environ.get("AI_FACTORY_GITHUB_TOKEN", ""))

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._api_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "ai-factory-publisher",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = str(error_payload.get("message") or "GitHub API request failed")
            except (json.JSONDecodeError, UnicodeDecodeError):
                message = "GitHub API request failed"
            raise GitHubAPIError(exc.code, message) from exc

        if not body:
            return {}
        return json.loads(body.decode("utf-8"))


@dataclass(frozen=True)
class PublishResult:
    owner: str
    repository: str
    repository_url: str
    pages_url: str
    commit_sha: str
    status: str = "published"


def slugify_repository_name(game_name: str) -> str:
    normalized = unicodedata.normalize("NFC", game_name).strip().lower()
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = normalized.replace("_", "-").strip(".-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return (normalized or "ai-factory-game")[:80].rstrip(".-")


def validate_publish_files(files: Mapping[str, str]) -> dict[str, str]:
    if not files:
        raise GitHubPublishError("At least one game file is required")
    if len(files) > MAX_FILES:
        raise GitHubPublishError(f"A release can contain at most {MAX_FILES} files")

    validated: dict[str, str] = {}
    total_bytes = 0
    for raw_path, content in files.items():
        if not isinstance(raw_path, str) or not isinstance(content, str):
            raise GitHubPublishError("Game file paths and contents must be text")
        if "\\" in raw_path or raw_path.startswith("/"):
            raise GitHubPublishError(f"Unsafe release path: {raw_path}")

        path = PurePosixPath(raw_path)
        if not raw_path or any(part in {"", ".", "..", ".git"} for part in path.parts):
            raise GitHubPublishError(f"Unsafe release path: {raw_path}")

        lower_name = path.name.lower()
        if lower_name in BLOCKED_FILE_NAMES or path.suffix.lower() in BLOCKED_SUFFIXES:
            raise GitHubPublishError(f"Credential-like file is blocked: {raw_path}")

        encoded_size = len(content.encode("utf-8"))
        if encoded_size > MAX_FILE_BYTES:
            raise GitHubPublishError(f"Game file is too large: {raw_path}")
        total_bytes += encoded_size
        if total_bytes > MAX_TOTAL_BYTES:
            raise GitHubPublishError("Release exceeds the total publishing size limit")
        validated[path.as_posix()] = content

    if "index.html" not in validated:
        raise GitHubPublishError("GitHub Pages releases require index.html at the repository root")
    return dict(sorted(validated.items()))


class GitHubPublisher:
    def __init__(self, client: GitHubAPI, default_owner: str | None = None):
        self._client = client
        self._default_owner = default_owner or os.environ.get("AI_FACTORY_GITHUB_OWNER")

    @classmethod
    def from_environment(cls) -> "GitHubPublisher":
        return cls(GitHubClient.from_environment())

    def publish(
        self,
        *,
        game_name: str,
        files: Mapping[str, str],
        description: str = "Game generated by AI Factory",
        owner: str | None = None,
        private: bool = False,
    ) -> PublishResult:
        release_files = validate_publish_files(files)
        repository = slugify_repository_name(game_name)
        authenticated = self._client.request("GET", "/user")
        authenticated_login = str(authenticated["login"])
        target_owner = owner or self._default_owner or authenticated_login

        create_path = "/user/repos" if target_owner.lower() == authenticated_login.lower() else f"/orgs/{quote(target_owner)}/repos"
        try:
            repo_payload = self._client.request(
                "POST",
                create_path,
                {
                    "name": repository,
                    "description": description[:350],
                    "private": private,
                    "auto_init": False,
                    "has_issues": True,
                },
            )
        except GitHubAPIError as exc:
            if exc.status != 422:
                raise
            repo_payload = self._client.request(
                "GET",
                f"/repos/{quote(target_owner)}/{quote(repository)}",
            )

        repo_base = f"/repos/{quote(target_owner)}/{quote(repository)}"
        parent_sha: str | None = None
        try:
            ref_payload = self._client.request("GET", f"{repo_base}/git/ref/heads/main")
            parent_sha = str(ref_payload["object"]["sha"])
        except GitHubAPIError as exc:
            if exc.status != 404:
                raise

        tree_entries: list[dict[str, str]] = []
        for path, content in release_files.items():
            blob = self._client.request(
                "POST",
                f"{repo_base}/git/blobs",
                {
                    "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                },
            )
            tree_entries.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": str(blob["sha"])}
            )

        tree = self._client.request("POST", f"{repo_base}/git/trees", {"tree": tree_entries})
        commit_payload: dict[str, Any] = {
            "message": f"release: publish {game_name}",
            "tree": str(tree["sha"]),
        }
        if parent_sha:
            commit_payload["parents"] = [parent_sha]

        commit = self._client.request("POST", f"{repo_base}/git/commits", commit_payload)
        commit_sha = str(commit["sha"])
        if parent_sha:
            self._client.request(
                "PATCH",
                f"{repo_base}/git/refs/heads/main",
                {"sha": commit_sha, "force": False},
            )
        else:
            self._client.request(
                "POST",
                f"{repo_base}/git/refs",
                {"ref": "refs/heads/main", "sha": commit_sha},
            )

        try:
            pages = self._client.request(
                "POST",
                f"{repo_base}/pages",
                {"source": {"branch": "main", "path": "/"}, "build_type": "legacy"},
            )
        except GitHubAPIError as exc:
            if exc.status != 409:
                raise
            pages = self._client.request("GET", f"{repo_base}/pages")

        repository_url = str(repo_payload.get("html_url") or f"https://github.com/{target_owner}/{quote(repository)}")
        pages_url = str(pages.get("html_url") or f"https://{target_owner}.github.io/{quote(repository)}/")
        return PublishResult(
            owner=target_owner,
            repository=repository,
            repository_url=repository_url,
            pages_url=pages_url,
            commit_sha=commit_sha,
        )
