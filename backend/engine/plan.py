# """Balance simulation (the only simulator, TR-19). Planning/recommendation is added by later tasks."""
"""Balance simulation (the only simulator, TR-19), current-policy projection and recommendation (PRD 6.1-6.5)."""

from __future__ import annotations

# from dataclasses import dataclass
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from .forecast import ForecastResult
    from .schema import AtmMaster, Override


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


# ---------------------------------------------------------------- planning (PRD 6.1, 6.2, 6.5)

Status = Literal["cash_out_risk", "over_stocked", "ok", "insufficient_history"]
SL_COL = {"p50": "q50", "p80": "q80", "p90": "q90", "p95": "q95"}
OVERSTOCK_FRAC = 0.30


@dataclass
class Visit:
    tid: str
    date: date
    kind: Literal["scheduled", "extra", "moved"]
    amount: int
    tier1_need: int
    reason: str
    flags: list[str] = field(default_factory=list)
    manual: bool = False
    allocated: int | None = None


@dataclass
class AtmPlan:
    tid: str
    master: AtmMaster
    status: Status
    days_of_cash: int | None
    b0: int
    visits: list[Visit]
    projection_p50: np.ndarray
    projection_sl: np.ndarray
    schedule_assumed: bool


def _fmt_rp(x: int) -> str:
    return "Rp " + f"{int(x):,}".replace(",", ".")


def _fmt_day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _q(fc: ForecastResult, col: str) -> np.ndarray:
    """Forecast column as int64; position 0 is as_of + 1 (forecasts are always 30 rows)."""
    return fc.forecast[col].to_numpy(dtype=np.int64)


def _idx(d: date, as_of: date) -> int:
    return (d - as_of).days - 1


def _bal_before(b0: int, demand: np.ndarray, loads: np.ndarray, cap: int, i: int) -> int:
    """Balance on the morning of horizon day i, before its load (previous closing; b0 on day 0)."""
    if i == 0:
        return int(b0)
    return int(simulate_balance(b0, demand[:i], loads[:i], cap).closing[-1])


