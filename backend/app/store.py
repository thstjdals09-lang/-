from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .domain import AIEmployee, AIEmployeeCreate, RoutingDecision, TaskCreate

DB_PATH = Path("data/ai_factory.sqlite3")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routing_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_payload TEXT NOT NULL,
                decision_payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def list_employees() -> list[AIEmployee]:
    with connect() as conn:
        rows = conn.execute("SELECT id, payload FROM employees ORDER BY id").fetchall()
    return [
        AIEmployee(id=row["id"], **json.loads(row["payload"]))
        for row in rows
    ]


def create_employee(payload: AIEmployeeCreate) -> AIEmployee:
    serialized = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
    with connect() as conn:
        cur = conn.execute("INSERT INTO employees(payload) VALUES (?)", (serialized,))
        employee_id = int(cur.lastrowid)
    return AIEmployee(id=employee_id, **payload.model_dump())


def save_routing_log(task: TaskCreate, decision: RoutingDecision) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO routing_logs(task_payload, decision_payload) VALUES (?, ?)",
            (
                task.model_dump_json(),
                decision.model_dump_json(),
            ),
        )


def list_routing_logs(limit: int = 100) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, task_payload, decision_payload, created_at
            FROM routing_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "task": json.loads(row["task_payload"]),
            "decision": json.loads(row["decision_payload"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
