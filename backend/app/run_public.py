"""Public factory from this PC: `python -m app.run_public` (used by start-public.cmd).

1. Opens a Cloudflare quick tunnel (no account needed) → https://<random>.trycloudflare.com
2. Runs the server behind it in public mode: email/password sign-up, local email login OFF,
   secure cookies, local AI endpoints reserved for the owner (AI_FACTORY_ADMIN_EMAILS).
3. Publishes the address to docs/backend.json so https://thstjdals09-lang.github.io/-/ forwards
   visitors to the running server.
The address changes on every start; the GitHub Pages link keeps working because it reads backend.json.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import envfile
from .run_local import ensure_env

PORT = 8000
REPO = Path(__file__).resolve().parents[2]
BACKEND_JSON = REPO / "docs" / "backend.json"
PAGES_ORIGIN = "https://thstjdals09-lang.github.io"
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared() -> str | None:
    for candidate in (shutil.which("cloudflared"), r"C:\Program Files (x86)\cloudflared\cloudflared.exe", r"C:\Program Files\cloudflared\cloudflared.exe"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def open_tunnel(binary: str) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen([binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    found: list[str] = []

    def pump():
        for line in proc.stdout:  # keep draining so cloudflared never blocks on a full pipe
            if not found:
                m = TUNNEL_RE.search(line)
                if m:
                    found.append(m.group(0))

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.time() + 90
    while not found and time.time() < deadline and proc.poll() is None:
        time.sleep(0.3)
    if not found:
        proc.terminate()
        raise SystemExit("[AI Factory] Cloudflare tunnel did not start (check the internet connection).")
    return proc, found[0]


def publish_address(url: str | None) -> None:
    """Commits docs/backend.json and pushes it so the GitHub Pages link can find this server."""
    BACKEND_JSON.write_text(json.dumps({"url": url, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n", encoding="utf-8")
    git = ["git", "-C", str(REPO)]
    try:
        subprocess.run(git + ["add", "docs/backend.json"], check=True, capture_output=True)
        subprocess.run(git + ["commit", "-q", "-m", "chore: update live backend address", "--", "docs/backend.json"], capture_output=True)
        res = subprocess.run(git + ["push", "-q", "origin", "HEAD:main"], capture_output=True, text=True)
        print("[AI Factory] link updated → " + PAGES_ORIGIN + "/-/ (GitHub Pages refreshes in about a minute)" if res.returncode == 0
              else "[AI Factory] could not push backend.json: " + res.stderr.strip()[:200])
    except (OSError, subprocess.CalledProcessError) as exc:
        print("[AI Factory] could not publish the address:", exc)


def main() -> None:
    ensure_env()
    binary = find_cloudflared()
    if not binary:
        raise SystemExit("[AI Factory] cloudflared is not installed: winget install Cloudflare.cloudflared")
    tunnel, url = open_tunnel(binary)
    os.environ.update({
        "AI_FACTORY_PUBLIC_URL": url,
        "AI_FACTORY_DEV_LOGIN": "false",
        "AI_FACTORY_COOKIE_SECURE": "true",
        "AI_FACTORY_COOKIE_SAMESITE": "lax",
        "AI_FACTORY_ALLOWED_ORIGINS": f"{url},{PAGES_ORIGIN},http://127.0.0.1:{PORT}",
    })
    envfile.load()  # the rest (vault key, admin emails, tokens) from backend/.env
    print(f"[AI Factory] public console: {url}/console/")
    print(f"[AI Factory] shareable link: {PAGES_ORIGIN}/-/  (forwards here while this window is open)")
    threading.Thread(target=publish_address, args=(url,), daemon=True).start()
    try:
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning", proxy_headers=True, forwarded_allow_ips="127.0.0.1")
    finally:
        tunnel.terminate()


if __name__ == "__main__":
    sys.exit(main())
