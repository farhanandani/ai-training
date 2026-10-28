"""Budget allocation ("cross-subsidy", PRD 6.3, TR-30, TR-32) and re-allocation flows (TR-36)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np

from .plan import SL_COL, AtmPlan, Visit, _bal_before, _idx, _q, apply_loads, simulate_balance, size_load

if TYPE_CHECKING:
    from .forecast import ForecastResult

UNDERFUNDED = "underfunded"


@dataclass
class Allocation:
    plans: list[AtmPlan]
    need_total: int
    funded_total: int
    unused: int
    underfunded: int


@dataclass
class _State:
    """Mutable allocation state of one ATM (only plans that have a forecast)."""

    plan: AtmPlan
    fc: ForecastResult
    q: np.ndarray  # service-level quantile, full 30 days
    q50: np.ndarray
    qh: np.ndarray  # q[:h], the projection demand
    alloc: list[int | None]  # per visit (plan.visits order); None = not decided yet (load 0)
    tier1: list[int]  # per visit, recomputed Tier-1 need

    @property
    def h(self) -> int:
        return len(self.qh)

    def loads(self) -> np.ndarray:
        loads = np.zeros(self.h, dtype=np.int64)
        for v, a in zip(self.plan.visits, self.alloc, strict=True):
            i = _idx(v.date, self.fc.as_of)
            if a and 0 <= i < self.h:
                loads[i] += a
        return loads

    def bal_before(self, k: int) -> int:
        cap = self.plan.master.capacity
        return _bal_before(
            self.plan.b0, self.qh, self.loads(), cap, _idx(self.plan.visits[k].date, self.fc.as_of)
        )

    def breach(self) -> int:
        """Index of the first day the q_sl projection (allocation so far) closes below min; h if none."""
        m = self.plan.master
        below = np.flatnonzero(
            simulate_balance(self.plan.b0, self.qh, self.loads(), m.capacity).closing < m.min_safe_balance
        )
        return int(below[0]) if len(below) else self.h

    def need_tier1(self, k: int) -> int:
        """Tier-1 (p50) need of visit k under the allocation so far: same formula as the plan (size_load)."""
        m, v = self.plan.master, self.plan.visits[k]
        i = _idx(v.date, self.fc.as_of)
        nxt = next(
            (
                _idx(u.date, self.fc.as_of)
                for u in self.plan.visits
                if u.date > v.date and "skip" not in u.flags
            ),
            None,
        )
        end = nxt - 1 if nxt is not None else i + m.replenish_cycle_days - 1
        return size_load(
            self.q, self.q50, i, end, self.bal_before(k), m.capacity, m.min_safe_balance, m.denomination
        )[1]

    def slack(self, k: int) -> int:
        """Largest extra load on visit k that never makes the simulator clamp this or a later allocated load."""
        cap = self.plan.master.capacity
        room = cap - self.bal_before(k) - (self.alloc[k] or 0)
        for u in range(k + 1, len(self.plan.visits)):
            if self.alloc[u]:
                room = min(room, cap - self.bal_before(u) - self.alloc[u])
        return max(room, 0)


def _fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _reproject(plan: AtmPlan, allocs: list[int], fc: ForecastResult, sl: str) -> AtmPlan:
    """Set `allocated` per visit (by position, so two visits on one date stay distinct) and re-project."""
    visits = [
        replace(v, flags=list(v.flags), allocated=int(a)) for v, a in zip(plan.visits, allocs, strict=True)
    ]
    return apply_loads(replace(plan, visits=visits), {}, fc, sl)


def _is_skip(v: Visit) -> bool:
    return "skip" in v.flags


def allocate(
    plans: list[AtmPlan], forecasts: dict[str, ForecastResult], sl: str, budget: int | None
) -> Allocation:
    """Allocate a total budget across all ATMs' visits (PRD 6.3).

    budget None or >= need: everything funded. Otherwise: manual visits first (fixed demand, date order),
    then a full Tier-1 pass (p50 need, date order, TR-32 tie-break, re-projected after each allocation),
    then Tier 2 proportional to max(0, amount - tier1_need), rounded down and capacity-capped."""
    need_total = sum(int(v.amount) for p in plans for v in p.visits)
    if budget is None or budget >= need_total:
        out = [
            p
            if p.status == "insufficient_history"
            else _reproject(p, [int(v.amount) for v in p.visits], forecasts[p.tid], sl)
            for p in plans
        ]
        unused = 0 if budget is None else int(budget) - need_total
        return Allocation(out, need_total, need_total, unused, 0)

    states: dict[int, _State] = {}
    for n, p in enumerate(plans):
        if p.status == "insufficient_history":
            continue
        fc = forecasts[p.tid]
        q = _q(fc, SL_COL[sl])
        states[n] = _State(
            p,
            fc,
            q,
            _q(fc, "q50"),
            q[: len(p.projection_sl)],
            [0 if _is_skip(v) else None for v in p.visits],
            [int(v.tier1_need) for v in p.visits],
        )
    remaining = max(int(budget), 0)

    def take(want: int, step: int) -> int:
        nonlocal remaining
        a = max(min(int(want), remaining // step * step), 0)
        remaining -= a
        return a

    todo = [
        (st.plan.visits[k].date, st.plan.tid, n, k) for n, st in states.items() for k in range(len(st.alloc))
    ]
    todo = sorted(t for t in todo if not _is_skip(states[t[2]].plan.visits[t[3]]))

    # Manual visits: the user's decision, funded first as fixed demand (date order).
    for _, _, n, k in todo:
        st = states[n]
        v = st.plan.visits[k]
        if v.manual:
            amt = max(int(v.amount), 0)
            if amt <= remaining:  # funded as entered (manual amounts are not re-rounded)
                st.alloc[k] = amt
                remaining -= amt
            else:
                st.alloc[k] = take(amt, st.plan.master.denomination)

    # Tier 1: full pass in date order; within a date earliest breach, larger deficit, tid (TR-32).
    auto = [t for t in todo if not states[t[2]].plan.visits[t[3]].manual]
    for d in sorted({t[0] for t in auto}):
        pending = [(n, k) for dd, _, n, k in auto if dd == d]
        while pending:
            keyed = []
            for n, k in pending:
                st = states[n]
                t1 = st.need_tier1(k)
                keyed.append((st.breach(), -t1, st.plan.tid, n, k, t1))
            _, _, _, n, k, t1 = min(keyed)
            st = states[n]
            st.tier1[k] = t1
            st.alloc[k] = take(t1, st.plan.master.denomination)
            pending.remove((n, k))

    # Tier 2: the remainder in proportion to each visit's p50 -> p_service gap.
    gaps = {(n, k): max(int(states[n].plan.visits[k].amount) - states[n].tier1[k], 0) for _, _, n, k in auto}
    total_gap, pool = sum(gaps.values()), remaining
    if total_gap > 0 and pool > 0:
        for _, _, n, k in auto:
            st = states[n]
            step = st.plan.master.denomination
            share = pool * gaps[(n, k)] // total_gap
            x = min(share, int(st.plan.visits[k].amount) - st.alloc[k], st.slack(k), remaining)
            x = max(x, 0) // step * step
            st.alloc[k] += x
            remaining -= x

    out: list[AtmPlan] = []
    underfunded = 0
    for n, p in enumerate(plans):
        if n not in states:
            out.append(p)
            continue
        st = states[n]
        allocs = [int(a or 0) for a in st.alloc]
        new = _reproject(p, allocs, st.fc, sl)
        mn = p.master.min_safe_balance
        for k, v in enumerate(new.visits):
            if _is_skip(v):
                continue
            if not v.manual:
                v.tier1_need = st.tier1[k]
            short = v.allocated < (v.amount if v.manual else v.tier1_need)
            if short:
                i = _idx(v.date, st.fc.as_of)
                below = np.flatnonzero(new.projection_p50[i:] < mn)
                when = v.date + timedelta(days=int(below[0])) if len(below) else v.date
                v.flags.append(UNDERFUNDED)
                v.reason = f"Underfunded – cash-out likely on {_fmt_date(when)}"
                underfunded += 1
        out.append(new)
    funded = sum(int(v.allocated or 0) for p in out for v in p.visits)
    return Allocation(out, need_total, funded, int(budget) - funded, underfunded)


def reallocation_flows(current: list[AtmPlan], alloc: Allocation) -> list[dict]:
    """TR-36: cash freed at over-stocked ATMs (vs the current policy) moved to at-risk ATMs, greedy largest first."""
    allocated = {
        p.tid: sum(int(v.allocated if v.allocated is not None else v.amount) for v in p.visits)
        for p in alloc.plans
    }
    give: list[list] = []
    get: list[list] = []
    for p in current:
        if p.tid not in allocated:
            continue
        cur = sum(int(v.amount) for v in p.visits)
        if p.status == "over_stocked" and cur > allocated[p.tid]:
            give.append([cur - allocated[p.tid], p.tid])
        elif p.status == "cash_out_risk" and allocated[p.tid] > cur:
            get.append([allocated[p.tid] - cur, p.tid])
    give.sort(key=lambda x: (-x[0], x[1]))
    get.sort(key=lambda x: (-x[0], x[1]))
    flows: list[dict] = []
    i = j = 0
    while i < len(give) and j < len(get):
        amt = min(give[i][0], get[j][0])
        flows.append({"from_tid": give[i][1], "to_tid": get[j][1], "amount": int(amt)})
        give[i][0] -= amt
        get[j][0] -= amt
        if give[i][0] == 0:
            i += 1
        if get[j][0] == 0:
            j += 1
    return flows
