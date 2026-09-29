from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from .domain import AIEmployee, AIEmployeeCreate, RoutingDecision, TaskCreate
from .router import route_task
from .store import create_employee, init_db, list_employees, list_routing_logs, save_routing_log


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Factory Core", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/employees", response_model=list[AIEmployee])
def get_employees() -> list[AIEmployee]:
    return list_employees()


@app.post("/employees", response_model=AIEmployee, status_code=201)
def post_employee(payload: AIEmployeeCreate) -> AIEmployee:
    return create_employee(payload)


@app.post("/route", response_model=RoutingDecision)
def route(payload: TaskCreate) -> RoutingDecision:
    try:
        decision = route_task(payload, list_employees())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    save_routing_log(payload, decision)
    return decision


@app.get("/routing-logs")
def get_routing_logs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return list_routing_logs(limit)
