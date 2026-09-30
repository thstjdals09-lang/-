"""Minimal .env loader: KEY=VALUE lines, comments and blanks ignored. Existing environment
variables always win, so deployment settings are never overridden by a stray file."""

from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load(path: Path = ENV_PATH) -> int:
    if not path.is_file():
        return 0
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            count += 1
    return count
