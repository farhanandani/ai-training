"""Per-TID forecast pipeline: order selection, backtest, selection, final fit, explanations (TR-22..TR-27, TR-41)."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import ENGINE_VERSION
from .backtest import HORIZON, lebaran_check, metrics, origins, run_backtest
from .calendar import features
from .models import QCOLS
from .models.ets import Ets
from .models.sarimax import Sarimax, select_sarimax_order
from .models.seasonal_naive import LAG, SeasonalNaive, _fill_weekly
from .preprocess import MIN_TRAIN_DAYS, demand_series

SELECTION_H = 14
TIE_EPS = 0.001
PREFERENCE = ["seasonal_naive", "ets", "sarimax"]

EXPLAIN_LABELS: dict[str, str] = {
    "fitri_ramp_near": "pre-Lebaran",
    "fitri_ramp_far": "pre-Lebaran",
    "fitri_thr": "THR",
    "fitri_ramadan": "Ramadan",
    "fitri_holiday": "Lebaran holiday",
    "fitri_return": "post-Lebaran return",
    "year_end": "year-end",
    "payday": "payday",
    "pre_holiday": "pre-holiday",
    "holiday": "holiday",
}

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DATE_KEYS = ("origin", "date", "fitri_day")


@dataclass
class ForecastResult:
    tid: str
    as_of: date
    engine_version: str
    model: str
    orders: dict | None
    forecast: pd.DataFrame
    explanations: dict[date, list[str]]
    backtest: dict
    lebaran_check: dict | None
    diagnostics: dict
    fitted_q50: pd.Series

    def to_payload(self) -> dict:
        return {
            "tid": self.tid,
            "as_of": self.as_of.isoformat(),
            "engine_version": self.engine_version,
            "model": self.model,
            "orders": _jsonable(self.orders),
            "forecast": [
                {"date": d.date().isoformat(), **{c: int(row[c]) for c in QCOLS}}
                for d, row in self.forecast.iterrows()
            ],
            "explanations": {d.isoformat(): list(v) for d, v in self.explanations.items()},
            "backtest": _jsonable(self.backtest),
            "lebaran_check": _jsonable(self.lebaran_check),
            "diagnostics": _jsonable(self.diagnostics),
            "fitted_in_sample_q50": [
                {"date": d.date().isoformat(), "q50": int(v)} for d, v in self.fitted_q50.items()
            ],
        }

    @classmethod
    def from_payload(cls, d: dict) -> ForecastResult:
        fc = pd.DataFrame(d["forecast"])
        idx = pd.DatetimeIndex(pd.to_datetime(fc["date"]), name="date")
        forecast = fc.set_index(idx)[QCOLS].astype("int64")
        fit = d["fitted_in_sample_q50"]
        fitted = pd.Series(
            [r["q50"] for r in fit],
            index=pd.DatetimeIndex(pd.to_datetime([r["date"] for r in fit])),
            dtype="int64",
            name="q50",
        )
        return cls(
            tid=d["tid"],
            as_of=date.fromisoformat(d["as_of"]),
            engine_version=d["engine_version"],
            model=d["model"],
            orders=d["orders"],
            forecast=forecast,
            explanations={date.fromisoformat(k): list(v) for k, v in d["explanations"].items()},
            backtest=_parse(d["backtest"]),
            lebaran_check=_parse(d["lebaran_check"]),
            diagnostics=d["diagnostics"],
            fitted_q50=fitted,
        )


def _jsonable(o):
    """Dates -> ISO strings, NaN -> None, numpy scalars -> Python, tuples -> lists."""
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_jsonable(v) for v in o]
    if isinstance(o, pd.Timestamp):
        return o.date().isoformat()
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def _parse(o, key: str | None = None):
    """Inverse of _jsonable for backtest / lebaran_check structures."""
    if isinstance(o, dict):
        return {k: _parse(v, k) for k, v in o.items()}
    if isinstance(o, list):
        return [_parse(v) for v in o]
    if key in _DATE_KEYS and isinstance(o, str):
        return date.fromisoformat(o)
    if o is None and key in ("y", "q10", "q50", "q90", "wape", "mape", "mae", "coverage"):
        return float("nan")
    return o


def select_model(bt: dict, n_origins: int) -> str:
    """Lowest WAPE at SELECTION_H; ties (< TIE_EPS) go to the simpler model; > half failed origins = ineligible."""
    failures = bt.get("_failures", [])
    scores: dict[str, float] = {}
    for name in PREFERENCE:
        if name not in bt:
            continue
        n_fail = sum(1 for f in failures if f["error"].startswith(f"{name}:"))
        if n_fail > n_origins / 2:
            continue
        w = metrics(bt[name], SELECTION_H)["wape"]
        if w is not None and math.isfinite(w):
            scores[name] = w
    if not scores:
        raise ValueError("no eligible model")
    best = min(scores.values())
    return next(n for n in PREFERENCE if n in scores and scores[n] - best < TIE_EPS)


def _make(name: str, orders):
    if name == "sarimax":
        return Sarimax(order=orders[0], seasonal_order=orders[1])
    return Ets() if name == "ets" else SeasonalNaive()


def _to_int(a) -> np.ndarray:
    return np.rint(np.nan_to_num(np.clip(np.asarray(a, dtype=float), 0, None), nan=0.0)).astype("int64")


def _fitted_q50(name: str, model, y: pd.Series) -> pd.Series:
    """In-sample one-step predictions, back-transformed from log1p."""
    if name == "seasonal_naive":
        v = _fill_weekly(np.log1p(y.to_numpy(dtype=float)))
        log_fit = np.concatenate([v[:LAG], v[:-LAG]])
    else:
        log_fit = np.asarray(model._res.fittedvalues, dtype=float)
    return pd.Series(_to_int(np.expm1(log_fit)), index=y.index, name="q50")


def _sarimax_explanations(model: Sarimax, X_fut: pd.DataFrame) -> dict[date, list[str]]:
    beta = model._res.params
    out: dict[date, list[str]] = {}
    for d, row in X_fut.iterrows():
        contrib = [
            (label, math.expm1(float(beta[c]) * float(row[c])))
            for c, label in EXPLAIN_LABELS.items()
            if row[c] != 0 and c in beta.index
        ]
        contrib.sort(key=lambda t: -abs(t[1]))
        out[d.date()] = [f"{label} {u * 100:+.0f}%" for label, u in contrib[:2]]
    return out


def _weekday_explanations(y: pd.Series, as_of: date, q50: pd.Series) -> dict[date, list[str]]:
    recent = y[y.index > pd.Timestamp(as_of - timedelta(days=28))]
    base = recent.groupby(recent.index.day_of_week).mean()
    out: dict[date, list[str]] = {}
    for d, v in q50.items():
        b = base.get(d.day_of_week, float("nan"))
        if not math.isfinite(b) or b <= 0:
            out[d.date()] = []
        else:
            out[d.date()] = [f"vs recent {_WEEKDAYS[d.day_of_week]} {(v / b - 1) * 100:+.0f}%"]
    return out


def _final(name: str, orders, y, X_hist, X_fut, as_of):
    model = _make(name, orders).fit(y, X_hist)
    pred = model.predict(HORIZON, X_fut)
    if not np.isfinite(pred[QCOLS].to_numpy(dtype=float)).all():
        # garbage must not reach planning; the TR-41 fallback takes over
        raise ValueError("non-finite forecast quantiles")
    if name == "sarimax":
        expl = _sarimax_explanations(model, X_fut)
    else:
        expl = _weekday_explanations(y, as_of, pred["q50"])
    forecast = pd.DataFrame({c: _to_int(pred[c]) for c in QCOLS}, index=pred.index.rename("date"))
    return model, forecast, expl, _fitted_q50(name, model, y)


def _dedupe(xs: list[str]) -> list[str]:
    return list(dict.fromkeys(xs))


def run_tid(tid: str, log: pd.DataFrame, holidays: pd.DataFrame, as_of: date) -> ForecastResult | None:
    t0 = time.perf_counter()
    y = demand_series(log, tid, as_of)
    if len(y) < MIN_TRAIN_DAYS:
        return None
    fut = pd.date_range(pd.Timestamp(as_of) + pd.Timedelta(days=1), periods=HORIZON, freq="D")
    # raises HolidaysNotCovered before any fitting when the table stops short of as_of + 30
    X_all = features(y.index.append(fut), holidays, y.index[0].date())
    X_hist, X_fut = X_all.loc[y.index], X_all.loc[fut]
    diag: dict = {"warnings": [], "fallback": False}

    sarimax_orders = None
    aic = None
    try:
        order, seasonal, aic = select_sarimax_order(y, X_hist)
        sarimax_orders = (order, seasonal)
    except Exception as e:  # noqa: BLE001  SARIMAX is skipped; the TID still gets a forecast
        diag["warnings"].append(f"sarimax order selection failed: {e}")

    bt: dict = {}
    name: str | None = None
    cause = "no model selected"
    try:
        bt = run_backtest(y, holidays, as_of, sarimax_orders)
        name = select_model(bt, len(origins(y.index[0].date(), as_of)))
    except Exception as e:  # noqa: BLE001  falls back below (TR-41)
        # diag["warnings"].append(f"backtest/selection failed: {e}")
        cause = f"backtest/selection failed: {e}"
        diag["warnings"].append(cause)

    leb = None
    if name is not None:
        try:
            leb = lebaran_check(y, holidays, as_of, name, sarimax_orders)
        except Exception as e:  # noqa: BLE001  reported separately, never blocks the forecast
            diag["warnings"].append(f"lebaran check failed: {e}")

    try:
        if name is None:
            # raise RuntimeError("no model selected")
            raise RuntimeError(cause)
        model, forecast, expl, fitted = _final(name, sarimax_orders, y, X_hist, X_fut, as_of)
    except Exception as e:  # noqa: BLE001  TR-41 fallback to seasonal naive
        diag["fallback"] = True
        # diag["error"] = f"{name}: {e}"
        diag["error"] = f"{name}: {e}" if name is not None else str(e)
        name = "seasonal_naive"
        model, forecast, expl, fitted = _final(name, None, y, X_hist, X_fut, as_of)

    diag["warnings"] = _dedupe(diag["warnings"] + list(getattr(model, "warnings", [])))
    diag["fit_seconds"] = round(time.perf_counter() - t0, 3)
    orders = None
    if name == "sarimax":
        orders = {"order": list(sarimax_orders[0]), "seasonal_order": list(sarimax_orders[1]), "aic": aic}
    return ForecastResult(
        tid=tid,
        as_of=as_of,
        engine_version=ENGINE_VERSION,
        model=name,
        orders=orders,
        forecast=forecast,
        explanations=expl,
        backtest=bt,
        lebaran_check=leb,
        diagnostics=diag,
        fitted_q50=fitted,
    )
