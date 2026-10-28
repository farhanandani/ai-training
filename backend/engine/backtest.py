"""Rolling-origin backtest, pooled metrics and Lebaran check (TR-23, TR-24)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .calendar import features, fitri_days
from .models.ets import Ets
from .models.sarimax import Sarimax
from .models.seasonal_naive import SeasonalNaive
from .preprocess import MIN_TRAIN_DAYS

HORIZON = 30
N_ORIGINS = 8
MIN_ORIGINS = 4
STEP = 14


def origins(series_start: date, as_of: date) -> list[date]:
    out = [as_of - timedelta(days=HORIZON + STEP * i) for i in range(N_ORIGINS)]
    out = [o for o in out if (o - series_start).days + 1 >= MIN_TRAIN_DAYS]
    if len(out) < MIN_ORIGINS:
        raise ValueError(f"only {len(out)} usable backtest origins (need {MIN_ORIGINS})")
    return out


def _make(name: str, sarimax_orders):
    if name == "seasonal_naive":
        return SeasonalNaive()
    if name == "ets":
        return Ets()
    order, seasonal = sarimax_orders
    return Sarimax(order=order, seasonal_order=seasonal)


def _candidates(sarimax_orders) -> list[str]:
    names = ["seasonal_naive", "ets"]
    if sarimax_orders is not None:
        names.append("sarimax")
    return names


def _feature_frame(y: pd.Series, holidays, as_of: date) -> pd.DataFrame:
    end = max(y.index[-1], pd.Timestamp(as_of))
    return features(pd.date_range(y.index[0], end, freq="D"), holidays, y.index[0].date())


def _score_origin(name, y, X_all, origin: date, sarimax_orders) -> list[dict]:
    ts = pd.Timestamp(origin)
    y_tr = y[y.index <= ts]
    X_tr = X_all.loc[y_tr.index]
    fut = pd.date_range(ts + pd.Timedelta(days=1), periods=HORIZON, freq="D")
    model = _make(name, sarimax_orders).fit(y_tr, X_tr)
    pred = model.predict(HORIZON, X_all.loc[fut])
    actual = y.reindex(pred.index)
    return [
        {
            "origin": origin,
            "date": d.date(),
            "y": float(actual.loc[d]),
            "q10": float(pred.loc[d, "q10"]),
            "q50": float(pred.loc[d, "q50"]),
            "q90": float(pred.loc[d, "q90"]),
        }
        for d in pred.index
    ]


def run_backtest(y: pd.Series, holidays, as_of: date, sarimax_orders) -> dict[str, list[dict]]:
    X_all = _feature_frame(y, holidays, as_of)
    res: dict[str, list[dict]] = {n: [] for n in _candidates(sarimax_orders)}
    failures: list[dict] = []
    for o in origins(y.index[0].date(), as_of):
        for name in res:
            try:
                res[name] += _score_origin(name, y, X_all, o, sarimax_orders)
            except Exception as e:  # noqa: BLE001  a failing model contributes no rows for this origin
                failures.append({"origin": o, "error": f"{name}: {e}"})
    res["_failures"] = failures
    return res


def metrics(rows: list[dict], h: int) -> dict:
    sel = [r for r in rows if 0 < (r["date"] - r["origin"]).days <= h and not np.isnan(r["y"])]
    if not sel:
        return {
            "wape": float("nan"),
            "mape": float("nan"),
            "mae": float("nan"),
            "coverage": float("nan"),
            "n": 0,
        }
    yy = np.array([r["y"] for r in sel])
    q50 = np.array([r["q50"] for r in sel])
    err = np.abs(yy - q50)
    pos = yy > 0
    return {
        "wape": float(err.sum() / yy.sum()) if yy.sum() > 0 else float("nan"),
        "mape": float(np.mean(err[pos] / yy[pos])) if pos.any() else float("nan"),
        "mae": float(err.mean()),
        "coverage": float(np.mean([r["q10"] <= r["y"] <= r["q90"] for r in sel])),
        "n": len(sel),
    }


def lebaran_check(y: pd.Series, holidays, as_of: date, model_name: str, sarimax_orders) -> dict | None:
    start = y.index[0].date()
    cands = [
        f - timedelta(days=14)
        for f in fitri_days(holidays)
        if f - timedelta(days=14) + timedelta(days=HORIZON) <= as_of
        and (f - timedelta(days=14) - start).days + 1 >= MIN_TRAIN_DAYS
    ]
    if not cands:
        return None
    origin = max(cands)
    X_all = _feature_frame(y, holidays, as_of)
    rows = _score_origin(model_name, y, X_all, origin, sarimax_orders)
    return {
        "origin": origin,
        "fitri_day": origin + timedelta(days=14),
        "rows": rows,
        "metrics": metrics(rows, HORIZON),
    }
