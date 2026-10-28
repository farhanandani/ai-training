"""Policy comparison and replay against actual demand (PRD 6.4, TR-16, TR-19, TR-33, TR-36).

This is the only engine module that may receive the dummy ground truth `true_demand` (TR-16)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

from .plan import AtmPlan, _idx, _topup, simulate_balance

if TYPE_CHECKING:
    from .allocate import Allocation
    from .forecast import ForecastResult


@dataclass
class PolicyStats:
    cash_out_days: int
    idle_cash: int
    idle_cost: int
    visits: int
    visit_cost: int
    loaded: int


@dataclass
class DemandSource:
    basis: Literal["true_demand", "estimated"]
    demand: dict[str, np.ndarray]


def _planned_loads(plan: AtmPlan, as_of: date, h: int) -> np.ndarray:
    """Recommended plan: each visit's load (allocated if set, else amount) on its date; skips load 0."""
    loads = np.zeros(h, dtype=np.int64)
    for v in plan.visits:
        i = _idx(v.date, as_of)
        if 0 <= i < h:
            loads[i] += max(int(v.allocated if v.allocated is not None else v.amount), 0)
    return loads


def policy_stats(
    plans: list[AtmPlan],
    demand: dict[str, np.ndarray],
    h: int,
    idle_rate: float,
    *,
    as_of: date,
    current: bool = False,
) -> PolicyStats:
    """Re-simulate each plan against `demand` with simulate_balance (PRD 6.4).

    current=True re-applies the current-policy rule (top up to current_fill_level on each visit date)
    against this demand; otherwise the plan's planned loads are used. A visit counts only when its
    effective (clamped) load is > 0. insufficient_history plans are excluded."""
    co = visits = cost = loaded = 0
    idle_sum, atm_days, n_atms = 0, 0, 0
    for p in plans:
        if p.status == "insufficient_history":
            continue
        m, d = p.master, np.asarray(demand[p.tid], dtype=float)[:h]
        if current:
            idx = sorted({_idx(v.date, as_of) for v in p.visits if 0 <= _idx(v.date, as_of) < h})
            sim = _topup(p.b0, d, idx, m)
        else:
            sim = simulate_balance(p.b0, d, _planned_loads(p, as_of, h), m.capacity)
        n = int((sim.loads > 0).sum())
        co += int(sim.cash_out.sum())
        visits += n
        cost += n * m.cost_per_visit
        loaded += int(sim.loads.sum())
        idle_sum += int(np.maximum(sim.closing - m.min_safe_balance, 0).sum())
        atm_days += len(sim.closing)
        n_atms += 1
    idle = idle_sum / atm_days if atm_days else 0.0
    idle_cost = round(idle * n_atms * idle_rate * h / 365)
    return PolicyStats(int(co), round(idle), int(idle_cost), int(visits), int(cost), int(loaded))


def _q50_on(fc: ForecastResult | None, ts: pd.Timestamp) -> float | None:
    """In-sample fitted q50 for dates <= the forecast's as_of, else the forecast q50; None if unknown."""
    if fc is None:
        return None
    s = fc.fitted_q50 if ts.date() <= fc.as_of else fc.forecast["q50"]
    v = s.get(ts)
    return None if v is None or pd.isna(v) else float(v)


def build_demand_source(
    log: pd.DataFrame,
    true_demand: pd.DataFrame | None,
    forecasts: dict[str, ForecastResult | None],
    as_of: date,
    h: int,
) -> DemandSource | None:
    """Actual demand over as_of+1 .. as_of+h for replay (PRD 6.4); None if that window is not in the log.

    true_demand given (dummy data) -> its values. Otherwise "estimated": the logged withdrawal, and on
    censored days (closing_balance == 0, or no row) max(logged, q50 fit/forecast for that date)."""
    if log.empty or as_of + timedelta(days=h) > max(log["date"]):
        return None
    days = pd.date_range(as_of + timedelta(days=1), periods=h, freq="D")
    use_true = true_demand is not None and not true_demand.empty
    out: dict[str, np.ndarray] = {}
    for tid, g in log.groupby("tid", sort=True):
        g = g.set_index(pd.to_datetime(g["date"])).reindex(days)
        if use_true:
            t = true_demand[true_demand["tid"] == tid]
            t = t.set_index(pd.to_datetime(t["date"]))["true_demand"].reindex(days)
            out[tid] = t.fillna(g["withdrawal"]).fillna(0).to_numpy(dtype=np.int64)
            continue
        vals = []
        for ts, w, c in zip(days, g["withdrawal"], g["closing_balance"], strict=True):
            logged = 0.0 if pd.isna(w) else float(w)
            if pd.isna(c) or c == 0:
                q = _q50_on(forecasts.get(tid), ts)
                logged = max(logged, q) if q is not None else logged
            vals.append(round(logged))
        out[tid] = np.asarray(vals, dtype=np.int64)
    return DemandSource("true_demand" if use_true else "estimated", out)


def compare(
    current: list[AtmPlan],
    alloc: Allocation,
    forecast_demand: dict[str, np.ndarray],
    replay: DemandSource | None,
    idle_rate: float,
    h: int,
    *,
    as_of: date,
) -> dict:
    """The TR-36 `comparison` object: current vs recommended on the forecast (q50) demand and, in
    time-travel mode, replayed against actual demand. All values are ints."""

    def both(demand: dict[str, np.ndarray]) -> tuple[dict, dict]:
        cur = policy_stats(current, demand, h, idle_rate, as_of=as_of, current=True)
        rec = policy_stats(alloc.plans, demand, h, idle_rate, as_of=as_of)
        return asdict(cur), asdict(rec)

    cur, rec = both(forecast_demand)
    out: dict = {"current": cur, "recommended": rec, "replay": None}
    if replay is not None:
        rc, rr = both(replay.demand)
        out["replay"] = {"basis": replay.basis, "current": rc, "recommended": rr}
    return out
