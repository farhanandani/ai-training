"""Additive damped-trend ETS with weekly seasonality on log1p (TR-22)."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

from .base import future_index, quantiles_from_intervals
from .seasonal_naive import _fill_weekly


class Ets:
    name = "ets"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def fit(self, y: pd.Series, X: pd.DataFrame | None = None) -> Ets:
        self._y = y
        ly = pd.Series(_fill_weekly(np.log1p(y.to_numpy(dtype=float))), index=y.index)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self._res = ETSModel(
                ly, error="add", trend="add", damped_trend=True, seasonal="add", seasonal_periods=7
            ).fit(disp=False)
        self.warnings = [str(x.message) for x in w]
        return self

    def predict(self, h: int, X_future: pd.DataFrame | None = None) -> pd.DataFrame:
        idx = future_index(self._y, h)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            pred = self._res.get_prediction(start=len(self._y), end=len(self._y) + h - 1)
            point = np.asarray(pred.predicted_mean)

            def interval(alpha):
                sf = pred.summary_frame(alpha=alpha)
                return sf["pi_lower"].to_numpy(), sf["pi_upper"].to_numpy()

            out = quantiles_from_intervals(idx, point, interval)
        self.warnings += [str(x.message) for x in w]
        return out
