from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .domain import AIEmployee, AIEmployeeCreate, RoutingDecision, TaskCreate
from .router import route_task


app = FastAPI(title="AI Factory Core", version="0.1.0")

_EMPLOYEES: dict[int, AIEmployee] = {}
_NEXT_ID = 1


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/employees", response_model=list[AIEmployee])
def list_employees() -> list[AIEmployee]:
    return list(_EMPLOYEES.values())


@app.post("/employees", response_model=AIEmployee, status_code=201)
def create_employee(payload: AIEmployeeCreate) -> AIEmployee:
    global _NEXT_ID
    employee = AIEmployee(id=_NEXT_ID, **payload.model_dump())
    _EMPLOYEES[_NEXT_ID] = employee
    _NEXT_ID += 1
    return employee


@app.post("/route", response_model=RoutingDecision)
def route(payload: TaskCreate) -> RoutingDecision:
    try:
        return route_task(payload, list(_EMPLOYEES.values()))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
