"""Confirms a GitHub Pages deployment is really reachable before the console links to it.

Pages takes a minute or two after a push; a link shown earlier answers 404. The verifier polls the
Pages build status and then the public URL, and only marks the publication `live` on HTTP 200.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import httpx

from .. import db
from ..github_publisher import GitHubAPIError
from .github_sync import GitHubSync, GitHubSyncError, RepoRef


def http_status(url: str, transport=None) -> int:
    try:
        with httpx.Client(timeout=15, follow_redirects=True, transport=transport) as client:
            return client.get(url, headers={"Cache-Control": "no-cache"}).status_code
    except httpx.HTTPError:
        return 0


class PagesVerifier:
    def __init__(self, github: GitHubSync, *, interval: float = 10, timeout: float = 420, background: bool = True,
                 probe: Callable[[str], int] | None = None, sleep: Callable[[float], None] = time.sleep):
        self.github = github
        self.interval = interval
        self.timeout = timeout
        self.background = background
        self.probe = probe or http_status
        self.sleep = sleep

    def watch(self, *, publication_id: str, user_id: str, line_id: str, title: str, ref: RepoRef, url: str, expect: str | None = None) -> None:
        job = lambda: self._run(publication_id, user_id, line_id, title, ref, url, expect)
        if self.background:
            threading.Thread(target=job, name="pages-verifier", daemon=True).start()
        else:
            job()

    def _update(self, publication_id, user_id, line_id, status, detail, log_type, text):
        conn = db.connect(autocommit=True)
        try:
            conn.execute("UPDATE publications SET status=?, detail=? WHERE id=?", (status, detail, publication_id))
            conn.execute("INSERT INTO factory_logs(user_id, line_id, type, text) VALUES (?,?,?,?)", (user_id, line_id, log_type, text))
        finally:
            conn.close()

    def _run(self, publication_id, user_id, line_id, title, ref, url, expect):
        deadline = time.monotonic() + self.timeout
        last = "queued"
        while time.monotonic() < deadline:
            try:
                build = self.github.pages_status(ref)
            except (GitHubSyncError, GitHubAPIError) as exc:
                build = {"status": "unknown", "error": str(exc)[:200]}
            last = build.get("status") or "unknown"
            if last == "errored":
                self._update(publication_id, user_id, line_id, "failed", build.get("error") or "GitHub Pages build errored",
                             "PUBLISH FAIL", f"{title} · GitHub Pages 빌드 오류")
                return
            fresh = not expect or not build.get("commit") or build["commit"].startswith(expect[:7]) or expect.startswith(build["commit"][:7])
            if last == "built" and fresh:
                code = self.probe(url)
                if code == 200:
                    self._update(publication_id, user_id, line_id, "live", None, "PAGES LIVE", f"{title} · 접속 확인 200 · {url}")
                    return
                last = f"built, HTTP {code}"
            self.sleep(self.interval)
        self._update(publication_id, user_id, line_id, "failed", f"not reachable after {int(self.timeout)}s (last: {last})",
                     "PUBLISH FAIL", f"{title} · Pages 접속 확인 실패 ({last})")
