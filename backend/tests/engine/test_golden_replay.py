"""Golden replay test on the shipped dummy data (PRD AC8). Slow: full forecast pipeline per TID."""

from concurrent.futures import ProcessPoolExecutor
from datetime import date

import pandas as pd
import pytest

from engine.allocate import allocate
from engine.compare import build_demand_source, compare, policy_stats
from engine.forecast import run_tid
from engine.plan import project_current, recommend
from engine.schedule import scheduled_visits

pytestmark = pytest.mark.slow

AS_OF, H, SL, RATE = date(2026, 3, 1), 30, "p90", 0.06
IDLE_TIDS = ["TID-DPK-0004", "TID-BKS-0005", "TID-JKT-0008"]


def test_golden_replay(seed_dir, log_df, holidays_df, master_list):
    masters = {m.tid: m for m in master_list}
    tids = sorted(log_df["tid"].unique())
    assert len(tids) == 10
    with ProcessPoolExecutor() as ex:
        futs = {t: ex.submit(run_tid, t, log_df, holidays_df, AS_OF) for t in tids}
        fcs = {t: f.result() for t, f in futs.items()}

    current, recs = [], []
    for tid in tids:
        m, fc, sel = masters[tid], fcs[tid], log_df[log_df["tid"] == tid]
        assert fc is not None, tid
        b0 = int(sel.loc[sel["date"] == AS_OF, "closing_balance"].iloc[0])
        dates, assumed = scheduled_visits(m, sel, AS_OF, H)
        current.append(project_current(m, fc, b0, AS_OF, H, dates, schedule_assumed=assumed))
        recs.append(recommend(m, fc, b0, AS_OF, H, SL, dates, [], schedule_assumed=assumed))
    alloc = allocate(recs, fcs, SL, None)

    true_demand = pd.read_csv(seed_dir / "atm_true_demand.csv")
    true_demand["date"] = pd.to_datetime(true_demand["date"]).dt.date
    src = build_demand_source(log_df, true_demand, fcs, AS_OF, H)
    assert src is not None and src.basis == "true_demand"
    q50 = {t: fcs[t].forecast["q50"].to_numpy()[:H] for t in tids}
    out = compare(current, alloc, q50, src, RATE, H, as_of=AS_OF)
    rep = out["replay"]

    lines = [f"{'tid':14s} {'co_cur':>6s} {'co_rec':>6s} {'idle_cur':>14s} {'idle_rec':>14s}"]
    per = {}
    for c, r in zip(current, alloc.plans, strict=True):
        sc = policy_stats([c], src.demand, H, RATE, as_of=AS_OF, current=True)
        sr = policy_stats([r], src.demand, H, RATE, as_of=AS_OF)
        per[c.tid] = (sc, sr)
        lines.append(
            f"{c.tid:14s} {sc.cash_out_days:6d} {sr.cash_out_days:6d} {sc.idle_cash:14,d} {sr.idle_cash:14,d}"
        )
    lines.append(f"fleet replay current={rep['current']}")
    lines.append(f"fleet replay recommended={rep['recommended']}")
    msg = "\n".join(lines)
    print("\n" + msg)

    assert rep["recommended"]["cash_out_days"] < rep["current"]["cash_out_days"], msg
    for tid in IDLE_TIDS:
        sc, sr = per[tid]
        assert sr.idle_cash < sc.idle_cash, f"{tid}\n{msg}"
