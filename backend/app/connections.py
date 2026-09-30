"""Provider connections: install an adapter for a user, store its credential in the vault,
verify it (health_check → list_models → quota_probe) and expose only safe metadata."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import catalog, db, vault
from .auth import User, csrf_guard, current_user, pkce_pair, safe_return_to
from .providers import AdapterUnavailable, ProviderAdapter, ProviderError, build_adapter

router = APIRouter(prefix="/providers", tags=["providers"], dependencies=[Depends(csrf_guard)])


class ConnectionCreate(BaseModel):
    catalog_id: str = Field(min_length=1, max_length=64)
    auth_type: str
    api_key: str | None = Field(default=None, max_length=4096)
    endpoint: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    reserve: float | None = Field(default=None, ge=0, le=0.9)


class ConnectionOut(BaseModel):
    id: str
    catalog_id: str
    auth_type: str
    credential_ref: str | None
    credential_fingerprint: str | None
    endpoint: str | None
    model: str | None
    status: str
    reserve: float | None
    quota_unit: str | None
    quota_limit: float | None
    quota_used: float
    quota_reset_at: str | None
    models: list[str]
    last_verified: str | None
    last_error: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def next_reset(window: str | None, now: datetime) -> datetime | None:
    if window == "day":
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)
    if window == "month":
        return datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=timezone.utc)
    return None


def row_to_out(conn: sqlite3.Connection, row: sqlite3.Row) -> ConnectionOut:
    fp = None
    if row["credential_id"]:
        cred = conn.execute("SELECT fingerprint FROM encrypted_credentials WHERE id = ?", (row["credential_id"],)).fetchone()
        fp = cred["fingerprint"] if cred else None
    return ConnectionOut(
        id=row["id"], catalog_id=row["catalog_id"], auth_type=row["auth_type"],
        credential_ref=vault.reference(row["credential_id"]), credential_fingerprint=fp,
        endpoint=row["endpoint"], model=row["model"], status=row["status"], reserve=row["reserve"],
        quota_unit=row["quota_unit"], quota_limit=row["quota_limit"], quota_used=row["quota_used"],
        quota_reset_at=row["quota_reset_at"], models=json.loads(row["models"] or "[]"),
        last_verified=row["last_verified"], last_error=row["last_error"],
    )


def adapter_for(conn: sqlite3.Connection, user_id: str, row: sqlite3.Row, entry: dict, transport=None) -> ProviderAdapter:
    secret = vault.reveal(conn, user_id, row["credential_id"]) if row["credential_id"] else None
    return build_adapter(entry, secret=secret, endpoint=row["endpoint"], model=row["model"], transport=transport)


def verify(conn: sqlite3.Connection, user_id: str, row: sqlite3.Row, entry: dict, transport=None) -> None:
    """health_check + quota_probe; updates status, models, quota and last_verified."""
    try:
        adapter = adapter_for(conn, user_id, row, entry, transport)
    except AdapterUnavailable as exc:
        conn.execute("UPDATE provider_connections SET status='offline', last_error=? WHERE id=?", (str(exc), row["id"]))
        return
    health = adapter.health_check()
    if not health.ok:
        status = "auth_required" if "HTTP 401" in (health.detail or "") or "HTTP 403" in (health.detail or "") else "offline"
        conn.execute("UPDATE provider_connections SET status=?, last_error=? WHERE id=?", (status, (health.detail or "")[:300], row["id"]))
        return
    try:
        quota = adapter.quota_probe()
    except ProviderError:
        quota = None
    now = _now()
    conn.execute(
        "UPDATE provider_connections SET status='online', models=?, last_verified=?, last_error=NULL WHERE id=?",
        (json.dumps(health.models[:200]), _iso(now), row["id"]),
    )
    # A model the provider does not serve would fail every task: pick one it actually lists.
    if health.models and row["model"] not in health.models:
        preferred = next((m for m in health.models if entry.get("default_model") and m.startswith(str(entry["default_model"]).split(":")[0])), health.models[0])
        conn.execute("UPDATE provider_connections SET model=? WHERE id=?", (preferred, row["id"]))
    if quota and quota.limit:
        used = max(0.0, quota.limit - (quota.remaining if quota.remaining is not None else quota.limit))
        conn.execute(
            "UPDATE provider_connections SET quota_unit=?, quota_limit=?, quota_used=?, quota_reset_at=COALESCE(?, quota_reset_at) WHERE id=?",
            (quota.unit, quota.limit, used, _iso(quota.reset_at), row["id"]),
        )
        conn.execute(
            "INSERT INTO quota_snapshots(connection_id, unit, quota_limit, remaining, reset_at, source) VALUES (?,?,?,?,?,?)",
            (row["id"], quota.unit, quota.limit, quota.remaining, _iso(quota.reset_at), quota.source),
        )


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(user: User = Depends(current_user)) -> list[ConnectionOut]:
    with db.transaction() as conn:
        rows = conn.execute("SELECT * FROM provider_connections WHERE user_id = ? ORDER BY created_at", (user.id,)).fetchall()
        return [row_to_out(conn, r) for r in rows]


def install_connection(conn, user_id: str, entry: dict, *, auth_type: str, secret: str | None, endpoint: str | None = None,
                       model: str | None = None, reserve: float | None = None, transport=None) -> sqlite3.Row:
    """Stores the credential in the vault, creates the connection and verifies it
    (health_check → list_models → quota_probe). Shared by API-key and OAuth installs."""
    if conn.execute("SELECT 1 FROM provider_connections WHERE user_id=? AND catalog_id=?", (user_id, entry["id"])).fetchone():
        raise HTTPException(status_code=409, detail="already_installed")
    credential_id = vault.store(conn, user_id, secret) if secret else None
    connection_id = "con_" + secrets.token_urlsafe(10)
    quota = entry["quota"]
    conn.execute(
        """INSERT INTO provider_connections(id, user_id, catalog_id, auth_type, credential_id, endpoint, model, status,
           reserve, quota_limit, quota_unit, quota_window, quota_reset_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            connection_id, user_id, entry["id"], auth_type, credential_id, endpoint, model or entry.get("default_model"), "pending",
            reserve if reserve is not None else quota.get("default_reserve", 0),
            quota.get("limit"), quota.get("unit"), quota.get("window"), _iso(next_reset(quota.get("window"), _now())),
        ),
    )
    row = conn.execute("SELECT * FROM provider_connections WHERE id=?", (connection_id,)).fetchone()
    verify(conn, user_id, row, entry, transport)
    return conn.execute("SELECT * FROM provider_connections WHERE id=?", (connection_id,)).fetchone()


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(payload: ConnectionCreate, request: Request, user: User = Depends(current_user)) -> ConnectionOut:
    settings = request.app.state.settings
    entry = catalog.provider(settings.catalog_dir, payload.catalog_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown_provider")
    if payload.auth_type not in entry["auth_types"]:
        raise HTTPException(status_code=400, detail="auth_type_not_supported")
    if payload.auth_type == "oauth":
        raise HTTPException(status_code=400, detail="use_oauth_start")
    if payload.auth_type == "api_key" and not payload.api_key:
        raise HTTPException(status_code=400, detail="api_key_required")
    if payload.api_key and not vault.configured():
        raise HTTPException(status_code=503, detail="vault_not_configured")
    with db.transaction() as conn:
        row = install_connection(conn, user.id, entry, auth_type=payload.auth_type, secret=(payload.api_key or "").strip() or None,
                                 endpoint=payload.endpoint, model=payload.model, reserve=payload.reserve,
                                 transport=getattr(request.app.state, "http_transport", None))
        return row_to_out(conn, row)


@router.post("/connections/{connection_id}/verify", response_model=ConnectionOut)
def reverify(connection_id: str, request: Request, user: User = Depends(current_user)) -> ConnectionOut:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM provider_connections WHERE id=? AND user_id=?", (connection_id, user.id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        entry = catalog.provider(request.app.state.settings.catalog_dir, row["catalog_id"])
        verify(conn, user.id, row, entry, getattr(request.app.state, "http_transport", None))
        return row_to_out(conn, conn.execute("SELECT * FROM provider_connections WHERE id=?", (connection_id,)).fetchone())


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: str, user: User = Depends(current_user)) -> None:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM provider_connections WHERE id=? AND user_id=?", (connection_id, user.id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        conn.execute("DELETE FROM provider_connections WHERE id=?", (connection_id,))
        if row["credential_id"]:
            vault.delete(conn, user.id, row["credential_id"])


