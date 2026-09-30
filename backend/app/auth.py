"""Google OAuth login, server-side sessions and the CSRF guard.

Flow: browser → GET /auth/google/login → Google consent → GET /auth/google/callback → session
cookie (HttpOnly) → redirect back to the allow-listed web console. The session token is random;
only its SHA-256 hash is stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import threading
import json
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import config, db

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
COOKIE = "af_session"
STATE_TTL_SECONDS = 600

router = APIRouter(prefix="/auth", tags=["auth"])


class User(BaseModel):
    id: str
    email: str
    name: str | None = None
    picture: str | None = None
    role: str = "member"


class SignupClosed(HTTPException):
    def __init__(self):
        super().__init__(status_code=403, detail="signup_not_allowed")


class PasswordSignup(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=60)


class PasswordLogin(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class DevLogin(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def safe_return_to(return_to: str | None, settings: config.Settings) -> str:
    """Only allow redirects back to configured web-console origins (no open redirect)."""
    fallback = settings.allowed_origins[0] + "/" if settings.allowed_origins else "/"
    if not return_to:
        return fallback
    for origin in settings.allowed_origins:
        if return_to == origin or return_to.startswith(origin + "/"):
            return return_to
    return fallback


def upsert_user(conn: sqlite3.Connection, *, email: str, name: str | None, picture: str | None, google_sub: str | None,
                settings: config.Settings | None = None) -> User:
    """First sign-in creates the account (subject to the signup policy); later sign-ins update it."""
    email = email.strip().lower()
    row = None
    if google_sub:
        row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    role = "admin" if settings and email in settings.admin_emails else "member"
    if row is None:
        if settings and settings.signup_mode == "allowlist" and email not in settings.allowed_emails and email not in settings.admin_emails:
            raise SignupClosed()
        user_id = "usr_" + secrets.token_urlsafe(10)
        conn.execute(
            "INSERT INTO users(id, google_sub, email, name, picture, last_login_at, role) VALUES (?,?,?,?,?,?,?)",
            (user_id, google_sub, email, name, picture, _iso(_now()), role),
        )
    else:
        user_id = row["id"]
        role = "admin" if role == "admin" else row["role"]
        conn.execute(
            "UPDATE users SET google_sub = COALESCE(?, google_sub), name = COALESCE(?, name), picture = COALESCE(?, picture), last_login_at = ?, role = ? WHERE id = ?",
            (google_sub, name, picture, _iso(_now()), role, user_id),
        )
    return User(id=user_id, email=email, name=name, picture=picture, role=role)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_b64, digest_b64 = stored.split("$", 2)
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


class LoginThrottle:
    """At most `limit` failed sign-ins per email and per client address in `window` seconds."""

    def __init__(self, limit: int = 8, window: int = 900):
        self.limit, self.window = limit, window
        self.failures: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        now = time.time()
        items = [t for t in self.failures.get(key, []) if now - t < self.window]
        self.failures[key] = items
        return items

    def check(self, *keys: str) -> None:
        with self.lock:
            if any(len(self._recent(k)) >= self.limit for k in keys):
                raise HTTPException(status_code=429, detail="too_many_attempts")

    def fail(self, *keys: str) -> None:
        with self.lock:
            for k in keys:
                self._recent(k).append(time.time())


throttle = LoginThrottle()


def create_session(conn: sqlite3.Connection, user_id: str, settings: config.Settings) -> str:
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(days=settings.session_days)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?,?,?)", (_hash(token), user_id, _iso(expires)))
    return token


def set_session_cookie(response: Response, token: str, settings: config.Settings) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not_signed_in")
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (_hash(token), _iso(_now())),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="session_expired")
    return User(id=row["id"], email=row["email"], name=row["name"], picture=row["picture"], role=row["role"])


def csrf_guard(request: Request) -> None:
    """Cookie-authenticated mutations must carry the custom header (forces a CORS preflight)
    and, when the browser sends an Origin, it must be allow-listed."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("x-ai-factory") != "1":
        raise HTTPException(status_code=403, detail="missing_csrf_header")
    origin = request.headers.get("origin")
    settings = request.app.state.settings
    if origin and origin.rstrip("/") not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="origin_not_allowed")


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def validate_id_token(id_token: str, client_id: str, now: float | None = None) -> dict:
    """Validates Google ID-token claims. The token is received directly from Google's token
    endpoint over TLS in the code flow, so per OIDC Core 3.1.3.7 the TLS channel authenticates
    the issuer; we still check issuer, audience, expiry and email verification."""
    try:
        payload_b64 = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_id_token") from exc
    now = time.time() if now is None else now
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise HTTPException(status_code=400, detail="bad_issuer")
    if claims.get("aud") != client_id:
        raise HTTPException(status_code=400, detail="bad_audience")
    if float(claims.get("exp", 0)) < now:
        raise HTTPException(status_code=400, detail="id_token_expired")
    if not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise HTTPException(status_code=400, detail="email_not_verified")
    return claims


