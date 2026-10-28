"""Balance simulation (the only simulator, TR-19). Planning/recommendation is added by later tasks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SimResult:
    opening: np.ndarray
    withdrawal: np.ndarray
    closing: np.ndarray
    cash_out: np.ndarray  # bool
    loads: np.ndarray  # effective (clamped) loads


def simulate_balance(b0: int, demand: np.ndarray, loads: np.ndarray, cap: int) -> SimResult:
    """Daily order: load in the morning -> withdraw -> close (TR-19).

    Each load is clamped to [0, cap - balance_before_load]. withdrawal = min(demand, available),
    rounded to whole IDR. Cash-out day: closing == 0 and demand > withdrawal.
    """
    demand = np.asarray(demand, dtype=float)
    h = len(demand)
    opening = np.zeros(h, dtype=np.int64)
    withdrawal = np.zeros(h, dtype=np.int64)
    closing = np.zeros(h, dtype=np.int64)
    eff = np.zeros(h, dtype=np.int64)
    bal = int(b0)
    for i in range(h):
        opening[i] = bal
        load = min(max(int(loads[i]), 0), max(int(cap) - bal, 0))
        eff[i] = load
        avail = bal + load
        w = min(round(max(float(demand[i]), 0.0)), avail)
        withdrawal[i] = w
        bal = avail - w
        closing[i] = bal
    cash_out = (closing == 0) & (demand > withdrawal)
    return SimResult(opening, withdrawal, closing, cash_out, eff)