# ---- provider OAuth (login → key issued automatically → vault) ----

OAUTH_STATE_TTL = 600
OPENROUTER_AUTH = "https://openrouter.ai/auth"
OPENROUTER_KEYS = "https://openrouter.ai/api/v1/auth/keys"


def _append_query(url: str, **params) -> str:
    return url + ("&" if "?" in url else "?") + urlencode(params)


@router.get("/oauth/{provider_id}/start")
def oauth_start(provider_id: str, request: Request, return_to: str | None = None, user: User = Depends(current_user)) -> dict:
    """Returns the provider's login URL. OpenRouter uses PKCE and issues an API key on approval."""
    settings = request.app.state.settings
    entry = catalog.provider(settings.catalog_dir, provider_id)
    if entry is None or "oauth" not in entry["auth_types"]:
        raise HTTPException(status_code=404, detail="oauth_not_supported")
    if provider_id != "openrouter":
        raise HTTPException(status_code=501, detail="oauth_adapter_not_implemented")
    if not vault.configured():
        raise HTTPException(status_code=503, detail="vault_not_configured")
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    with db.transaction() as conn:
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (_iso(_now() - timedelta(seconds=OAUTH_STATE_TTL)),))
        conn.execute("INSERT INTO oauth_states(state, code_verifier, return_to, purpose, user_id) VALUES (?,?,?,?,?)",
                     (state, verifier, safe_return_to(return_to, settings), "provider:openrouter", user.id))
    # OpenRouter only appends ?code=, so the state travels in the callback path.
    callback = settings.public_url.rstrip("/") + f"/providers/oauth/openrouter/callback/{state}"
    return {"authorize_url": OPENROUTER_AUTH + "?" + urlencode({"callback_url": callback, "code_challenge": challenge, "code_challenge_method": "S256"})}


