from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from engine.allocate import Allocation
from engine.compare import build_demand_source, compare, policy_stats
from engine.plan import AtmPlan, Visit
from engine.schema import AtmMaster

M = 1_000_000
AS_OF = date(2026, 3, 1)


def _d(k: int) -> date:
    return AS_OF + timedelta(days=k)


def _master(tid="T1"):
    # capacity 100M, min 10M, cycle 7, denom 100k, cost/visit 5M, fill level 80M
    return AtmMaster(tid, "x", "mall", 100 * M, 10 * M, 7, 100_000, 5 * M, 80 * M)


def _plan(visits, tid="T1", b0=30 * M, status="ok", h=3):
    z = np.zeros(h, dtype=np.int64)
    return AtmPlan(tid, _master(tid), status, None, b0, visits, z, z, False)


def _v(k, amount, tid="T1", flags=None, allocated=None):
    return Visit(tid, _d(k), "scheduled", amount, 0, "r", flags or [], allocated=allocated)


DEMAND = {"T1": np.array([20 * M, 50 * M, 40 * M])}


def test_policy_stats_hand_case():
    # day1: 30-20 -> 10 | day2: load 60 -> 70-50 -> 20 | day3: 20, demand 40 -> 0 (cash-out); skip on day3
    plan = _plan([_v(2, 60 * M), _v(3, 0, flags=["skip"])])
    empty = _plan([], tid="T2", status="insufficient_history", h=0)
    s = policy_stats([plan, empty], DEMAND, 3, 0.06, as_of=AS_OF)
    assert s.cash_out_days == 1
    assert s.idle_cash == 3_333_333  # mean(0, 10M, 0)
    assert s.idle_cost == 1644  # round(3_333_333.3 * 1 * 0.06 * 3 / 365)
    assert s.visits == 1
    assert s.visit_cost == 5 * M
    assert s.loaded == 60 * M
    assert all(type(x) is int for x in vars(s).values())


def test_policy_stats_uses_allocated_over_amount():
    plan = _plan([_v(2, 60 * M, allocated=30 * M)])
    s = policy_stats([plan], DEMAND, 3, 0.06, as_of=AS_OF)
    # day2: 10+30 < 50 -> 0 (cash-out), day3: 0 (cash-out)
    assert (s.cash_out_days, s.loaded, s.idle_cash) == (2, 30 * M, 0)


def test_policy_stats_current_rule_reapplied_on_demand():
    # current policy re-applies "top up to fill level (80M)" against this demand, ignoring stored amount
    plan = _plan([_v(2, 1)])
    s = policy_stats([plan], DEMAND, 3, 0.06, as_of=AS_OF, current=True)
    # day2: balance 10 -> load 70 -> 80-50 -> 30 | day3: 30, demand 40 -> 0 (cash-out)
    assert (s.cash_out_days, s.loaded, s.visits, s.idle_cash) == (1, 70 * M, 1, 6_666_667)


def test_policy_stats_zero_effective_load_is_not_a_visit():
    plan = _plan([_v(1, 0)], b0=80 * M)  # current: already at fill level -> load 0
    s = policy_stats([plan], DEMAND, 3, 0.06, as_of=AS_OF, current=True)
    assert (s.visits, s.visit_cost, s.loaded) == (0, 0, 0)


def _log(tid, start, withdrawals, closings):
    rows = []
    for k, (w, c) in enumerate(zip(withdrawals, closings, strict=True)):
        rows.append(
            {
                "tid": tid,
                "date": start + timedelta(days=k),
                "opening_balance": c + w,
                "withdrawal": w,
                "replenishment": 0,
                "closing_balance": c,
            }
        )
    return pd.DataFrame(rows)


def _fc(q50_by_day: dict[int, int], fitted: dict[date, int] | None = None):
    idx = pd.DatetimeIndex([pd.Timestamp(_d(k)) for k in range(1, 31)])
    q50 = [q50_by_day.get(k, 0) for k in range(1, 31)]
    fitted = fitted or {}
    fq = pd.Series(list(fitted.values()), index=pd.DatetimeIndex([pd.Timestamp(d) for d in fitted]))
    return SimpleNamespace(as_of=AS_OF, forecast=pd.DataFrame({"q50": q50}, index=idx), fitted_q50=fq)


def test_replay_none_when_future():
    log = _log("T1", _d(-5), [1] * 8, [5] * 8)  # last date = as_of + 2
    assert build_demand_source(log, None, {"T1": _fc({})}, AS_OF, 3) is None
    assert build_demand_source(log, None, {"T1": _fc({})}, AS_OF, 2) is not None


def test_estimated_basis_uses_max_on_censored_days():
    # days 1..4: logged 10, 5, 7, 40; closing 0 on days 2 and 4 (censored)
    log = _log("T1", _d(1), [10 * M, 5 * M, 7 * M, 40 * M], [50 * M, 0, 20 * M, 0])
    fc = _fc({1: 99 * M, 2: 30 * M, 3: 99 * M, 4: 25 * M})
    src = build_demand_source(log, None, {"T1": fc}, AS_OF, 4)
    assert src.basis == "estimated"
    # censored: max(logged, q50) -> day2 30M (q50 larger), day4 40M (logged larger); others logged
    assert src.demand["T1"].tolist() == [10 * M, 30 * M, 7 * M, 40 * M]


def test_estimated_basis_prefers_fitted_q50_for_dates_up_to_forecast_as_of():
    # replay window (as_of-1 .. as_of) lies at/before the forecast's as_of: covered by fitted_q50
    fc = _fc({1: 99 * M}, fitted={_d(-1): 9 * M, _d(0): 8 * M})
    log = _log("T1", _d(-1), [1 * M, 1 * M, 1 * M], [0, 0, 0])
    src = build_demand_source(log, None, {"T1": fc}, AS_OF - timedelta(days=2), 2)
    assert src.demand["T1"].tolist() == [9 * M, 8 * M]


def test_true_demand_basis():
    log = _log("T1", _d(1), [10 * M, 5 * M], [50 * M, 0])
    td = pd.DataFrame({"tid": ["T1", "T1"], "date": [_d(1), _d(2)], "true_demand": [11 * M, 60 * M]})
    src = build_demand_source(log, td, {"T1": _fc({})}, AS_OF, 2)
    assert src.basis == "true_demand"
    assert src.demand["T1"].tolist() == [11 * M, 60 * M]


def test_compare_shape_and_ints():
    cur = _plan([_v(2, 1)])
    rec = _plan([_v(2, 60 * M)])
    alloc = Allocation([rec], 60 * M, 60 * M, 0, 0)
    out = compare([cur], alloc, DEMAND, None, 0.06, 3, as_of=AS_OF)
    assert out["replay"] is None
    assert out["current"]["loaded"] == 70 * M  # current rule re-applied on the given demand
    assert out["recommended"]["loaded"] == 60 * M
    keys = {"cash_out_days", "idle_cash", "idle_cost", "visits", "visit_cost", "loaded"}
    assert set(out["current"]) == keys == set(out["recommended"])

    log = _log("T1", _d(1), [20 * M, 50 * M, 40 * M], [10 * M, 10 * M, 10 * M])
    src = build_demand_source(log, None, {"T1": _fc({})}, AS_OF, 3)
    out = compare([cur], alloc, DEMAND, src, 0.06, 3, as_of=AS_OF)
    assert out["replay"]["basis"] == "estimated"
    assert out["replay"]["recommended"] == out["recommended"]
    assert all(type(x) is int for x in out["replay"]["current"].values())
