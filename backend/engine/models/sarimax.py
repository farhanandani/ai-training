"""SARIMAX with exogenous calendar features on log1p (TR-22)."""

from __future__ import annotations

import itertools
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import adfuller

from .base import future_index, quantiles_from_intervals

S = 7
MAXITER = 200
GRID_MAXITER = 100  # grid search only; the selected model is refit with MAXITER


def _d(ly: pd.Series) -> int:
    v = ly.dropna()
    try:
        return 0 if adfuller(v, result_object=False)[1] < 0.05 else 1
    except ValueError:
        return 1


def _fit(
    ly: pd.Series, X, order, seasonal_order, d: int, caught: list[str] | None = None, maxiter: int = MAXITER
):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        res = SARIMAX(
            ly,
            exog=X,
            order=order,
            seasonal_order=seasonal_order,
            trend="c" if d == 0 else "n",
            enforce_stationarity=False,
            enforce_invertibility=False,
            concentrate_scale=True,
        ).fit(method="lbfgs", maxiter=maxiter, disp=False, cov_type="none")
    if caught is not None:
        caught += [str(x.message) for x in w]
    return res


def select_sarimax_order(y: pd.Series, X: pd.DataFrame | None) -> tuple[tuple, tuple, float]:
    ly = np.log1p(y.astype(float))
    d = _d(ly)
    best = None
    for p, q, P, Q in itertools.product((0, 1, 2), (0, 1, 2), (0, 1), (0, 1)):
        try:
            res = _fit(ly, X, (p, d, q), (P, 0, Q, S), d, maxiter=GRID_MAXITER)
        except (np.linalg.LinAlgError, ValueError):
            res = None  # candidate failed to fit; skip it
        if res is not None and np.isfinite(res.aic) and (best is None or res.aic < best[2]):
            best = ((p, d, q), (P, 0, Q, S), float(res.aic))
    if best is None:
        raise RuntimeError("SARIMAX grid search found no valid model")
    return best


class Sarimax:
    name = "sarimax"

    def __init__(
        self,
        order: tuple[int, int, int] | None = None,
        seasonal_order: tuple[int, int, int, int] | None = None,
    ):
        self.order = order
        self.seasonal_order = seasonal_order
        self.warnings: list[str] = []

    def fit(self, y: pd.Series, X: pd.DataFrame | None = None) -> Sarimax:
        self._y = y
        ly = np.log1p(y.astype(float))
        if self.order is None or self.seasonal_order is None:
            self.order, self.seasonal_order, self.aic = select_sarimax_order(y, X)
        d = self.order[1]
        self._res = _fit(ly, X, self.order, self.seasonal_order, d, self.warnings)
        return self

    def predict(self, h: int, X_future: pd.DataFrame | None = None) -> pd.DataFrame:
        idx = future_index(self._y, h)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fc = self._res.get_forecast(h, exog=X_future)
            point = np.asarray(fc.predicted_mean)

            def interval(alpha):
                ci = np.asarray(fc.conf_int(alpha=alpha))
                return ci[:, 0], ci[:, 1]

            out = quantiles_from_intervals(idx, point, interval)
        self.warnings += [str(x.message) for x in w]
        return out
