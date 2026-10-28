from datetime import date, timedelta

import numpy as np
import pandas as pd

from engine.forecast import ForecastResult
from engine.models import QCOLS
from engine.plan import apply_loads, project_current, recommend
from engine.schema import AtmMaster, Override

M = 1_000_000
AS_OF = date(2026, 3, 6)
DENOM = 100_000


def _d(k: int) -> date:
    return AS_OF + timedelta(days=k)


def _master(cap=1000 * M, fill=600 * M, cycle=4):
    return AtmMaster("T1", "x", "mall", cap, 100 * M, cycle, DENOM, 1_000_000, fill)


def _fc(q50=100 * M, q90=130 * M, explanations=None) -> ForecastResult:
    idx = pd.DatetimeIndex([pd.Timestamp(_d(k)) for k in range(1, 31)], name="date")
    q50 = np.broadcast_to(np.asarray(q50, dtype=np.int64), (30,))
    q90 = np.broadcast_to(np.asarray(q90, dtype=np.int64), (30,))
    df = pd.DataFrame(
        {"q10": q50 // 2, "q50": q50, "q80": (q50 + q90) // 2, "q90": q90, "q95": q90 + q90 // 10},
        index=idx,
    )[QCOLS].astype("int64")
    return ForecastResult(
        tid="T1",
        as_of=AS_OF,
        engine_version="t",
        model="seasonal_naive",
        orders=None,
        forecast=df,
        explanations=explanations or {},
        backtest={},
        lebaran_check=None,
        diagnostics={},
        fitted_q50=pd.Series(dtype="int64"),
    )


def _round_up(x: int) -> int:
    return -(-x // DENOM) * DENOM


def test_current_policy_status_risk():
    plan = project_current(_master(), _fc(), 450 * M, AS_OF, 14, [_d(4), _d(8), _d(12)])
    assert plan.status == "cash_out_risk"
    assert [v.date for v in plan.visits] == [_d(4), _d(8), _d(12)]
    assert all(v.kind == "scheduled" and v.amount >= 0 for v in plan.visits)
    # p50: 350, 250, 150 then top up to 600 on day 4
    assert plan.visits[0].amount == 450 * M
    assert plan.visits[0].reason == "Current policy: top up to Rp 600.000.000"
    assert plan.projection_p50[:4].tolist() == [350 * M, 250 * M, 150 * M, 500 * M]
    assert len(plan.projection_p50) == 14 and len(plan.projection_sl) == 14


def test_overstock_status():
    plan = project_current(_master(), _fc(q50=10 * M, q90=13 * M), 450 * M, AS_OF, 14, [_d(4), _d(8)])
    assert plan.status == "over_stocked"
    assert plan.days_of_cash is None


def test_days_of_cash():
    plan = project_current(_master(), _fc(), 450 * M, AS_OF, 14, [])
    # p50 closings 350, 250, 150, 50 -> below min on day 4
    assert plan.days_of_cash == 4
    assert plan.status == "cash_out_risk"


def test_status_risk_when_balance_below_min():
    plan = project_current(_master(), _fc(q50=10 * M, q90=13 * M), 50 * M, AS_OF, 14, [_d(4)])
    assert plan.status == "cash_out_risk"
    assert plan.days_of_cash == 0


def test_status_risk_beyond_next_visit():
    # visit on day 1 tops up to 600; p50 100/day (p90 only 101) -> runs dry on day 7, after the visit
    plan = project_current(_master(), _fc(q50=100 * M, q90=101 * M), 250 * M, AS_OF, 14, [_d(1)])
    assert plan.status == "cash_out_risk"


def test_status_imminent_risk_precedes_overstock():
    # p50 balance before the visit (day 4) is high, but p90 is below min on day 1 before it
    plan = project_current(_master(), _fc(q50=10 * M, q90=400 * M), 450 * M, AS_OF, 14, [_d(4)])
    assert plan.status == "cash_out_risk"


def test_status_overstock_precedes_later_cash_out():
    # over-stocked at the visit on day 2 (p50 opening 440 > 300); p90 fine before it; later p50 cash-out
    fc = _fc(q50=np.array([10 * M] * 2 + [300 * M] * 28), q90=np.array([20 * M] * 2 + [310 * M] * 28))
    plan = project_current(_master(), fc, 450 * M, AS_OF, 14, [_d(2)])
    assert plan.projection_p50.min() == 0 or plan.projection_p50[-1] < 100 * M
    assert plan.status == "over_stocked"


def test_need_formula_rounding():
    plan = recommend(_master(), _fc(), 450 * M, AS_OF, 14, "p90", [_d(2), _d(6)], [], merge=False)
    v = plan.visits[0]
    assert v.date == _d(2) and v.kind == "scheduled"
    before = 450 * M - 130 * M
    assert v.amount == min(_round_up(4 * 130 * M + 100 * M - before), 1000 * M - before)
    assert v.tier1_need == _round_up(4 * 100 * M + 100 * M - before)
    # non-round balance -> rounds UP to the denomination
    b0 = 450 * M + 30_000
    plan = recommend(_master(), _fc(), b0, AS_OF, 14, "p90", [_d(2), _d(6)], [], merge=False)
    before = b0 - 130 * M
    assert plan.visits[0].amount == _round_up(4 * 130 * M + 100 * M - before)
    assert plan.visits[0].amount % DENOM == 0
    # capped at cap - balance before load (sl p95 over a huge window)
    plan = recommend(_master(cap=600 * M), _fc(), 450 * M, AS_OF, 14, "p95", [_d(2), _d(6)], [], merge=False)
    assert plan.visits[0].amount == 600 * M - (450 * M - 143 * M)


def test_skip_when_need_nonpositive():
    plan = recommend(
        _master(), _fc(q50=40 * M, q90=50 * M), 450 * M, AS_OF, 5, "p90", [_d(2)], [], merge=False
    )
    v = plan.visits[0]
    assert v.date == _d(2) and v.amount == 0 and v.flags == ["skip"]
    assert plan.projection_sl.tolist() == [(450 - 50 * k) * M for k in range(1, 6)]


def test_extra_visit_inserted_on_peak():
    q90 = np.full(30, 600 * M, dtype=np.int64)
    q90[5] = 950 * M  # day 6: even a full machine ends below min
    expl = {_d(1): ["pre-Lebaran +120%", "payday"]}
    plan = recommend(
        _master(), _fc(q50=400 * M, q90=q90, explanations=expl), 450 * M, AS_OF, 7, "p90", [_d(4)], []
    )
    dates = [v.date for v in plan.visits]
    assert len(dates) == len(set(dates))
    assert dates == [_d(k) for k in range(1, 8)]
    extra = plan.visits[0]
    assert extra.kind == "extra"
    assert extra.reason == "Below safe minimum on 7 Mar (pre-Lebaran +120%)"
    assert plan.visits[1].reason == "Below safe minimum on 8 Mar"
    assert plan.visits[3].kind == "scheduled"
    assert "capacity_shortfall" in plan.visits[5].flags
    assert all("capacity_shortfall" not in v.flags for i, v in enumerate(plan.visits) if i != 5)
    assert all(0 <= v.amount <= 1000 * M for v in plan.visits)


def test_merge_suggested():
    fc = _fc(q50=80 * M, q90=100 * M)
    visits = [_d(1), _d(5), _d(9), _d(13)]
    plain = recommend(_master(), fc, 100 * M, AS_OF, 14, "p90", visits, [], merge=False)
    assert [v.amount for v in plain.visits] == [400 * M] * 4
    plan = recommend(_master(), fc, 100 * M, AS_OF, 14, "p90", visits, [])
    assert [v.date for v in plan.visits] == [_d(1), _d(9)]
    assert all("merged" in v.flags for v in plan.visits)
    assert [v.amount for v in plan.visits] == [800 * M, 800 * M]
    assert (plan.projection_sl >= 100 * M).all()


def test_override_amount_and_skip():
    ov = [
        Override("T1", _d(2), 500 * M),
        Override("T1", _d(6), None, skipped=True),
        Override("OTHER", _d(2), 1 * M),
    ]
    plan = recommend(_master(), _fc(), 450 * M, AS_OF, 14, "p90", [_d(2), _d(6)], ov, merge=False)
    by_date = {v.date: v for v in plan.visits}
    assert by_date[_d(2)].amount == 500 * M and by_date[_d(2)].manual
    assert by_date[_d(6)].amount == 0 and "skip" in by_date[_d(6)].flags and by_date[_d(6)].manual
    assert plan.projection_sl[1] == 320 * M + 500 * M - 130 * M
    assert plan.projection_sl[5] == plan.projection_sl[4] - 130 * M


def test_override_move():
    ov = [Override("T1", _d(3), None, moved_from=_d(2))]
    plan = recommend(_master(), _fc(), 450 * M, AS_OF, 14, "p90", [_d(2), _d(6)], ov, merge=False)
    dates = [v.date for v in plan.visits]
    assert _d(2) not in dates
    moved = next(v for v in plan.visits if v.date == _d(3))
    assert moved.kind == "moved" and moved.manual and moved.amount == 300 * M
    assert plan.projection_sl[2] == 190 * M + 300 * M - 130 * M


def test_capacity_below_balance_never_negative_load():
    master = _master(cap=300 * M, fill=800 * M)
    cur = project_current(master, _fc(), 450 * M, AS_OF, 14, [_d(1), _d(5), _d(9)])
    rec = recommend(master, _fc(), 450 * M, AS_OF, 14, "p90", [_d(1), _d(5), _d(9)], [])
    for plan in (cur, rec):
        assert all(v.amount >= 0 for v in plan.visits)
        assert (plan.projection_sl >= 0).all() and (plan.projection_p50 >= 0).all()
    assert cur.visits[0].amount == 0


def test_insufficient_history_plan():
    for plan in (
        project_current(_master(), None, 450 * M, AS_OF, 14, [_d(2)]),
        recommend(_master(), None, 450 * M, AS_OF, 14, "p90", [_d(2)], []),
    ):
        assert plan.status == "insufficient_history"
        assert plan.visits == []
        assert plan.days_of_cash is None


def test_apply_loads_reprojects():
    plan = recommend(_master(), _fc(), 450 * M, AS_OF, 14, "p90", [_d(2), _d(6)], [], merge=False)
    out = apply_loads(plan, {_d(2): 100 * M}, _fc(), "p90")
    v = next(v for v in out.visits if v.date == _d(2))
    assert v.allocated == 100 * M and v.amount == plan.visits[0].amount
    assert out.projection_sl[1] == 320 * M + 100 * M - 130 * M
    assert plan.visits[0].allocated is None  # input untouched
