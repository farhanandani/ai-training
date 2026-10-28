import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import engine.forecast as fc
from engine.calendar import HolidaysNotCovered
from engine.forecast import ForecastResult, run_tid, select_model
from engine.models import QCOLS
from engine.models.sarimax import Sarimax

AS_OF = date(2026, 3, 6)
NAMES = {"seasonal_naive", "ets", "sarimax"}
FIXED_ORDERS = ((1, 1, 1), (1, 0, 1, 7), 0.0)


def _stub_backtest(y, holidays, as_of, sarimax_orders):
    return {"seasonal_naive": [], "ets": [], "sarimax": [], "_failures": []}


def test_run_tid_shapes(log_df, holidays_df):
    r = run_tid("TID-JKT-0008", log_df, holidays_df, AS_OF)
    assert isinstance(r, ForecastResult)
    assert len(r.forecast) == 30
    assert r.forecast.index[0].date() == date(2026, 3, 7)
    assert list(r.forecast.columns) == QCOLS
    assert all(pd.api.types.is_integer_dtype(r.forecast[c]) for c in QCOLS)
    assert r.model in NAMES
    assert pd.api.types.is_integer_dtype(r.fitted_q50)
    payload = r.to_payload()
    json.dumps(payload)
    back = ForecastResult.from_payload(json.loads(json.dumps(payload)))
    assert back.model == r.model
    assert back.as_of == r.as_of
    np.testing.assert_array_equal(back.forecast[QCOLS].to_numpy(), r.forecast[QCOLS].to_numpy())
    np.testing.assert_array_equal(back.fitted_q50.to_numpy(), r.fitted_q50.to_numpy())


def test_short_history_returns_none(log_df, holidays_df):
    tid = "TID-JKT-0008"
    short = log_df[(log_df["tid"] == tid) & (log_df["date"] > AS_OF - timedelta(days=200))]
    assert run_tid(tid, short, holidays_df, AS_OF) is None


def test_holidays_not_covered_raises(log_df, holidays_df):
    short = holidays_df[holidays_df["date"] <= AS_OF + timedelta(days=10)]
    with pytest.raises(HolidaysNotCovered):
        run_tid("TID-JKT-0008", log_df, short, AS_OF)


def test_selection_tie_prefers_simpler(monkeypatch):
    monkeypatch.setattr(fc, "metrics", lambda rows, h: {"wape": 0.2})
    bt = {"seasonal_naive": [], "ets": [], "sarimax": [], "_failures": []}
    assert select_model(bt, 8) == "seasonal_naive"


def test_selection_excludes_model_failing_most_origins(monkeypatch):
    wape = {"seasonal_naive": 0.3, "ets": 0.25, "sarimax": 0.1}
    bt = {n: [{"model": n}] for n in wape}
    monkeypatch.setattr(fc, "metrics", lambda rows, h: {"wape": wape[rows[0]["model"]]})
    bt["_failures"] = [{"origin": date(2026, 1, i), "error": "sarimax: boom"} for i in range(1, 6)]
    assert select_model(bt, 8) == "ets"


def test_fallback_on_final_fit_error(monkeypatch, log_df, holidays_df):
    monkeypatch.setattr(fc, "select_sarimax_order", lambda y, X: FIXED_ORDERS)
    monkeypatch.setattr(fc, "run_backtest", _stub_backtest)
    monkeypatch.setattr(fc, "select_model", lambda bt, n: "sarimax")
    orig_fit = Sarimax.fit

    def fit(self, y, X=None):
        if y.index[-1].date() == AS_OF:  # the final fit uses all data up to as_of
            raise RuntimeError("final fit exploded")
        return orig_fit(self, y, X)

    monkeypatch.setattr(Sarimax, "fit", fit)
    r = run_tid("TID-JKT-0008", log_df, holidays_df, AS_OF)
    assert r.model == "seasonal_naive"
    assert r.diagnostics["fallback"] is True
    assert len(r.forecast) == 30


def test_explanations_pre_lebaran(monkeypatch, log_df, holidays_df):
    monkeypatch.setattr(fc, "run_backtest", _stub_backtest)
    monkeypatch.setattr(fc, "select_model", lambda bt, n: "sarimax")
    r = run_tid("TID-JKT-0007", log_df, holidays_df, AS_OF)
    assert r.model == "sarimax"
    assert r.orders is not None
    ex = r.explanations[date(2026, 3, 18)]
    assert 1 <= len(ex) <= 2
    assert any("pre-Lebaran" in s for s in ex)


def test_explanations_weekday_for_naive(monkeypatch, log_df, holidays_df):
    monkeypatch.setattr(fc, "select_sarimax_order", lambda y, X: FIXED_ORDERS)
    monkeypatch.setattr(fc, "run_backtest", _stub_backtest)
    monkeypatch.setattr(fc, "select_model", lambda bt, n: "seasonal_naive")
    r = run_tid("TID-JKT-0008", log_df, holidays_df, AS_OF)
    ex = r.explanations[date(2026, 3, 13)]  # a Friday
    assert len(ex) == 1
    assert ex[0].startswith("vs recent Fri ")
    assert ex[0].endswith("%")
