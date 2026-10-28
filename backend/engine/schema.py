"""Shared data shapes for the engine (log columns, issues, master rows, overrides)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

LOG_COLS = ["tid", "date", "opening_balance", "withdrawal", "replenishment", "closing_balance"]


@dataclass(frozen=True)
class Issue:
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    tid: str | None = None
    date: date | None = None


@dataclass
class AtmMaster:
    tid: str
    location_name: str
    location_type: str
    capacity: int
    min_safe_balance: int
    replenish_cycle_days: int
    denomination: int
    cost_per_visit: int
    current_fill_level: int
    next_visit_date: date | None = None
    inferred: bool = False


@dataclass(frozen=True)
class Override:
    tid: str
    visit_date: date
    amount: int | None
    skipped: bool = False
    moved_from: date | None = None
