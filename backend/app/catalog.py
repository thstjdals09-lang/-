"""Loads the shared provider and studio catalogs (docs/catalog/*.json)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def providers(catalog_dir: Path) -> list[dict]:
    return _read(str(catalog_dir / "providers.json"))["providers"]


def provider(catalog_dir: Path, provider_id: str) -> dict | None:
    return next((p for p in providers(catalog_dir) if p["id"] == provider_id), None)


def studio(catalog_dir: Path) -> dict:
    return _read(str(catalog_dir / "studio.json"))


def catalog_updated(catalog_dir: Path) -> str:
    return _read(str(catalog_dir / "providers.json"))["catalog_updated"]
