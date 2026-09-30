"""Runtime QA of generated games in an isolated headless browser (backend/runner/runtime-qa.mjs).

The game never runs inside the API process: a separate Node + Chromium process loads it offline
(all requests aborted) with a minimal environment that carries no server secrets, and is killed
on timeout. When Node or Playwright is unavailable the check reports `unavailable` instead of
pretending to pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "runner" / "runtime-qa.mjs"
PASSTHROUGH_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "HOME", "PLAYWRIGHT_BROWSERS_PATH", "XDG_CACHE_HOME")


def mode() -> str:
    return os.environ.get("AI_FACTORY_RUNTIME_QA", "auto").lower()


def _env() -> dict[str, str]:
    return {k: os.environ[k] for k in PASSTHROUGH_ENV if k in os.environ}


@lru_cache(maxsize=1)
def _probe() -> bool:
    node = shutil.which("node")
    if not node or not RUNNER.exists():
        return False
    try:
        res = subprocess.run([node, "-e", "import('playwright').then(()=>process.exit(0),()=>process.exit(1))"],
                             cwd=RUNNER.parent, env=_env(), capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def available() -> bool:
    return mode() != "off" and _probe()


def run(html: str, timeout: float = 60) -> dict:
    """Returns {"status": passed|failed|unavailable, "checks": [...], "errors": [...], "screenshot": bytes|None}."""
    if not available():
        return {"status": "unavailable", "checks": [], "errors": [], "screenshot": None}
    with tempfile.TemporaryDirectory(prefix="aif-qa-") as tmp:
        game = Path(tmp) / "game.html"
        shot = Path(tmp) / "shot.png"
        game.write_text(html, encoding="utf-8")
        try:
            res = subprocess.run([shutil.which("node"), str(RUNNER), str(game), str(shot)], cwd=RUNNER.parent, env=_env(),
                                 capture_output=True, text=True, encoding="utf-8", timeout=timeout)
            report = json.loads(res.stdout or "{}")
        except subprocess.TimeoutExpired:
            report = {"ok": False, "checks": [{"id": "timeout", "ok": False}], "errors": ["runtime QA timed out"]}
        except (ValueError, OSError) as exc:
            report = {"ok": False, "checks": [{"id": "runner", "ok": False}], "errors": [f"runner failed: {type(exc).__name__}"]}
        screenshot = shot.read_bytes() if shot.exists() else None
    return {
        "status": "passed" if report.get("ok") else "failed",
        "checks": report.get("checks", []),
        "errors": report.get("errors", []),
        "screenshot": screenshot,
    }
