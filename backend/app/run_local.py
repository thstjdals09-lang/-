"""One-click local factory: `python -m app.run_local` (used by start-backend.cmd).

Creates backend/.env on first run (fresh vault key, local-only login, same-origin console),
starts the server on 127.0.0.1 and opens the console when it answers.
"""

from __future__ import annotations

import threading
import time
import urllib.request
import webbrowser

from .envfile import ENV_PATH

HOST, PORT = "127.0.0.1", 8000
CONSOLE = f"http://{HOST}:{PORT}/console/"

LOCAL_ENV = """# Created by app.run_local for local use on this PC. Never commit this file.
AI_FACTORY_PUBLIC_URL=http://127.0.0.1:8000
AI_FACTORY_ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,https://thstjdals09-lang.github.io
AI_FACTORY_VAULT_KEY={vault_key}
# Local only: the console's Google button signs you in with an email prompt until Google OAuth is configured.
AI_FACTORY_DEV_LOGIN=true
AI_FACTORY_COOKIE_SECURE=false
AI_FACTORY_COOKIE_SAMESITE=lax
AI_FACTORY_DB=data/ai_factory.sqlite3
AI_FACTORY_WORKSPACE=data/workspaces
# Optional: Google login (OAuth client, redirect URI http://127.0.0.1:8000/auth/google/callback)
AI_FACTORY_GOOGLE_CLIENT_ID=
AI_FACTORY_GOOGLE_CLIENT_SECRET=
# Owner accounts: may connect this PC's local AIs on a public server and use the server GitHub token.
AI_FACTORY_ADMIN_EMAILS=
# Optional: GitHub token (repo scope) to create aif-* repositories and Pages links
AI_FACTORY_GITHUB_TOKEN=
"""


def ensure_env() -> bool:
    """Returns True when a new .env was created."""
    if ENV_PATH.exists():
        return False
    from .vault import generate_key

    ENV_PATH.write_text(LOCAL_ENV.format(vault_key=generate_key()), encoding="utf-8")
    return True


def _open_when_ready() -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=2) as res:
                if res.status == 200:
                    webbrowser.open(CONSOLE)
                    return
        except OSError:
            time.sleep(0.5)


def main() -> None:
    created = ensure_env()
    print(f"[AI Factory] {'created' if created else 'using'} {ENV_PATH}")
    print(f"[AI Factory] console: {CONSOLE}  (Ctrl+C to stop)")
    threading.Thread(target=_open_when_ready, daemon=True).start()
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
