"""Server configuration read from the environment. Nothing here is ever sent to a browser."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip().rstrip("/") for x in os.environ.get(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    public_url: str
    allowed_origins: list[str]
    google_client_id: str
    google_client_secret: str
    cookie_secure: bool
    cookie_samesite: str
    session_days: int
    dev_login: bool
    catalog_dir: Path
    workspace_dir: Path
    simulate_without_providers: bool = True
    signup_mode: str = "open"  # open: any Google account can sign up · allowlist: only allowed_emails
    allowed_emails: list[str] = field(default_factory=list)
    admin_emails: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        host = self.public_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        return host in ("127.0.0.1", "localhost", "::1")

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_redirect_uri(self) -> str:
        return self.public_url.rstrip("/") + "/auth/google/callback"


def load() -> Settings:
    secure = _bool("AI_FACTORY_COOKIE_SECURE", True)
    repo_root = Path(__file__).resolve().parents[2]
    return Settings(
        public_url=os.environ.get("AI_FACTORY_PUBLIC_URL", "http://127.0.0.1:8000"),
        allowed_origins=_list(
            "AI_FACTORY_ALLOWED_ORIGINS",
            "https://thstjdals09-lang.github.io,http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5500,http://localhost:5500",
        ),
        google_client_id=os.environ.get("AI_FACTORY_GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.environ.get("AI_FACTORY_GOOGLE_CLIENT_SECRET", ""),
        cookie_secure=secure,
        cookie_samesite=os.environ.get("AI_FACTORY_COOKIE_SAMESITE", "none" if secure else "lax").lower(),
        session_days=int(os.environ.get("AI_FACTORY_SESSION_DAYS", "14")),
        dev_login=_bool("AI_FACTORY_DEV_LOGIN", False),
        catalog_dir=Path(os.environ.get("AI_FACTORY_CATALOG_DIR", str(repo_root / "docs" / "catalog"))),
        workspace_dir=Path(os.environ.get("AI_FACTORY_WORKSPACE", "data/workspaces")),
        simulate_without_providers=_bool("AI_FACTORY_SIMULATE", True),
        signup_mode=os.environ.get("AI_FACTORY_SIGNUP_MODE", "open").strip().lower(),
        allowed_emails=[e.lower() for e in _list("AI_FACTORY_ALLOWED_EMAILS", "")],
        admin_emails=[e.lower() for e in _list("AI_FACTORY_ADMIN_EMAILS", "")],
    )
