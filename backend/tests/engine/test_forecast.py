import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import engine.forecast as fc
from engine.calendar import HolidaysNotCovered
from engine.forecast import ForecastResult, run_tid, select_model
from engine.models import QCOLS
from engine.models.ets import Ets
from engine.models.sarimax import Sarimax

AS_OF = date(2026, 3, 6)
NAMES = {"seasonal_naive", "ets", "sarimax"}
FIXED_ORDERS = ((1, 1, 1), (1, 0, 1, 7), 0.0)
FAST_ORDERS = ((0, 0, 0), (0, 0, 0, 7), 0.0)  # what the grid picks for most dummy TIDs


def _stub_backtest(y, holidays, as_of, sarimax_orders):
    return {"seasonal_naive": [], "ets": [], "sarimax": [], "_failures": []}


# def test_run_tid_shapes(log_df, holidays_df):
def test_run_tid_shapes(monkeypatch, log_df, holidays_df):
    monkeypatch.setattr(fc, "select_sarimax_order", lambda y, X: FAST_ORDERS)
    r = run_tid("TID-JKT-0008", log_df, holidays_df, AS_OF)
    assert isinstance(r, ForecastResult)
    assert len(r.forecast) == 30
    assert r.forecast.index[0].date() == date(2026, 3, 7)
    assert list(r.forecast.columns) == QCOLS
    assert all(pd.api.types.is_integer_dtype(r.forecast[c]) for c in QCOLS)
    assert r.model in NAMES
    assert pd.api.types.is_integer_dtype(r.fitted_q50)
    payload = r.to_payload()
    # json.dumps(payload)
    json.dumps(payload, allow_nan=False)
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
    monkeypatch.setattr(fc, "select_sarimax_order", lambda y, X: FAST_ORDERS)
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


def test_fallback_on_non_finite_forecast(monkeypatch, log_df, holidays_df):
    monkeypatch.setattr(fc, "select_sarimax_order", lambda y, X: FAST_ORDERS)
    monkeypatch.setattr(fc, "run_backtest", _stub_backtest)
    monkeypatch.setattr(fc, "select_model", lambda bt, n: "ets")

    def predict(self, h, X_future=None):
        idx = pd.date_range(self._y.index[-1] + pd.Timedelta(days=1), periods=h, freq="D")
        return pd.DataFrame(np.inf, index=idx, columns=QCOLS)

    monkeypatch.setattr(Ets, "predict", predict)
    r = run_tid("TID-JKT-0008", log_df, holidays_df, AS_OF)
    assert r.model == "seasonal_naive"
    assert r.diagnostics["fallback"] is True
    assert "non-finite" in r.diagnostics["error"]
    assert np.isfinite(r.forecast[QCOLS].to_numpy(dtype=float)).all()


def test_too_few_origins_falls_back(monkeypatch, log_df, holidays_df):
    monkeypatch.setattr(fc, "select_sarimax_order", lambda y, X: FAST_ORDERS)
    tid = "TID-JKT-0008"
    short = log_df[(log_df["tid"] == tid) & (log_df["date"] > AS_OF - timedelta(days=300))]
    r = run_tid(tid, short, holidays_df, AS_OF)
    assert r is not None
    assert r.model == "seasonal_naive"
    assert r.diagnostics["fallback"] is True
    assert r.backtest == {}
    assert "origins" in r.diagnostics["error"]


# ------------------------------------------------------- incremental refit (AC5)
def _prior(model, orders=None):
    idx = pd.date_range("2026-03-07", periods=30, freq="D", name="date")
    bt = {"seasonal_naive": [{"origin": date(2026, 1, 1), "date": date(2026, 1, 2), "y": 1.0, "q50": 1.0}]}
    return ForecastResult(
        tid="TID-JKT-0008",
        as_of=AS_OF,
        engine_version="x",
        model=model,
        orders=orders,
        forecast=pd.DataFrame({c: np.ones(30, dtype="int64") for c in QCOLS}, index=idx),
        explanations={},
        backtest=bt,
        lebaran_check={"origin": date(2025, 3, 1), "fitri_day": date(2025, 3, 31), "metrics": {"wape": 0.1}},
        diagnostics={"warnings": [], "fallback": False},
        fitted_q50=pd.Series(dtype="int64"),
    )


def _forbid(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("incremental refit must not run the grid / backtest / lebaran check")

    for f in ("select_sarimax_order", "run_backtest", "lebaran_check", "select_model"):
        monkeypatch.setattr(fc, f, boom)


def test_incremental_reuses_prior_model_and_orders(monkeypatch, log_df, holidays_df):
    _forbid(monkeypatch)
    made = []

    class _Res:
        params = pd.Series({"payday": 0.1})

    class StubSarimax:  # stub fit: records nothing heavy, mimics the fitted SARIMAX surface
        warnings = ()

        def fit(self, y, X=None):
            self._res = _Res()
            self._res.fittedvalues = np.log1p(y.fillna(0).to_numpy())
            return self

        def predict(self, h, X_future=None):
            return pd.DataFrame({c: np.full(h, 1e8) for c in QCOLS}, index=X_future.index[:h])

    def spy(name, orders):
        made.append((name, orders))
        return StubSarimax()

    monkeypatch.setattr(fc, "_make", spy)
    prior = _prior("sarimax", {"order": [1, 0, 1], "seasonal_order": [1, 0, 0, 7], "aic": 12.5})
    r = fc.run_tid_incremental("TID-JKT-0008", log_df, holidays_df, AS_OF, prior)
    assert made == [("sarimax", ((1, 0, 1), (1, 0, 0, 7)))]
    assert r.model == "sarimax"
    assert r.orders == {"order": [1, 0, 1], "seasonal_order": [1, 0, 0, 7], "aic": 12.5}
    assert r.diagnostics["backtest_stale"] is True and r.diagnostics["fallback"] is False
    assert r.backtest is prior.backtest and r.lebaran_check is prior.lebaran_check
    assert len(r.forecast) == 30 and len(r.fitted_q50) > 0
    json.dumps(r.to_payload(), allow_nan=False)


def test_incremental_fallback_keeps_stale_backtest(monkeypatch, log_df, holidays_df):
    _forbid(monkeypatch)

    def predict(self, h, X_future=None):
        idx = pd.date_range("2026-03-07", periods=h, freq="D")
        return pd.DataFrame({c: np.full(h, np.nan) for c in QCOLS}, index=idx)

    monkeypatch.setattr(Ets, "fit", lambda self, y, X=None: self)
    monkeypatch.setattr(Ets, "predict", predict)
    r = fc.run_tid_incremental("TID-JKT-0008", log_df, holidays_df, AS_OF, _prior("ets"))
    assert r.model == "seasonal_naive"
    assert r.diagnostics["fallback"] is True and r.diagnostics["error"].startswith("ets:")
    assert r.diagnostics["backtest_stale"] is True
    assert r.backtest == _prior("ets").backtest


def test_incremental_short_history_returns_none(log_df, holidays_df):
    short = log_df[log_df["date"] >= date(2025, 12, 1)]
    assert fc.run_tid_incremental("TID-JKT-0008", short, holidays_df, AS_OF, _prior("ets")) is None
