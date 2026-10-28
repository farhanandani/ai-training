from datetime import date

import pandas as pd
import pytest

from engine.calendar import FEATURE_COLS, HolidaysNotCovered, features, fitri_days

EXPECTED = [
    "dow_1", "dow_2", "dow_3", "dow_4", "dow_5", "dow_6", "payday",
    "fitri_ramadan", "fitri_thr", "fitri_ramp_far", "fitri_ramp_near",
    "fitri_holiday", "fitri_return", "year_end", "new_year_day",
    "pre_holiday", "holiday", "trend",
]  # fmt: skip


def test_fitri_days(holidays_df):
    assert fitri_days(holidays_df) == [date(2025, 3, 31), date(2026, 3, 20)]


def _f(holidays_df, a, b):
    return features(pd.date_range(a, b), holidays_df, date(2024, 10, 28))


def test_feature_buckets(holidays_df):
    f = _f(holidays_df, "2025-12-01", "2026-05-31")
    assert list(f.columns) == EXPECTED == FEATURE_COLS
    v = lambda col, d: f.loc[d, col]
    assert all(v("fitri_ramp_near", f"2026-03-{d}") == 1 for d in range(15, 20))
    assert v("fitri_ramp_near", "2026-03-14") == 0
    assert all(v("fitri_holiday", f"2026-03-{d}") == 1 for d in range(20, 27))
    assert v("fitri_holiday", "2026-03-27") == 0 and v("fitri_return", "2026-03-27") == 1
    assert v("payday", "2026-01-25") == 1 and v("payday", "2026-02-03") == 1
    assert v("payday", "2026-02-04") == 0
    assert v("year_end", "2025-12-20") == 1 and v("year_end", "2025-12-19") == 0
    assert v("pre_holiday", "2026-05-13") == 1
    assert v("new_year_day", "2026-01-01") == 1
    assert v("trend", "2025-12-01") == pytest.approx(399 / 365)


def test_features_raise_when_holidays_short(holidays_df):
    short = holidays_df[holidays_df["date"] <= date(2026, 10, 31)]
    with pytest.raises(HolidaysNotCovered) as e:
        _f(short, "2026-10-01", "2026-11-26")
    assert e.value.code == "HOLIDAYS_NOT_COVERED"


def test_features_ok_with_new_year_after(holidays_df):
    assert len(_f(holidays_df, "2026-10-01", "2026-12-31")) == 92
