import itertools
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from engine.backtest import lebaran_check, metrics, origins, run_backtest
from engine.models.seasonal_naive import SeasonalNaive


def test_origins_dummy():
    o = origins(date(2024, 10, 28), date(2026, 3, 6))
    assert len(o) == 8
    assert o[0] == date(2026, 2, 4)
    assert all((a - b).days == 14 for a, b in itertools.pairwise(o))


def test_origins_too_short_raises():
    with pytest.raises(ValueError):
        origins(date(2025, 1, 1), date(2025, 11, 1))


def _row(origin, k, y, q50, q10=None, q90=None):
    return {
        "origin": origin,
        "date": origin + timedelta(days=k),
        "y": y,
        "q10": q50 if q10 is None else q10,
        "q50": q50,
        "q90": q50 if q90 is None else q90,
    }


def test_metrics_formulas():
    o = date(2026, 1, 1)
    nan = float("nan")
    rows = [_row(o, 1, 100.0, 110.0), _row(o, 2, 200.0, 180.0), _row(o, 3, nan, 5.0)]
    m = metrics(rows, 30)
    assert m["wape"] == pytest.approx(30 / 300)
    assert m["mape"] == pytest.approx(np.mean([0.1, 0.1]))
    assert m["mae"] == pytest.approx(15)
    assert m["n"] == 2


def test_metrics_coverage():
    o = date(2026, 1, 1)
    rows = [_row(o, 1, 100.0, 100.0, 90.0, 110.0), _row(o, 2, 200.0, 100.0, 90.0, 110.0)]
    assert metrics(rows, 30)["coverage"] == pytest.approx(0.5)


def test_metrics_slice_by_h():
    o = date(2026, 1, 1)
    rows = [_row(o, k, 100.0, 100.0) for k in range(1, 31)]
    assert metrics(rows, 7)["n"] == 7


def _synthetic(n=420, start="2024-01-01"):
    idx = pd.date_range(start, periods=n, freq="D")
    week = np.array([1.0, 0.8, 0.9, 1.0, 1.2, 1.6, 1.4])
    y = pd.Series(5_000_000 * week[np.arange(n) % 7], index=idx)
    y.iloc[[50, 100]] = np.nan
    return y


def _holidays(y):
    last = y.index[-1].date() + timedelta(days=400)
    return pd.DataFrame(
        {
            "date": [date(2024, 4, 10), date(2025, 3, 31), last],
            "type": ["idul_fitri", "idul_fitri", "new_year"],
            "name": ["a", "b", "c"],
        }
    )


def test_backtest_no_leakage(monkeypatch):
    y = _synthetic()
    as_of = y.index[-1].date()
    seen = []
    orig_fit = SeasonalNaive.fit

    def spy(self, yy, X=None):
        seen.append(yy.index.max().date())
        return orig_fit(self, yy, X)

    monkeypatch.setattr(SeasonalNaive, "fit", spy)
    res = run_backtest(y, _holidays(y), as_of, None)
    os_ = origins(y.index[0].date(), as_of)
    assert len(seen) == len(os_)
    assert all(s <= max(os_) for s in seen)
    assert sorted(seen) == sorted(os_)
    assert "seasonal_naive" in res and "ets" in res and "sarimax" not in res
    r = res["seasonal_naive"][0]
    assert set(r) == {"origin", "date", "y", "q10", "q50", "q90"}
    assert len(res["seasonal_naive"]) == 30 * len(os_)


def test_backtest_records_failures(monkeypatch):
    y = _synthetic()

    def boom(self, yy, X=None):
        raise RuntimeError("nope")

    monkeypatch.setattr(SeasonalNaive, "fit", boom)
    res = run_backtest(y, _holidays(y), y.index[-1].date(), None)
    assert res["seasonal_naive"] == []
    assert len(res["_failures"]) == 8 and res["_failures"][0]["error"]


def test_lebaran_check_none_when_not_computable():
    y = _synthetic()
    assert lebaran_check(y, _holidays(y), y.index[-1].date(), "seasonal_naive", None) is None


def test_lebaran_check_computed():
    y = _synthetic(n=620)
    as_of = y.index[-1].date()
    out = lebaran_check(y, _holidays(y), as_of, "seasonal_naive", None)
    assert out is not None
    assert out["fitri_day"] == date(2025, 3, 31)
    assert out["origin"] == date(2025, 3, 17)
    assert out["metrics"]["n"] == 30
