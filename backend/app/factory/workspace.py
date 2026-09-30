"""Git workspace for a production line (P3).

Each line owns a repository whose `main` stays runnable. Every task runs in its own worktree on
`ai-factory/<project>/<line>/<agent>/<stage>-<task>`, commits there, is reviewed, then merged into
main with --no-ff, after which the worktree and branch are removed.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .ideation import slugify

GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}


class WorkspaceError(RuntimeError):
    pass


def _safe_relpath(path: str) -> Path:
    """Artifact paths come from model output: allow only plain relative paths inside the tree.
    (On Windows, Path('/x').is_absolute() is False, so anchors and drives are checked explicitly.)"""
    norm = str(path).replace("\\", "/")
    rel = PurePosixPath(norm)
    if not norm or norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in rel.parts or rel.parts[0] == ".git":
        raise WorkspaceError(f"unsafe artifact path: {path}")
    return Path(*rel.parts)


def _inside(root: Path, rel: str) -> Path:
    target = root / _safe_relpath(rel)
    if not target.resolve().is_relative_to(root.resolve()):
        raise WorkspaceError(f"unsafe artifact path: {rel}")
    return target


@dataclass
class TaskCommit:
    branch: str
    sha: str
    merged_sha: str


class LineWorkspace:
    def __init__(self, root: Path):
        # Absolute paths only: git resolves relative paths from its own cwd (the line repo), so a
        # relative worktree path would land somewhere else than where the files are written.
        self.root = Path(root).resolve()
        self.repo = self.root / "repo"
        self.trees = self.root / "wt"

    def _git(self, *args: str, cwd: Path | None = None, author: str = "AI Factory", extra_env: dict | None = None) -> str:
        # Never let git walk above the line folder into an enclosing repository (e.g. the factory's own).
        env = {**os.environ, **GIT_ENV, "GIT_CEILING_DIRECTORIES": str(self.root), **(extra_env or {})}
        cmd = ["git", "-c", f"user.name={author}", "-c", "user.email=ai-factory@localhost", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", *args]
        res = subprocess.run(cmd, cwd=cwd or self.repo, env=env, capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            detail = (res.stderr.strip() or res.stdout.strip())[:300]
            raise WorkspaceError(f"git {' '.join(args[:2])} failed: {detail}")
        return res.stdout.strip()

    def ensure(self, title: str) -> None:
        if (self.repo / ".git").exists():
            return
        self.repo.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q", "-b", "main")
        (self.repo / "README.md").write_text(f"# {title}\n\nProduced by AI Factory.\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".env\n*.key\nnode_modules/\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "chore: initialize production line")

    @staticmethod
    def branch_name(project: str, line: str, agent: str, stage: str, task: str) -> str:
        parts = [slugify(project), slugify(line), slugify(agent), f"{slugify(stage)}-{slugify(task)}"]
        return "ai-factory/" + "/".join(parts)

    def commit_task(self, *, branch: str, files: dict[str, str], message: str, author: str) -> TaskCommit:
        """Worktree → write → commit → merge into main → cleanup. Returns the task commit."""
        if not files:
            raise WorkspaceError("task produced no files")
        # Short directory names keep Windows paths (and git's worktree admin dir) under MAX_PATH.
        tree = self.trees / hashlib.sha1(branch.encode()).hexdigest()[:10]
        if tree.exists():
            shutil.rmtree(tree, ignore_errors=True)
            self._git("worktree", "prune")
        self.trees.mkdir(parents=True, exist_ok=True)
        if self._git("branch", "--list", branch):
            self._git("branch", "-D", branch)
        self._git("worktree", "add", "-q", "-b", branch, str(tree), "main")
        try:
            top = Path(self._git("rev-parse", "--show-toplevel", cwd=tree)).resolve()
            if top != tree.resolve():
                raise WorkspaceError(f"worktree mismatch: git is using {top}, expected {tree}")
            for rel, content in files.items():
                target = _inside(tree, rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            self._git("add", "-A", cwd=tree)
            # A task whose output equals what main already has still gets its own commit.
            self._git("commit", "-q", "--allow-empty", "-m", message, cwd=tree, author=author)
            sha = self._git("rev-parse", "HEAD", cwd=tree)
            self._git("merge", "-q", "--no-ff", "-X", "theirs", "-m", f"merge {branch}", branch, author="AI Factory Leader")
            merged = self._git("rev-parse", "HEAD")
        finally:
            self._git("worktree", "remove", "--force", str(tree))
        self._git("branch", "-D", branch)
        return TaskCommit(branch=branch, sha=sha, merged_sha=merged)

    def commit_on_main(self, files: dict[str, str | bytes], message: str, author: str) -> str:
        for rel, content in files.items():
            target = _inside(self.repo, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "--allow-empty", "-m", message, author=author)
        return self._git("rev-parse", "HEAD")

    def git_env(self, extra_env: dict, *args: str) -> str:
        """Runs git with extra environment (e.g. GIT_CONFIG_* credentials kept out of argv)."""
        return self._git(*args, extra_env=extra_env)

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def read_bytes(self, rel: str) -> bytes | None:
        path = self.repo / _safe_relpath(rel)
        return path.read_bytes() if path.is_file() else None

    def read(self, rel: str) -> str | None:
        path = self.repo / _safe_relpath(rel)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def log(self, limit: int = 20) -> list[str]:
        return self._git("log", f"-{limit}", "--format=%h %s").splitlines()

    def worktrees(self) -> list[str]:
        return [l for l in self._git("worktree", "list", "--porcelain").splitlines() if l.startswith("worktree ")]