@router.get("/config")
def auth_config(request: Request) -> dict:
    s: config.Settings = request.app.state.settings
    return {"google": s.google_configured, "password": True, "dev_login": s.dev_login, "signup": s.signup_mode}


@router.get("/google/login")
def google_login(request: Request, return_to: str | None = None) -> RedirectResponse:
    s: config.Settings = request.app.state.settings
    if not s.google_configured:
        raise HTTPException(status_code=503, detail="google_oauth_not_configured")
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    with db.transaction() as conn:
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (_iso(_now() - timedelta(seconds=STATE_TTL_SECONDS)),))
        conn.execute("INSERT INTO oauth_states(state, code_verifier, return_to) VALUES (?,?,?)", (state, verifier, safe_return_to(return_to, s)))
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return RedirectResponse(GOOGLE_AUTH_URL + "?" + urlencode(params), status_code=302)


@router.get("/google/callback")
def google_callback(request: Request, state: str, code: str | None = None, error: str | None = None) -> RedirectResponse:
    s: config.Settings = request.app.state.settings
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM oauth_states WHERE state = ? AND purpose = 'login' AND created_at > ?",
            (state, _iso(_now() - timedelta(seconds=STATE_TTL_SECONDS))),
        ).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    if row is None:
        raise HTTPException(status_code=400, detail="invalid_or_expired_state")
    if error or not code:
        return RedirectResponse(row["return_to"] + "?login=denied", status_code=302)

    transport = getattr(request.app.state, "http_transport", None)
    with httpx.Client(timeout=15, transport=transport) as client:
        res = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": s.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": row["code_verifier"],
            },
        )
    if res.status_code != 200:
        raise HTTPException(status_code=502, detail="google_token_exchange_failed")
    claims = validate_id_token(res.json().get("id_token", ""), s.google_client_id)

    try:
        with db.transaction() as conn:
            user = upsert_user(conn, email=claims["email"], name=claims.get("name"), picture=claims.get("picture"), google_sub=claims["sub"], settings=s)
            token = create_session(conn, user.id, s)
    except SignupClosed:
        return RedirectResponse(row["return_to"] + "?login=not_allowed", status_code=302)
    response = RedirectResponse(row["return_to"] + "?login=ok", status_code=302)
    set_session_cookie(response, token, s)
    return response


@router.post("/register", dependencies=[Depends(csrf_guard)])
def register(payload: PasswordSignup, request: Request, response: Response) -> User:
    """Email + password sign-up (works without any external identity provider)."""
    s: config.Settings = request.app.state.settings
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="invalid_email")
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="email_taken")
        user = upsert_user(conn, email=email, name=payload.name or email.split("@")[0], picture=None, google_sub=None, settings=s)
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(payload.password), user.id))
        token = create_session(conn, user.id, s)
    set_session_cookie(response, token, s)
    return user


@router.post("/login", dependencies=[Depends(csrf_guard)])
def password_login(payload: PasswordLogin, request: Request, response: Response) -> User:
    s: config.Settings = request.app.state.settings
    email = payload.email.strip().lower()
    client = "ip:" + (request.client.host if request.client else "?")
    throttle.check("email:" + email, client)
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row is None or not verify_password(payload.password, row["password_hash"]):
            throttle.fail("email:" + email, client)
            raise HTTPException(status_code=401, detail="invalid_credentials")
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (_iso(_now()), row["id"]))
        token = create_session(conn, row["id"], s)
    set_session_cookie(response, token, s)
    return User(id=row["id"], email=row["email"], name=row["name"], picture=row["picture"], role=row["role"])


@router.post("/dev-login", dependencies=[Depends(csrf_guard)])
def dev_login(payload: DevLogin, request: Request, response: Response) -> User:
    """Local development only (AI_FACTORY_DEV_LOGIN=1). Disabled by default."""
    s: config.Settings = request.app.state.settings
    if not s.dev_login:
        raise HTTPException(status_code=404, detail="not_found")
    with db.transaction() as conn:
        user = upsert_user(conn, email=payload.email, name=payload.name, picture=None, google_sub=None, settings=s)
        token = create_session(conn, user.id, s)
    set_session_cookie(response, token, s)
    return user


@router.get("/me")
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/logout", status_code=204, dependencies=[Depends(csrf_guard)])
def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(COOKIE)
    if token:
        with db.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
    s: config.Settings = request.app.state.settings
    response.delete_cookie(COOKIE, path="/", secure=s.cookie_secure, samesite=s.cookie_samesite)
    response.status_code = 204
    return response
