from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import sys

from . import account, auth, catalog, config, connections, envfile, vault

if "pytest" not in sys.modules:
    envfile.load()  # backend/.env for local runs; real environment variables always win
from .auth import User, csrf_guard, current_user
from .factory import api as factory_api
from .factory.leader import autopilot_pass
from .domain import (
    AIEmployee,
    AIEmployeeCreate,
    GamePublishRequest,
    GamePublishResponse,
    GitHubPublisherStatus,
    RoutingDecision,
    TaskCreate,
)
from .github_publisher import GitHubPublishError, GitHubPublisher
from .router import route_task
from .store import create_employee, init_db, list_employees, list_routing_logs, save_routing_log

core = APIRouter()


@core.get("/health")
def health(request: Request) -> dict:
    s: config.Settings = request.app.state.settings
    return {"status": "ok", "google_oauth": s.google_configured, "vault": vault.configured(), "dev_login": s.dev_login, "signup": s.signup_mode}


@core.get("/catalog/providers")
def catalog_providers(request: Request) -> dict:
    d = request.app.state.settings.catalog_dir
    return {"catalog_updated": catalog.catalog_updated(d), "providers": catalog.providers(d)}


@core.get("/catalog/studio")
def catalog_studio(request: Request) -> dict:
    return catalog.studio(request.app.state.settings.catalog_dir)


# ---- V0 employee/routing API (kept for compatibility) ----

@core.get("/employees", response_model=list[AIEmployee])
def get_employees() -> list[AIEmployee]:
    return list_employees()


@core.post("/employees", response_model=AIEmployee, status_code=201, dependencies=[Depends(csrf_guard)])
def post_employee(payload: AIEmployeeCreate) -> AIEmployee:
    return create_employee(payload)


@core.post("/route", response_model=RoutingDecision, dependencies=[Depends(csrf_guard)])
def route(payload: TaskCreate) -> RoutingDecision:
    try:
        decision = route_task(payload, list_employees())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    save_routing_log(payload, decision)
    return decision


@core.get("/routing-logs")
def get_routing_logs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return list_routing_logs(limit)


# ---- GitHub publishing (server token; signed-in users only) ----

@core.get("/publishing/github/status", response_model=GitHubPublisherStatus)
def github_publisher_status() -> GitHubPublisherStatus:
    return GitHubPublisherStatus(
        configured=bool(os.environ.get("AI_FACTORY_GITHUB_TOKEN", "").strip()),
        owner=os.environ.get("AI_FACTORY_GITHUB_OWNER"),
    )


@core.post("/publishing/github", response_model=GamePublishResponse, status_code=201, dependencies=[Depends(csrf_guard)])
def publish_game(payload: GamePublishRequest, _: User = Depends(current_user)) -> GamePublishResponse:
    try:
        result = GitHubPublisher.from_environment().publish(
            game_name=payload.game_name,
            description=payload.description,
            files=payload.files,
            owner=payload.owner,
            private=payload.private,
        )
    except GitHubPublishError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return GamePublishResponse(**result.__dict__)


def _autopilot_loop(app: FastAPI, stop: threading.Event, interval: float) -> None:
    while not stop.wait(interval):
        try:
            autopilot_pass(factory_api.get_factory(app))
        except Exception:  # keep the loop alive; per-line errors are logged inside
            pass


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    stop = threading.Event()
    interval = float(os.environ.get("AI_FACTORY_AUTOPILOT_SECONDS", "5"))
    worker = None
    if interval > 0:
        worker = threading.Thread(target=_autopilot_loop, args=(application, stop, interval), name="ai-factory-autopilot", daemon=True)
        worker.start()
    yield
    stop.set()
    if worker:
        worker.join(timeout=5)


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()
    if settings.dev_login and not settings.is_local:
        raise RuntimeError("AI_FACTORY_DEV_LOGIN lets anyone sign in as any email; it is refused when AI_FACTORY_PUBLIC_URL is not localhost")
    application = FastAPI(title="AI Factory Core", version="0.2.0", lifespan=lifespan)
    application.state.settings = settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-AI-Factory"],
    )
    application.include_router(core)
    application.include_router(auth.router)
    application.include_router(connections.router)
    application.include_router(account.router)
    application.include_router(factory_api.router)
    console = settings.catalog_dir.parent
    if os.environ.get("AI_FACTORY_SERVE_CONSOLE", "true").lower() in ("1", "true", "yes") and (console / "index.html").exists():
        # Same-origin console for local use: http://127.0.0.1:8000/console/
        application.mount("/console", StaticFiles(directory=console, html=True), name="console")
    return application


app = create_app()