def _round_up(x: int, step: int) -> int:
    return -(-int(x) // step) * step


def need_window_end(i: int, loading_idx: list[int], cycle: int) -> int:
    """Last day covered by a load on day i: the day before the next *loading* visit (one that is not a
    skip), else i + cycle - 1 (PRD 6.2). Shared by recommend and allocation."""
    nxt = min((j for j in loading_idx if j > i), default=None)
    return nxt - 1 if nxt is not None else i + cycle - 1


def size_load(
    q: np.ndarray, q50: np.ndarray, i: int, end: int, bal: int, cap: int, mn: int, step: int
) -> tuple[int, int, int]:
    """(amount, tier1_need, raw need) for a load on day i covering days i..end (PRD 6.2, TR-30).

    q = service-level quantile, q50 = median (full forecast columns); bal = balance before the load.
    amount/tier1_need are rounded up to `step` and capped at the room (cap - bal, rounded down)."""
    end = min(end, len(q) - 1)
    room = max(cap - bal, 0) // step * step
    need = int(q[i : end + 1].sum()) + mn - bal
    tier1 = int(q50[i : end + 1].sum()) + mn - bal
    return min(max(_round_up(need, step), 0), room), min(max(_round_up(tier1, step), 0), room), need


def _plan_status(
    master: AtmMaster, p50: SimResult, p90: SimResult, visit_idx: list[int], frac: float
) -> tuple[Status, int | None]:
    """PRD 6.1 status + days of cash. Shared by the current-policy and the recommended plan."""
    h = len(p50.closing)
    mn = master.min_safe_balance
    below = np.flatnonzero(p50.closing < mn)
    days = int(below[0]) + 1 if len(below) else None
    nxt = min(visit_idx) if visit_idx else h
    b0 = int(p50.opening[0]) if h else 0
    if b0 < mn:  # already below the safe minimum: no days of cash
        days = 0
    # if (p90.closing[:nxt] < mn).any():
    if b0 < mn or (p90.closing[:nxt] < mn).any():  # imminent: p90 below min before the next visit
        return "cash_out_risk", days
    if visit_idx and p50.opening[nxt] > frac * master.capacity:
        return "over_stocked", days
    if p50.cash_out.any():  # later in the horizon: p50 projection runs dry
        return "cash_out_risk", days
    return "ok", days


def _empty_plan(master: AtmMaster, b0: int, schedule_assumed: bool) -> AtmPlan:
    empty = np.zeros(0, dtype=np.int64)
    return AtmPlan(
        master.tid, master, "insufficient_history", None, int(b0), [], empty, empty, schedule_assumed
    )


def _topup(b0: int, demand: np.ndarray, idx: list[int], master: AtmMaster) -> SimResult:
    """Current policy: on each visit day load current_fill_level - balance (clamped by the simulator)."""
    loads = np.zeros(len(demand), dtype=np.int64)
    for i in idx:
        loads[i] = max(master.current_fill_level - _bal_before(b0, demand, loads, master.capacity, i), 0)
    return simulate_balance(b0, demand, loads, master.capacity)


def project_current(
    master: AtmMaster,
    fc: ForecastResult | None,
    b0: int,
    as_of: date,
    h: int,
    visit_dates: list[date],
    *,
    overstock_frac: float = OVERSTOCK_FRAC,
    schedule_assumed: bool = False,
) -> AtmPlan:
    """Project the current policy (top up to current_fill_level on each scheduled visit), PRD 6.1.

    projection_sl is the p90 projection (the one that defines cash-out risk)."""
    if fc is None:
        return _empty_plan(master, b0, schedule_assumed)
    idx = sorted({_idx(d, as_of) for d in visit_dates if 0 <= _idx(d, as_of) < h})
    p50 = _topup(b0, _q(fc, "q50")[:h], idx, master)
    p90 = _topup(b0, _q(fc, "q90")[:h], idx, master)
    reason = f"Current policy: top up to {_fmt_rp(master.current_fill_level)}"
    visits = [
        Visit(master.tid, as_of + timedelta(days=i + 1), "scheduled", int(p50.loads[i]), 0, reason, [])
        for i in idx
    ]
    status, days = _plan_status(master, p50, p90, idx, overstock_frac)
    return AtmPlan(
        master.tid, master, status, days, int(b0), visits, p50.closing, p90.closing, schedule_assumed
    )


def _finish(
    master: AtmMaster,
    fc: ForecastResult,
    b0: int,
    h: int,
    sl: str,
    visits: list[Visit],
    frac: float,
    assumed: bool,
) -> AtmPlan:
    """Project a plan with its visits' loads (allocated if set, else amount) and compute its status."""
    cap = master.capacity
    loads = np.zeros(h, dtype=np.int64)
    for v in visits:
        i = _idx(v.date, fc.as_of)
        if 0 <= i < h:
            loads[i] += max(int(v.allocated if v.allocated is not None else v.amount), 0)
    p50 = simulate_balance(b0, _q(fc, "q50")[:h], loads, cap)
    p90 = simulate_balance(b0, _q(fc, "q90")[:h], loads, cap)
    psl = simulate_balance(b0, _q(fc, SL_COL[sl])[:h], loads, cap)
    idx = [int(i) for i in np.flatnonzero(loads > 0)]
    status, days = _plan_status(master, p50, p90, idx, frac)
    visits = sorted(visits, key=lambda v: v.date)
    return AtmPlan(master.tid, master, status, days, int(b0), visits, p50.closing, psl.closing, assumed)


def recommend(
    master: AtmMaster,
    fc: ForecastResult | None,
    b0: int,
    as_of: date,
    h: int,
    sl: str,
    visit_dates: list[date],
    overrides: list[Override],
    merge: bool = True,
    *,
    overstock_frac: float = OVERSTOCK_FRAC,
    schedule_assumed: bool = False,
) -> AtmPlan:
    """Recommended plan: need per visit, extra visits, merges, then manual overrides (PRD 6.2, 6.5)."""
    if fc is None:
        return _empty_plan(master, b0, schedule_assumed)
    q, q50 = _q(fc, SL_COL[sl]), _q(fc, "q50")
    qh = q[:h]
    cap, mn, step = master.capacity, master.min_safe_balance, master.denomination
    cycle, last = master.replenish_cycle_days, len(q) - 1

    def size(i: int, end: int, bal: int) -> tuple[int, int, int]:
        """(amount, tier1_need, raw need) for a load on day i covering days i..end (TR-30)."""
        # end = min(end, last)
        # room = max(cap - bal, 0) // step * step
        # need = int(q[i : end + 1].sum()) + mn - bal
        # tier1 = int(q50[i : end + 1].sum()) + mn - bal
        # return min(max(_round_up(need, step), 0), room), min(max(_round_up(tier1, step), 0), room), need
        return size_load(q, q50, i, min(end, last), bal, cap, mn, step)

    sched = sorted({_idx(d, as_of) for d in visit_dates if 0 <= _idx(d, as_of) < h})
    loads = np.zeros(h, dtype=np.int64)
    visits: list[Visit] = []
    for i in range(h):  # forward walk with q_sl demand (PRD 6.2, TR-31); at most one visit per day
        bal = _bal_before(b0, qh, loads, cap, i)
        d = as_of + timedelta(days=i + 1)
        if i in sched:
            kind, reason = "scheduled", "Scheduled visit"
        elif simulate_balance(bal, qh[i : i + 1], np.zeros(1), cap).closing[0] < mn:
            top = fc.explanations.get(d) or []
            kind, reason = "extra", f"Below safe minimum on {_fmt_day(d)}" + (f" ({top[0]})" if top else "")
        else:
            continue
        # nxt = next((j for j in sched if j > i), None)
        # amount, tier1, need = size(i, nxt - 1 if nxt is not None else i + cycle - 1, bal)
        amount, tier1, need = size(i, need_window_end(i, sched, cycle), bal)  # later skips not known yet
        flags: list[str] = []
        if need <= 0:
            amount, flags, reason = 0, ["skip"], "Skip: balance covers demand until the next visit"
        elif simulate_balance(bal, qh[i : i + 1], np.array([amount]), cap).closing[0] < mn:
            flags.append("capacity_shortfall")
        loads[i] = amount
        visits.append(Visit(master.tid, d, kind, amount, tier1, reason, flags))

    k = 0
    while merge:  # fold visit k+1 into k when one load covers both without a breach (PRD 6.2)
        act = [v for v in visits if "skip" not in v.flags]
        if k + 1 >= len(act):
            break
        a, b = act[k], act[k + 1]
        after = _idx(act[k + 2].date, as_of) if k + 2 < len(act) else None
        ia, ib = _idx(a.date, as_of), _idx(b.date, as_of)
        bal = _bal_before(b0, qh, loads, cap, ia)
        if a.amount + b.amount <= cap - bal:
            # amount, tier1, _ = size(ia, after - 1 if after is not None else ib + cycle - 1, bal)
            amount, tier1, _ = size(ia, need_window_end(ib, [_idx(v.date, as_of) for v in act], cycle), bal)
            trial = loads.copy()
            trial[ia], trial[ib] = amount, 0
            closing = simulate_balance(b0, qh, trial, cap).closing
            if (closing[ia : after if after is not None else h] >= mn).all():
                loads = trial
                a.amount, a.tier1_need = amount, tier1
                a.flags.append("merged")
                visits.remove(b)
                continue
        k += 1

    _apply_overrides(visits, overrides, master.tid)
    return _finish(master, fc, b0, h, sl, visits, overstock_frac, schedule_assumed)


def _apply_overrides(visits: list[Visit], overrides: list[Override], tid: str) -> None:
    """Manual overrides, applied last (PRD 6.5): move, skip (kept as a 0 'skip' visit) or replace the amount."""
    for o in overrides:
        if o.tid != tid:
            continue
        src = o.moved_from if o.moved_from is not None else o.visit_date
        v = next((x for x in visits if x.date == src), None)
        if v is None:  # no visit on that date: the user added one
            v = Visit(tid, o.visit_date, "extra", 0, 0, "Manual visit", [])
            visits.append(v)
        if o.moved_from is not None:
            v.date, v.kind = o.visit_date, "moved"
        if o.skipped:
            v.amount = 0
            if "skip" not in v.flags:
                v.flags.append("skip")
        elif o.amount is not None:
            v.amount = max(int(o.amount), 0)
            if "skip" in v.flags:
                v.flags.remove("skip")
        v.manual = True


def apply_loads(
    plan: AtmPlan,
    amounts: dict[date, int],
    fc: ForecastResult,
    sl: str,
    *,
    overstock_frac: float = OVERSTOCK_FRAC,
) -> AtmPlan:
    """Set `allocated` for the given visit dates and re-project the plan with those loads (used by allocation)."""
    visits = [
        replace(v, flags=list(v.flags), allocated=int(amounts[v.date]) if v.date in amounts else v.allocated)
        for v in plan.visits
    ]
    h = len(plan.projection_sl)
    return _finish(plan.master, fc, plan.b0, h, sl, visits, overstock_frac, plan.schedule_assumed)
