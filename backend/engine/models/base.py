"""Shared model protocol and quantile helpers (TR-22)."""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd

QUANTILES = (0.10, 0.50, 0.80, 0.90, 0.95)
QCOLS = ["q10", "q50", "q80", "q90", "q95"]


class Model(Protocol):
    name: str

    def fit(self, y: pd.Series, X: pd.DataFrame | None) -> Model: ...

    def predict(self, h: int, X_future: pd.DataFrame | None) -> pd.DataFrame: ...


def finalize_quantiles(df: pd.DataFrame) -> pd.DataFrame:
    """Clip at 0 and force non-decreasing across the quantile columns."""
    vals = np.maximum.accumulate(np.clip(df[QCOLS].to_numpy(dtype=float), 0, None), axis=1)
    return pd.DataFrame(vals, index=df.index, columns=QCOLS)


def future_index(y: pd.Series, h: int) -> pd.DatetimeIndex:
    return pd.date_range(y.index[-1] + pd.Timedelta(days=1), periods=h, freq="D")


def quantiles_from_intervals(index, point: np.ndarray, interval) -> pd.DataFrame:
    """Build the log-space quantile frame and back-transform to demand space.

    `interval(alpha)` returns (lower, upper) log-space arrays of the two-sided (1-alpha) interval.
    q > 0.5 -> upper bound with alpha = 2*(1-q); q < 0.5 -> lower bound with alpha = 2*(1-(1-q)) = 2*q;
    q == 0.5 -> point forecast.
    """
    cols = {}
    for q, c in zip(QUANTILES, QCOLS):
        if q == 0.5:
            cols[c] = np.asarray(point, dtype=float)
        elif q > 0.5:
            cols[c] = np.asarray(interval(2 * (1 - q))[1], dtype=float)
        else:
            cols[c] = np.asarray(interval(2 * q)[0], dtype=float)
    out = pd.DataFrame(cols, index=index)
    return finalize_quantiles(np.expm1(out))
