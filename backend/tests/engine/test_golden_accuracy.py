"""Golden accuracy tests on the shipped dummy data (PRD AC3, AC4). Slow: full pipeline per TID."""

from concurrent.futures import ProcessPoolExecutor
from datetime import date

import pandas as pd
import pytest

from engine.backtest import metrics
from engine.forecast import SELECTION_H, run_tid

pytestmark = pytest.mark.slow


def _run_all(tids, log, holidays, as_of):
    with ProcessPoolExecutor() as ex:
        futs = {t: ex.submit(run_tid, t, log, holidays, as_of) for t in tids}
        return {t: f.result() for t, f in futs.items()}


def test_golden_accuracy(log_df, holidays_df):
    as_of = date(2026, 3, 6)
    tids = sorted(log_df["tid"].unique())
    assert len(tids) == 10
    results = _run_all(tids, log_df, holidays_df, as_of)
    wins = 0
    lines = []
    for tid, r in results.items():
        chosen = metrics(r.backtest[r.model], SELECTION_H)["wape"]
        naive = metrics(r.backtest["seasonal_naive"], SELECTION_H)["wape"]
        beat = chosen < naive
        wins += beat
        lines.append(f"{tid} {r.model:15s} chosen={chosen:.4f} naive={naive:.4f} beat={beat}")
    print("\n" + "\n".join(lines))
    assert wins >= 7, "\n".join(lines)


@pytest.mark.parametrize("tid", ["TID-TNG-0006", "TID-JKT-0007"])
def test_golden_lebaran(tid, log_df, holidays_df):
    as_of = date(2026, 3, 1)
    r = run_tid(tid, log_df, holidays_df, as_of)
    sel = log_df[log_df["tid"] == tid]
    g = sel[(sel["date"] >= date(2026, 3, 2)) & (sel["date"] <= date(2026, 3, 22))]
    actual = pd.Series(g["withdrawal"].to_numpy(dtype=float), index=pd.to_datetime(g["date"]))
    peak = actual.idxmax()
    q10, q90 = r.forecast.loc[peak, "q10"], r.forecast.loc[peak, "q90"]
    msg = f"{tid} model={r.model} peak={peak.date()} actual={actual[peak]:.0f} band=[{q10}, {q90}]"
    print("\n" + msg)
    assert isinstance(peak, pd.Timestamp)
    assert q10 <= actual[peak] <= q90, msg
