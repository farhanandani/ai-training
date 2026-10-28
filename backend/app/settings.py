"""Environment-driven settings (TR-06). Plain dataclass, env prefix CASHFC_."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PREFIX = "CASHFC_"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.environ.get(PREFIX + name, default)


def _path(name: str, default: str) -> Path:
    p = Path(_env(name, default))
    return p if p.is_absolute() else REPO_ROOT / p


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(PREFIX + name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _default_workers() -> int:
    return int(_env("WORKERS", str(max(1, (os.cpu_count() or 2) - 1))))


def _business_defaults() -> dict:
    return {
        "h": 14,
        "sl": "p90",
        "budget": None,
        "overstock_frac": 0.30,
        "idle_rate": 0.06,
        "detect_jump_frac": 0.20,
    }


@dataclass
class Settings:
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))
    workspace_db: Path = field(default_factory=lambda: _path("WORKSPACE_DB", "workspace/workspace.db"))
    seed_dir: Path = field(default_factory=lambda: _path("SEED_DIR", "data"))
    workers: int = field(default_factory=_default_workers)
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "20")))
    warmup_scenarios: bool = field(default_factory=lambda: _bool("WARMUP_SCENARIOS", True))
    business_defaults: dict = field(default_factory=_business_defaults)
