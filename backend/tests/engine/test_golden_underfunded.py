"""F1 regression on the shipped dummy data: underfunded flags under real forecasts (pre-Lebaran 2026).
Slow: full forecast pipeline per TID."""

import itertools
from concurrent.futures import ProcessPoolExecutor
from datetime import date

import pytest

from engine.allocate import allocate
from engine.forecast import run_tid
from engine.plan import recommend
from engine.schedule import scheduled_visits

pytestmark = pytest.mark.slow

AS_OF, H, SL, STEP = date(2026, 3, 6), 21, "p90", 100_000


def test_underfunded_flags_on_final_allocation(log_df, holidays_df, master_list):
    masters = {m.tid: m for m in master_list}
    tids = sorted(log_df["tid"].unique())
    with ProcessPoolExecutor() as ex:
        futs = {t: ex.submit(run_tid, t, log_df, holidays_df, AS_OF) for t in tids}
        fcs = {t: f.result() for t, f in futs.items()}
    recs = []
    for tid in tids:
        m, sel = masters[tid], log_df[log_df["tid"] == tid]
        b0 = int(sel.loc[sel["date"] == AS_OF, "closing_balance"].iloc[0])
        dates, assumed = scheduled_visits(m, sel, AS_OF, H)
        recs.append(recommend(m, fcs[tid], b0, AS_OF, H, SL, dates, [], schedule_assumed=assumed))
    need = sum(v.amount for p in recs for v in p.visits)

    counts = []
    for pct in range(0, 101, 5):
        budget = need * pct // 100 // STEP * STEP
        out = allocate(recs, fcs, SL, budget)
        full = [
            v for p in out.plans for v in p.visits if "underfunded" in v.flags and v.allocated >= v.amount
        ]
        assert not full, (pct, [(v.tid, v.date, v.amount, v.allocated, v.tier1_need) for v in full])
        counts.append(out.underfunded)
    assert all(a >= b for a, b in itertools.pairwise(counts)), counts
    assert counts[-1] == 0
