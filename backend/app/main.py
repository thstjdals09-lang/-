from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from . import auth, catalog, config, connections, vault
from .auth import User, csrf_guard, current_user
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
    return {"status": "ok", "google_oauth": s.google_configured, "vault": vault.configured(), "dev_login": s.dev_login}


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.load()
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
    return application


app = create_app()
