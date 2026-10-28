from dataclasses import asdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

from engine.allocate import allocate, reallocation_flows
from engine.forecast import ForecastResult
from engine.models import QCOLS
from engine.plan import project_current, recommend, simulate_balance
from engine.schema import AtmMaster

M = 1_000_000
AS_OF = date(2026, 3, 6)
DENOM = 100_000
H = 14
SL = "p90"


def _d(k: int) -> date:
    return AS_OF + timedelta(days=k)


def _master(tid: str, cap=1000 * M, fill=600 * M, cycle=4) -> AtmMaster:
    return AtmMaster(tid, tid, "mall", cap, 100 * M, cycle, DENOM, 1_000_000, fill)


def _fc(tid: str, q50: int, q90: int) -> ForecastResult:
    idx = pd.DatetimeIndex([pd.Timestamp(_d(k)) for k in range(1, 31)], name="date")
    q50a = np.full(30, q50, dtype=np.int64)
    q90a = np.full(30, q90, dtype=np.int64)
    df = pd.DataFrame(
        {"q10": q50a // 2, "q50": q50a, "q80": (q50a + q90a) // 2, "q90": q90a, "q95": q90a + q90a // 10},
        index=idx,
    )[QCOLS].astype("int64")
    return ForecastResult(
        tid=tid,
        as_of=AS_OF,
        engine_version="t",
        model="seasonal_naive",
        orders=None,
        forecast=df,
        explanations={},
        backtest={},
        lebaran_check=None,
        diagnostics={},
        fitted_q50=pd.Series(dtype="int64"),
    )


# A: breaches first (day 2), B: breaches day 4, C: over-stocked (low demand, current policy over-fills)
SPEC = {
    "A": {
        "master": _master("A"),
        "q50": 100 * M,
        "q90": 130 * M,
        "b0": 190 * M,
        "visits": [_d(2), _d(6), _d(10)],
    },
    "B": {
        "master": _master("B"),
        "q50": 100 * M,
        "q90": 130 * M,
        "b0": 600 * M,
        "visits": [_d(4), _d(8), _d(12)],
    },
    "C": {
        "master": _master("C", fill=900 * M),
        "q50": 20 * M,
        "q90": 26 * M,
        "b0": 500 * M,
        "visits": [_d(4), _d(8), _d(12)],
    },
}


def _fixture():
    fcs = {t: _fc(t, s["q50"], s["q90"]) for t, s in SPEC.items()}
    plans = [
        recommend(s["master"], fcs[t], s["b0"], AS_OF, H, SL, s["visits"], [], merge=False)
        for t, s in SPEC.items()
    ]
    current = [project_current(s["master"], fcs[t], s["b0"], AS_OF, H, s["visits"]) for t, s in SPEC.items()]
    return plans, fcs, current


def _need(plans) -> int:
    return sum(v.amount for p in plans for v in p.visits)


def _active(plan):
    return [v for v in plan.visits if "skip" not in v.flags]


def test_unconstrained_funds_everything():
    plans, fcs, _ = _fixture()
    out = allocate(plans, fcs, SL, None)
    assert out.unused == 0 and out.underfunded == 0
    assert out.need_total == _need(plans) == out.funded_total
    for p in out.plans:
        for v in p.visits:
            assert v.allocated == v.amount
            assert "underfunded" not in v.flags
    assert plans[0].visits[0].allocated is None  # input untouched


def test_budget_70pct_tier1_order():
    plans, fcs, _ = _fixture()
    need = _need(plans)
    budget = int(0.7 * need)
    out = allocate(plans, fcs, SL, budget)
    by = {p.tid: p for p in out.plans}
    first_a = _active(by["A"])[0]  # A has the earliest breach
    assert first_a.allocated >= first_a.tier1_need > 0
    allocs = [v.allocated for p in out.plans for v in p.visits]
    assert sum(allocs) <= budget
    assert out.funded_total == sum(allocs) and out.unused == budget - sum(allocs)
    assert all(a % DENOM == 0 and a >= 0 for a in allocs)
    for p in out.plans:  # no load exceeds capacity: the simulator never clamps an allocated load
        s = SPEC[p.tid]
        loads = np.zeros(H, dtype=np.int64)
        for v in p.visits:
            loads[(v.date - AS_OF).days - 1] += v.allocated
        sim = simulate_balance(
            s["b0"], fcs[p.tid].forecast["q90"].to_numpy()[:H], loads, s["master"].capacity
        )
        assert (sim.loads == loads).all()


def test_same_date_earliest_breach_first():
    # A and B both visit on day 2; A breaches on day 1, B only later -> A's Tier 1 is funded first.
    fcs = {"A": _fc("A", 100 * M, 130 * M), "B": _fc("B", 100 * M, 130 * M)}
    a = recommend(_master("A"), fcs["A"], 230 * M, AS_OF, H, SL, [_d(2)], [], merge=False)
    b = recommend(_master("B"), fcs["B"], 380 * M, AS_OF, H, SL, [_d(2)], [], merge=False)
    va = next(v for v in a.visits if v.date == _d(2))
    out = allocate([b, a], fcs, SL, va.tier1_need)
    got = {p.tid: next(v for v in p.visits if v.date == _d(2)) for p in out.plans}
    assert got["A"].allocated == va.tier1_need
    assert got["B"].allocated == 0 and "underfunded" in got["B"].flags
    assert [p.tid for p in out.plans] == ["B", "A"]  # input order kept


def test_underfunding_carries_forward():
    plans, fcs, _ = _fixture()
    a = plans[0]
    v0, v1 = _active(a)[:2]
    budget = v0.tier1_need // 2 // DENOM * DENOM
    out = allocate([a], {"A": fcs["A"]}, SL, budget)
    w0, w1 = _active(out.plans[0])[:2]
    assert w0.allocated < w0.tier1_need
    assert "underfunded" in w0.flags
    assert w0.reason.startswith("Underfunded – cash-out likely on ")
    assert w1.tier1_need > v1.tier1_need


def test_deterministic():
    plans, fcs, _ = _fixture()
    budget = int(0.6 * _need(plans))
    r1 = allocate(plans, fcs, SL, budget)
    r2 = allocate(plans, fcs, SL, budget)
    assert [[asdict(v) for v in p.visits] for p in r1.plans] == [
        [asdict(v) for v in p.visits] for p in r2.plans
    ]
    assert (r1.need_total, r1.funded_total, r1.unused, r1.underfunded) == (
        r2.need_total,
        r2.funded_total,
        r2.unused,
        r2.underfunded,
    )
    for p1, p2 in zip(r1.plans, r2.plans, strict=True):
        assert (p1.projection_sl == p2.projection_sl).all()


def test_zero_budget():
    plans, fcs, _ = _fixture()
    out = allocate(plans, fcs, SL, 0)
    assert out.funded_total == 0 and out.unused == 0
    for p in out.plans:
        assert (p.projection_sl >= 0).all() and (p.projection_p50 >= 0).all()
        for v in p.visits:
            assert v.allocated == 0
            assert v.tier1_need >= 0
            if "skip" in v.flags:
                assert "underfunded" not in v.flags
            else:
                assert "underfunded" in v.flags
    assert out.underfunded == sum(len(_active(p)) for p in out.plans) > 0


def test_budget_above_need():
    plans, fcs, _ = _fixture()
    need = _need(plans)
    out = allocate(plans, fcs, SL, need + 50 * M)
    assert out.need_total == need and out.funded_total == need
    assert out.unused == 50 * M
    assert out.underfunded == 0
    assert all(v.allocated == v.amount for p in out.plans for v in p.visits)


def test_insufficient_history_passes_through():
    plans, fcs, _ = _fixture()
    short = recommend(_master("D"), None, 300 * M, AS_OF, H, SL, [_d(2)], [])
    out = allocate([*plans, short], fcs, SL, int(0.7 * _need(plans)))
    d = out.plans[-1]
    assert d.status == "insufficient_history" and d.visits == []


def test_reallocation_flows():
    plans, fcs, current = _fixture()
    cur = {p.tid: p for p in current}
    assert cur["C"].status == "over_stocked" and cur["A"].status == "cash_out_risk"
    out = allocate(plans, fcs, SL, None)
    by = {p.tid: p for p in out.plans}
    cur_c = sum(v.amount for v in cur["C"].visits)
    alloc_c = sum(v.allocated for v in by["C"].visits)
    assert alloc_c < cur_c
    flows = reallocation_flows(current, out)
    assert flows and flows[0]["from_tid"] == "C" and flows[0]["to_tid"] == "A"
    assert all(isinstance(f["amount"], int) and f["amount"] > 0 for f in flows)
    reduction = max(0, cur_c - alloc_c)
    assert sum(f["amount"] for f in flows) <= reduction
    increase_a = sum(v.allocated for v in by["A"].visits) - sum(v.amount for v in cur["A"].visits)
    assert flows[0]["amount"] == min(reduction, increase_a)
    assert reallocation_flows(current, out) == flows
