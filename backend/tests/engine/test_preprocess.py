from datetime import date

from engine.preprocess import MIN_TRAIN_DAYS, allowed_as_of_range, demand_series


def test_demand_series_censoring(log_df):
    tid, as_of = "TID-TNG-0006", date(2026, 10, 27)
    s = demand_series(log_df, tid, as_of)
    g = log_df[(log_df["tid"] == tid) & (log_df["date"] <= as_of)]
    zero_close = g[g["closing_balance"] == 0]
    assert len(zero_close) > 0
    for d in zero_close["date"]:
        assert s.isna()[str(d)]
    cash_out = g[(g["closing_balance"] == 0) & (g["withdrawal"] > 0)]
    assert s.isna().sum() >= len(cash_out)
    assert s.index[-1].date() == as_of and s.index.freq is not None


def test_allowed_range_dummy(log_df):
    assert allowed_as_of_range(log_df) == (date(2025, 12, 10), date(2026, 10, 27))


def test_min_train_days():
    assert MIN_TRAIN_DAYS == 280