@router.get("/oauth/openrouter/callback/{state}")
def openrouter_callback(state: str, request: Request, code: str | None = None) -> RedirectResponse:
    settings = request.app.state.settings
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM oauth_states WHERE state=? AND purpose='provider:openrouter' AND created_at > ?",
                           (state, _iso(_now() - timedelta(seconds=OAUTH_STATE_TTL)))).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state=?", (state,))
    if row is None:
        raise HTTPException(status_code=400, detail="invalid_or_expired_state")
    back = row["return_to"] or safe_return_to(None, settings)
    # The login must finish in the same browser session that started it.
    try:
        if current_user(request).id != row["user_id"]:
            return RedirectResponse(_append_query(back, connect_error="session_mismatch"), status_code=302)
    except HTTPException:
        return RedirectResponse(_append_query(back, connect_error="not_signed_in"), status_code=302)
    if not code:
        return RedirectResponse(_append_query(back, connect_error="denied"), status_code=302)
    transport = getattr(request.app.state, "http_transport", None)
    try:
        with httpx.Client(timeout=20, transport=transport) as client:
            res = client.post(OPENROUTER_KEYS, json={"code": code, "code_verifier": row["code_verifier"], "code_challenge_method": "S256"})
        key = res.json().get("key") if res.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        key = None
    if not key:
        return RedirectResponse(_append_query(back, connect_error="key_exchange_failed"), status_code=302)
    entry = catalog.provider(settings.catalog_dir, "openrouter")
    try:
        with db.transaction() as conn:
            installed = install_connection(conn, row["user_id"], entry, auth_type="oauth", secret=key, transport=transport)
    except HTTPException as exc:
        return RedirectResponse(_append_query(back, connect_error=str(exc.detail)), status_code=302)
    return RedirectResponse(_append_query(back, connected="openrouter", status=installed["status"]), status_code=302)
