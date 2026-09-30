"""SQLite persistence: connection handling and versioned schema migrations."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS: list[str] = [
    # 1 — legacy V0 tables kept for the /employees and /route APIs.
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
    """,
    # 2 — accounts, sessions, provider connections and the encrypted vault.
    """
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        google_sub TEXT UNIQUE,
        email TEXT NOT NULL UNIQUE,
        name TEXT,
        picture TEXT,
        settings TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_login_at TEXT
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT NOT NULL
    );
    CREATE TABLE oauth_states (
        state TEXT PRIMARY KEY,
        code_verifier TEXT NOT NULL,
        return_to TEXT,
        purpose TEXT NOT NULL DEFAULT 'login',
        user_id TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE encrypted_credentials (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        key_version INTEGER NOT NULL,
        nonce BLOB NOT NULL,
        ciphertext BLOB NOT NULL,
        fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        rotated_at TEXT
    );
    CREATE TABLE provider_connections (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        catalog_id TEXT NOT NULL,
        auth_type TEXT NOT NULL,
        credential_id TEXT REFERENCES encrypted_credentials(id) ON DELETE SET NULL,
        endpoint TEXT,
        model TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        reserve REAL,
        quota_limit REAL,
        quota_used REAL NOT NULL DEFAULT 0,
        quota_unit TEXT,
        quota_window TEXT,
        quota_reset_at TEXT,
        cooldown_until TEXT,
        models TEXT NOT NULL DEFAULT '[]',
        stats TEXT NOT NULL DEFAULT '{}',
        last_verified TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, catalog_id)
    );
    CREATE TABLE quota_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        connection_id TEXT NOT NULL REFERENCES provider_connections(id) ON DELETE CASCADE,
        unit TEXT,
        quota_limit REAL,
        remaining REAL,
        reset_at TEXT,
        source TEXT NOT NULL,
        captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        connection_id TEXT REFERENCES provider_connections(id) ON DELETE SET NULL,
        task_id TEXT,
        model TEXT,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        requests INTEGER NOT NULL DEFAULT 1,
        latency_ms INTEGER,
        outcome TEXT NOT NULL,
        error_kind TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # 3 — the production model: projects → ideas → lines → stages → tasks.
    """
    CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        topic TEXT NOT NULL,
        genre TEXT,
        platform TEXT,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE ideas (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        rank INTEGER NOT NULL,
        title TEXT NOT NULL,
        type TEXT NOT NULL,
        family TEXT NOT NULL,
        pitch TEXT NOT NULL,
        loop TEXT NOT NULL,
        metrics TEXT NOT NULL,
        reviews TEXT NOT NULL,
        score REAL NOT NULL,
        status TEXT NOT NULL
    );
    CREATE TABLE production_lines (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        idea_id TEXT NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        slug TEXT NOT NULL,
        project_slug TEXT NOT NULL,
        family TEXT NOT NULL,
        game_type TEXT NOT NULL,
        stage_index INTEGER NOT NULL,
        status TEXT NOT NULL,
        autopilot INTEGER NOT NULL DEFAULT 1,
        leader_state TEXT NOT NULL DEFAULT 'planning',
        leader_decision TEXT,
        repo_path TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE stages (
        id TEXT PRIMARY KEY,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        stage_key TEXT NOT NULL,
        status TEXT NOT NULL,
        qa_status TEXT NOT NULL DEFAULT 'pending',
        started_at TEXT,
        completed_at TEXT,
        UNIQUE(line_id, stage_key)
    );
    CREATE TABLE workers (
        id TEXT PRIMARY KEY,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        connection_id TEXT REFERENCES provider_connections(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'idle',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        stage_id TEXT NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
        task_key TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        kind TEXT NOT NULL,
        difficulty INTEGER NOT NULL,
        critical INTEGER NOT NULL DEFAULT 0,
        artifact TEXT,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        worker_id TEXT REFERENCES workers(id) ON DELETE SET NULL,
        connection_id TEXT REFERENCES provider_connections(id) ON DELETE SET NULL,
        reviewer_connection_id TEXT REFERENCES provider_connections(id) ON DELETE SET NULL,
        branch TEXT,
        commit_sha TEXT,
        qa_status TEXT,
        substituted_from TEXT,
        repair_of TEXT,
        tokens_used INTEGER NOT NULL DEFAULT 0,
        started_at TEXT,
        finished_at TEXT,
        UNIQUE(stage_id, task_key)
    );
    CREATE TABLE task_dependencies (
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        depends_on TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        PRIMARY KEY (task_id, depends_on)
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        task_id TEXT,
        type TEXT NOT NULL,
        sender TEXT NOT NULL,
        recipient TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
        stage_key TEXT NOT NULL,
        path TEXT NOT NULL,
        content TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE builds (
        id TEXT PRIMARY KEY,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        version TEXT NOT NULL,
        stage_key TEXT NOT NULL,
        platform TEXT NOT NULL,
        status TEXT NOT NULL,
        smoke TEXT NOT NULL,
        commit_sha TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE feedback (
        id TEXT PRIMARY KEY,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        stage_key TEXT,
        task_id TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE reviews (
        id TEXT PRIMARY KEY,
        line_id TEXT NOT NULL REFERENCES production_lines(id) ON DELETE CASCADE,
        build_id TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        blocking INTEGER NOT NULL,
        status TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT
    );
    CREATE TABLE factory_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        line_id TEXT,
        type TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_tasks_line ON tasks(line_id, status);
    CREATE INDEX idx_logs_user ON factory_logs(user_id, id);
    CREATE INDEX idx_messages_line ON messages(line_id, id);
    """,
    # 4 — worker/reviewer display names (simulated workers have no connection row).
    """
    ALTER TABLE tasks ADD COLUMN worker_name TEXT;
    ALTER TABLE tasks ADD COLUMN reviewer_name TEXT;
    """,
]


def db_path() -> Path:
    return Path(os.environ.get("AI_FACTORY_DB", "data/ai_factory.sqlite3"))


def connect(autocommit: bool = False) -> sqlite3.Connection:
    """autocommit=True: every statement commits on its own (worker threads never hold a write
    lock across a provider call)."""
    path = db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None if autocommit else "")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # API requests and the autopilot thread write concurrently
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migrate() -> int:
    """Applies pending migrations and returns the resulting schema version."""
    with transaction() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0
        for index, script in enumerate(MIGRATIONS[current:], start=current + 1):
            conn.executescript(script)
            if row is None and index == 1:
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (index,))
                row = {"version": index}
            else:
                conn.execute("UPDATE schema_version SET version = ?", (index,))
        return len(MIGRATIONS)
