"""My account: profile and usage, GitHub integration (per user), sessions, export and deletion."""

from __future__ import annotations

import json
import os
import shutil
import stat

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db, vault
from .auth import COOKIE, User, csrf_guard, current_user

router = APIRouter(prefix="/account", tags=["account"], dependencies=[Depends(csrf_guard)])

GITHUB_API = "https://api.github.com"


def remove_tree(path) -> None:
    """rmtree that also removes read-only files (git objects on Windows)."""
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if os.path.exists(path):
        shutil.rmtree(path, onexc=retry)


class GitHubToken(BaseModel):
    token: str = Field(min_length=10, max_length=500)


class DeleteAccount(BaseModel):
    confirm_email: str


def _counts(conn, user_id: str) -> dict:
    one = lambda sql: conn.execute(sql, (user_id,)).fetchone()[0]
    return {
        "ais": one("SELECT COUNT(*) FROM provider_connections WHERE user_id=?"),
        "ais_online": one("SELECT COUNT(*) FROM provider_connections WHERE user_id=? AND status='online'"),
        "projects": one("SELECT COUNT(*) FROM projects WHERE user_id=?"),
        "lines": one("SELECT COUNT(*) FROM production_lines WHERE user_id=?"),
        "running": one("SELECT COUNT(*) FROM production_lines WHERE user_id=? AND status='running'"),
        "builds": one("SELECT COUNT(*) FROM builds b JOIN production_lines l ON l.id=b.line_id WHERE l.user_id=?"),
        "deployed": one("SELECT COUNT(DISTINCT p.line_id) FROM publications p JOIN production_lines l ON l.id=p.line_id WHERE l.user_id=? AND p.status='live'"),
    }


def profile(conn, user_id: str) -> dict:
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return {
        "id": row["id"], "email": row["email"], "name": row["name"], "picture": row["picture"], "role": row["role"],
        "createdAt": row["created_at"], "lastLoginAt": row["last_login_at"],
        "signIn": "google" if row["google_sub"] else "local",
        "github": {"connected": bool(row["github_credential_id"]), "login": row["github_login"]},
        "counts": _counts(conn, user_id),
    }


@router.get("")
def get_account(user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        return profile(conn, user.id)


@router.put("/github")
def connect_github(payload: GitHubToken, request: Request, user: User = Depends(current_user)) -> dict:
    """Stores the user's own GitHub token in the vault after checking it with GitHub."""
    if not vault.configured():
        raise HTTPException(status_code=503, detail="vault_not_configured")
    token = payload.token.strip()
    try:
        with httpx.Client(timeout=15, transport=getattr(request.app.state, "http_transport", None)) as client:
            res = client.get(GITHUB_API + "/user", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="github_unreachable") from exc
    if res.status_code in (401, 403):
        raise HTTPException(status_code=400, detail="github_token_rejected")
    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"github_error_{res.status_code}")
    login = res.json().get("login")
    scopes = res.headers.get("x-oauth-scopes")  # classic tokens only; fine-grained tokens omit it
    if scopes is not None and "repo" not in [s.strip() for s in scopes.split(",")] and "public_repo" not in scopes:
        raise HTTPException(status_code=400, detail="github_token_needs_repo_scope")
    with db.transaction() as conn:
        old = conn.execute("SELECT github_credential_id FROM users WHERE id=?", (user.id,)).fetchone()["github_credential_id"]
        cred = vault.store(conn, user.id, token)
        conn.execute("UPDATE users SET github_credential_id=?, github_login=? WHERE id=?", (cred, login, user.id))
        if old:
            vault.delete(conn, user.id, old)
        conn.execute("INSERT INTO factory_logs(user_id, type, text) VALUES (?,?,?)", (user.id, "ACCOUNT", f"GitHub @{login} 연결 · 이후 게임은 이 계정에 배포"))
        return profile(conn, user.id)


@router.delete("/github")
def disconnect_github(user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        cred = conn.execute("SELECT github_credential_id FROM users WHERE id=?", (user.id,)).fetchone()["github_credential_id"]
        conn.execute("UPDATE users SET github_credential_id=NULL, github_login=NULL WHERE id=?", (user.id,))
        if cred:
            vault.delete(conn, user.id, cred)
        return profile(conn, user.id)


@router.post("/logout-all", status_code=204)
def logout_all(response: Response, request: Request, user: User = Depends(current_user)) -> Response:
    with db.transaction() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user.id,))
    s = request.app.state.settings
    response.delete_cookie(COOKIE, path="/", secure=s.cookie_secure, samesite=s.cookie_samesite)
    response.status_code = 204
    return response


@router.get("/export")
def export(user: User = Depends(current_user)) -> Response:
    """Everything the account owns, minus secrets (no keys, no ciphertext)."""
    with db.transaction() as conn:
        rows = lambda sql: [dict(r) for r in conn.execute(sql, (user.id,))]
        data = {
            "account": profile(conn, user.id),
            "ai_connections": rows("SELECT id, catalog_id, auth_type, endpoint, model, status, quota_unit, quota_limit, quota_used, last_verified, created_at FROM provider_connections WHERE user_id=?"),
            "projects": rows("SELECT * FROM projects WHERE user_id=?"),
            "ideas": rows("SELECT i.* FROM ideas i JOIN projects p ON p.id=i.project_id WHERE p.user_id=?"),
            "lines": rows("SELECT * FROM production_lines WHERE user_id=?"),
            "builds": rows("SELECT b.* FROM builds b JOIN production_lines l ON l.id=b.line_id WHERE l.user_id=?"),
            "publications": rows("SELECT p.* FROM publications p JOIN production_lines l ON l.id=p.line_id WHERE l.user_id=?"),
            "feedback": rows("SELECT * FROM feedback WHERE user_id=?"),
            "logs": rows("SELECT type, text, line_id, created_at FROM factory_logs WHERE user_id=? ORDER BY id"),
        }
    body = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return Response(body, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="ai-factory-account.json"'})


@router.delete("", status_code=204)
def delete_account(payload: DeleteAccount, request: Request, response: Response, user: User = Depends(current_user)) -> Response:
    """Deletes the account and everything it owns: keys, AIs, projects, lines, local game repositories.
    Repositories already pushed to the user's own GitHub stay in their GitHub account."""
    if payload.confirm_email.strip().lower() != user.email.lower():
        raise HTTPException(status_code=400, detail="confirmation_mismatch")
    from .factory.api import get_factory

    factory = get_factory(request.app)
    with db.transaction() as conn:
        line_ids = [r["id"] for r in conn.execute("SELECT id FROM production_lines WHERE user_id=?", (user.id,))]
        conn.execute("DELETE FROM users WHERE id=?", (user.id,))  # cascades to sessions, vault, AIs, projects, lines, logs
    for line_id in line_ids:
        root = factory.workspace(user.id, line_id).root
        remove_tree(root)
        if root.parent.exists() and not any(root.parent.iterdir()):
            root.parent.rmdir()
    s = request.app.state.settings
    response.delete_cookie(COOKIE, path="/", secure=s.cookie_secure, samesite=s.cookie_samesite)
    response.status_code = 204
    return response
