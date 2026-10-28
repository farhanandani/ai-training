"""Seasonal-naive baseline with empirical residual quantiles (TR-22)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import QCOLS, QUANTILES, finalize_quantiles, future_index

LAG = 7
RESID_DAYS = 180


def _fill_weekly(v: np.ndarray) -> np.ndarray:
    v = v.copy()
    for i in range(len(v)):
        if np.isnan(v[i]) and i >= LAG:
            v[i] = v[i - LAG]
    if np.isnan(v).any():
        v = np.where(np.isnan(v), np.nanmedian(v), v)
    return v


class SeasonalNaive:
    name = "seasonal_naive"

    def fit(self, y: pd.Series, X: pd.DataFrame | None = None) -> SeasonalNaive:
        self._y = y
        ly = np.log1p(y.to_numpy(dtype=float))
        self._last_week = _fill_weekly(ly)[-LAG:]
        resid = (ly[LAG:] - ly[:-LAG])[-RESID_DAYS:]
        resid = resid[~np.isnan(resid)]
        self._resid = resid if len(resid) else np.zeros(1)
        return self

    def predict(self, h: int, X_future: pd.DataFrame | None = None) -> pd.DataFrame:
        idx = future_index(self._y, h)
        point = np.array([self._last_week[k % LAG] for k in range(h)])
        cols = {}
        for q, c in zip(QUANTILES, QCOLS):
            shift = 0.0 if q == 0.5 else np.quantile(self._resid, q)
            cols[c] = point + shift
        return finalize_quantiles(np.expm1(pd.DataFrame(cols, index=idx)))
