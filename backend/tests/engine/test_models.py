import numpy as np
import pandas as pd
import pytest

from engine.models import QCOLS
from engine.models.ets import Ets
from engine.models.sarimax import Sarimax, select_sarimax_order
from engine.models.seasonal_naive import SeasonalNaive

N = 400
WEEK = np.array([1.0, 0.8, 0.9, 1.0, 1.2, 1.6, 1.4])


def _idx(n=N, start="2024-01-01"):
    return pd.date_range(start, periods=n, freq="D")


def _series(noise=True, nan_frac=0.05):
    rng = np.random.default_rng(0)
    base = 5_000_000 * WEEK[np.arange(N) % 7]
    if noise:
        base = base * rng.lognormal(0, 0.1, N)
    y = pd.Series(base, index=_idx())
    if nan_frac:
        y[rng.random(N) < nan_frac] = np.nan
    return y


def _X(idx):
    dow = idx.day_of_week
    return pd.DataFrame({"flag": (dow == 4).astype(float)}, index=idx)


def _future_X(h=30):
    return _X(pd.date_range(_idx()[-1] + pd.Timedelta(days=1), periods=h, freq="D"))


MODELS = [SeasonalNaive, Ets, Sarimax]


@pytest.mark.parametrize("cls", MODELS)
def test_predict_shape_and_monotonic(cls):
    y = _series()
    m = cls().fit(y, _X(y.index))
    out = m.predict(30, _future_X(30))
    assert len(out) == 30
    assert list(out.columns) == QCOLS
    assert out.index[0] == y.index[-1] + pd.Timedelta(days=1)
    assert (out.diff(axis=1).iloc[:, 1:] >= 0).all().all()
    assert (out >= 0).all().all()


def test_seasonal_naive_repeats_week():
    y = _series(noise=False, nan_frac=0)
    out = SeasonalNaive().fit(y, None).predict(14, None)
    n = len(y)
    for k in range(1, 15):
        assert out["q50"].iloc[k - 1] == pytest.approx(y.iloc[n - 1 + k - 7 * -(-k // 7)])


def test_sarimax_uses_exog():
    idx = _idx()
    X = _X(idx)
    y = _series(nan_frac=0) * (1 + 0.8 * X["flag"])
    out = Sarimax(order=(1, 0, 0), seasonal_order=(0, 0, 0, 7)).fit(y, X).predict(30, _future_X(30))
    fx = _future_X(30)
    assert out["q50"][fx["flag"] == 1].iloc[0] >= 1.5 * out["q50"][fx["flag"] == 0].iloc[0]


def test_sarimax_order_grid_bounds():
    y = _series()
    (p, _d, q), (P, D, Q, s), aic = select_sarimax_order(y, _X(y.index))
    assert p <= 2 and q <= 2 and P <= 1 and Q <= 1 and D == 0 and s == 7
    assert np.isfinite(aic)


@pytest.mark.parametrize("cls", MODELS)
def test_models_tolerate_nan(cls):
    y = _series(nan_frac=0.15)
    cls().fit(y, _X(y.index)).predict(7, _future_X(7))
